
import json
import math
import os
import random
import signal
import sys
import time

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
from mutation_helpers import mutate_values, short  # noqa: E402  (same folder)

KIND = os.environ.get("LTN_MUT_KIND", "none")
SEED = int(os.environ.get("LTN_MUT_SEED", "0"))
OUT = os.environ.get("LTN_MUT_OUT")
TIMEOUT = int(os.environ.get("LTN_MUT_TMO", "20"))
TRACE = os.environ.get("LTN_MUT_TRACE") == "1"      # record inputs and outputs of every mutated call (show_inputs.py)

COMMUTATIVE = {"AndMin", "AndProd", "AndLuk", "OrMax", "OrProbSum", "OrLuk"}
# Numeric oracle for the answer-preserving kinds: the mutated call must match an unmutated call on the same
# inputs within this absolute tolerance. (The tests compare with torch.equal, which is exact, so a failed assert
# alone is not evidence of a problem; this is.) stable uses the documented projection bound 3e-4 of
# fuzz/ltn_mutate.py.
TOL = {"permute": 1e-5, "swap": 3e-6, "stable": 3e-4, "float64": 1e-5}

CUR = {"test": None, "applied": [], "range": [], "n_calls": 0, "programs": [], "depth": 0, "diverge": [], "trace": []}


def _rng(tag):
    return random.Random(f"{SEED}:{CUR['test']}:{CUR['n_calls']}:{tag}")


def _is_float(x):
    import torch
    return isinstance(x, torch.Tensor) and x.is_floating_point()


def _like(arr, ref):
    import torch
    t = torch.tensor(arr, dtype=ref.dtype, device=ref.device)
    return t.requires_grad_(True) if ref.requires_grad else t


def _norm_axes(dim, ndim):
    if dim is None:
        return list(range(ndim))
    dims = [dim] if isinstance(dim, int) else list(dim)
    return [d % ndim for d in dims]


def _mutate_call(self, op, args, kwargs, is_agg):
    """Return (new_args, new_kwargs, post, description, record) or None when this call cannot be changed by KIND."""
    import torch
    rng = _rng("ltn")
    floats = [i for i, a in enumerate(args) if _is_float(a)]
    if not floats:
        return None

    if KIND == "values":
        for _ in range(20):
            sub = rng.choice(["boundary", "boundary", "perturb", "complement"])
            new = list(args)
            changed = False
            for i in floats:
                old = args[i].detach().cpu().double().numpy()
                arr = mutate_values(old, rng, sub)
                changed |= not np.array_equal(arr, old)
                new[i] = _like(arr, args[i])
            if changed:
                rec = {"op": op, "before": short(args[floats[0]].detach().cpu().numpy()),
                       "after": short(new[floats[0]].detach().cpu().numpy())}
                return new, kwargs, None, f"{op}: {sub} on {len(floats)} operand(s)", rec
        return None

    if KIND == "permute":
        if is_agg:
            xs = args[0]
            dim = kwargs.get("dim", args[1] if len(args) > 1 else None)
            axes = [a for a in _norm_axes(dim, xs.dim()) if xs.shape[a] >= 2]
            if not axes:
                return None
            ax = rng.choice(axes)
            perm = torch.tensor(np.random.RandomState(rng.randrange(10 ** 6)).permutation(xs.shape[ax]))
            if bool((perm == torch.arange(len(perm))).all()):
                perm = torch.roll(perm, 1)
            new = list(args)
            new[0] = xs.index_select(ax, perm.to(xs.device))
            kw = dict(kwargs)
            if isinstance(kw.get("mask"), torch.Tensor):
                if kw["mask"].shape != xs.shape:      # the library's own negative test (wrong mask shape must be rejected)
                    return None
                kw["mask"] = kw["mask"].index_select(ax, perm.to(kw["mask"].device))
            rec = {"op": op, "before": short(xs.detach().cpu().numpy()), "after": short(new[0].detach().cpu().numpy())}
            return new, kw, None, f"{op}: permute axis {ax} (aggregate must not change)", rec
        tens = [a for a in args if hasattr(a, "numel")]
        n = tens[0].numel() if tens else 0
        if n < 2 or any(a.numel() != n for a in tens) or len(tens) != len(args):
            return None
        perm = np.random.RandomState(rng.randrange(10 ** 6)).permutation(n)
        if (perm == np.arange(n)).all():
            perm = np.roll(perm, 1)
        pt = torch.tensor(perm)
        inv = torch.tensor(np.argsort(perm))
        new = [a.reshape(-1)[pt.to(a.device)].reshape(a.shape) for a in args]

        def post(out):
            if isinstance(out, torch.Tensor) and out.numel() == n:
                return out.reshape(-1)[inv.to(out.device)].reshape(out.shape)
            return out
        rec = {"op": op, "before": short(args[0].detach().cpu().numpy()), "after": short(new[0].detach().cpu().numpy())}
        return new, kwargs, post, f"{op}: permute {n} element(s), result permuted back", rec

    if KIND == "swap":
        if op not in COMMUTATIVE or len(args) != 2:
            return None
        rec = {"op": op, "before": short(args[0].detach().cpu().numpy()), "after": short(args[1].detach().cpu().numpy())}
        return [args[1], args[0]], kwargs, None, f"{op}: swap the two operands", rec

    if KIND == "float64":
        if all(args[i].dtype == torch.float64 for i in floats):
            return None
        ref = args[floats[0]].dtype
        new = [a.double() if _is_float(a) else a for a in args]

        def post(out):
            return out.to(ref) if isinstance(out, torch.Tensor) and out.is_floating_point() else out
        rec = {"op": op, "before": {"dtype": str(ref)}, "after": {"dtype": "torch.float64"}}
        return new, kwargs, post, f"{op}: float32 -> float64 (result cast back)", rec
    return None


def _reference(self, orig, args, kwargs):
    """The unmutated call on the original inputs (None if it raises)."""
    CUR["depth"] += 1
    try:
        return orig(self, *args, **kwargs)
    except Exception:
        return None
    finally:
        CUR["depth"] -= 1


def _diff(name, out, ref):
    """Numeric oracle: the mutated call must agree with an unmutated call on the same inputs."""
    import torch
    if not (isinstance(out, torch.Tensor) and isinstance(ref, torch.Tensor)) or out.shape != ref.shape:
        return
    a, b = out.detach().double(), ref.detach().double()
    if bool((torch.isnan(a) != torch.isnan(b)).any()):
        CUR["diverge"].append(f"{name}: NaN pattern differs")
        return
    ok = ~torch.isnan(a)
    if bool(ok.any()):
        d = float((a[ok] - b[ok]).abs().max())
        if d > TOL[KIND]:
            CUR["diverge"].append(f"{name}: max diff {d:.3g} > {TOL[KIND]:g}")


def _vals(x):
    import torch
    return short(x.detach().cpu().double().numpy()) if isinstance(x, torch.Tensor) else x


def _trace(name, orig_args, orig_kwargs, args, kwargs, ref, out, desc, flag):
    import torch
    CUR["trace"].append({
        "call": CUR["n_calls"], "op": name, "mutation": desc,
        "original_input": [_vals(a) for a in orig_args if isinstance(a, torch.Tensor)],
        "fuzzed_input": [_vals(a) for a in args if isinstance(a, torch.Tensor)],
        "extra": {**{k: (list(v) if isinstance(v, tuple) else ("tensor" if isinstance(v, torch.Tensor) else v))
                     for k, v in orig_kwargs.items()}, **flag},
        "output_original_input": _vals(ref),
        "output_fuzzed_input": _vals(out),
    })


def _check(op, out):
    import torch
    if isinstance(out, torch.Tensor) and out.is_floating_point():
        v = out.detach()
        if torch.isnan(v).any() or (v < -1e-6).any() or (v > 1 + 1e-6).any():
            CUR["range"].append(f"{op} -> min {float(v.min())!r} max {float(v.max())!r}")
    return out


def _install():
    import ltn.fuzzy_ops as F
    classes = [c for n, c in vars(F).items() if isinstance(c, type)
               and issubclass(c, (F.ConnectiveOperator, F.AggregationOperator))
               and c not in (F.ConnectiveOperator, F.UnaryConnectiveOperator, F.BinaryConnectiveOperator,
                             F.AggregationOperator)
               and "__call__" in c.__dict__ and c.__name__ != "SatAgg"]

    def make(orig, cls):
        name = cls.__name__
        is_agg = issubclass(cls, F.AggregationOperator)

        def wrapped(self, *args, **kwargs):
            if CUR["depth"] > 0 or KIND == "none":
                CUR["depth"] += 1
                try:
                    return orig(self, *args, **kwargs) if CUR["depth"] > 1 else _check(name, orig(self, *args, **kwargs))
                finally:
                    CUR["depth"] -= 1
            CUR["n_calls"] += 1
            flipped = None
            post = None
            orig_args, orig_kwargs = args, kwargs
            mutated = False
            if KIND == "stable":
                if hasattr(self, "stable"):
                    flipped = self.stable
                    CUR["applied"].append(f"{name}: stable {flipped} -> {not flipped}")
                    CUR["programs"].append({"op": name, "before": {"stable": flipped}, "after": {"stable": not flipped}})
                    self.stable = not flipped
                    mutated = True
            else:
                r = _mutate_call(self, name, args, kwargs, is_agg)
                if r:
                    args, kwargs, post, desc, rec = r
                    CUR["applied"].append(desc)
                    CUR["programs"].append(rec)
                    mutated = True
            CUR["depth"] += 1
            try:
                out = orig(self, *args, **kwargs)
            finally:
                CUR["depth"] -= 1
                if flipped is not None:
                    self.stable = flipped
            if post is not None:
                out = post(out)
            if mutated and (KIND in TOL or TRACE):
                ref = _reference(self, orig, orig_args, orig_kwargs)
                if KIND in TOL:
                    _diff(name, out, ref)
                if TRACE:
                    _trace(name, orig_args, orig_kwargs, args, kwargs, ref, out, CUR["applied"][-1],
                           {"stable_original": flipped, "stable_fuzzed": not flipped} if flipped is not None else {})
            return _check(name, out)
        return wrapped

    for cls in classes:
        cls.__call__ = make(cls.__call__, cls)


def pytest_configure(config):
    _install()


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout(f"TIMEOUT>{TIMEOUT}s")


def _begin(item):
    CUR.update(test=item.nodeid, applied=[], range=[], n_calls=0, programs=[], depth=0, diverge=[], trace=[])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    _begin(item)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT)
    CUR["t0"] = time.time()
    try:
        yield
    finally:
        signal.alarm(0)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if call.when != "call" and not (call.when == "setup" and rep.outcome != "passed"):
        return
    exc_type = exc_msg = None
    if call.excinfo is not None:
        exc_type = call.excinfo.type.__name__
        exc_msg = str(call.excinfo.value)[:300]
    rec = {"kind": KIND, "seed": SEED, "test": item.nodeid, "outcome": rep.outcome,
           "when": call.when, "exc_type": exc_type, "exc_msg": exc_msg,
           "applied": bool(CUR["applied"]), "mutations": list(CUR["applied"]), "programs": list(CUR["programs"]),
           "range_violations": list(CUR["range"]), "divergences": list(CUR["diverge"]), "trace": list(CUR["trace"]), "n_calls": CUR["n_calls"],
           "secs": round(time.time() - CUR.get("t0", time.time()), 3)}
    if OUT:
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
