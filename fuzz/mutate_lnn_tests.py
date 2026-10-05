"""pytest plugin: run LNN's own tests with the DATA they feed to Model.add_data() mutated, and judge the outcome.

Select the mutation with the environment variable NESY_LNN_MUT = "<kind>:<seed>" and the output file with NESY_LNN_OUT.

Kinds (the inputs of the tests are the facts and bounds given to add_data):
  none        no change (baseline run; its snapshots are the reference for `reorder`)
  boundary    replace a truth value by one of 0, 1e-12, 1e-9, 1e-5, 0.5, 1-1e-5, 1-1e-9, 1 (propositional bounds and groundings)
  perturb     move a bound by +-1e-9 .. 0.1 (kept inside [0,1] and ordered)
  complement  TRUE <-> FALSE, x -> 1 - x, (l, u) -> (1 - u, 1 - l)
  reorder     reverse the order of the entries of every data dict (the result must not depend on insertion order)

The tests' own assertions encode the ORIGINAL expected values, so an AssertionError after a mutation is expected and is not a
finding. Findings are: an exception that is not an AssertionError, an inference that does not finish within 8 s, a bound that
is NaN or outside [0,1], a node whose lower bound exceeds its upper bound without being reported as a contradiction, and (for
`reorder`) bounds that differ from the baseline run.
"""
import json
import logging
import math
import os
import random
import signal

import pytest

logging.disable(logging.CRITICAL)
MUT = os.environ.get("NESY_LNN_MUT", "none:0")
KIND, SEED = MUT.split(":")[0], int(MUT.split(":")[1])
OUT = os.environ.get("NESY_LNN_OUT")
RNG = random.Random(SEED)
CURRENT = {"test": None}
EVENTS = []          # findings
SNAPSHOTS = {}       # test -> list of {node: [[l, u], ...]} after each infer/train
OUTCOMES = {}        # test -> outcome label
SPECIAL = [0.0, 1e-12, 1e-9, 1e-5, 0.5, 1 - 1e-5, 1 - 1e-9, 1.0]


class MutantHang(Exception):
    pass


def _alarm(signum, frame):
    raise MutantHang()


signal.signal(signal.SIGALRM, _alarm)


def _mutate_value(v):
    from lnn import Fact
    if isinstance(v, dict):
        items = list(v.items())
        if KIND == "reorder":
            items = items[::-1]
        return {k: _mutate_value(x) for k, x in items}
    if KIND == "reorder":
        return v
    if isinstance(v, Fact):
        if KIND == "complement":
            return {Fact.TRUE: Fact.FALSE, Fact.FALSE: Fact.TRUE}.get(v, v)
        if KIND in ("boundary", "perturb") and RNG.random() < 0.5 and v in (Fact.TRUE, Fact.FALSE):
            x = RNG.choice(SPECIAL) if KIND == "boundary" else min(max(float(v == Fact.TRUE) + RNG.choice([-1, 1]) * RNG.choice([1e-9, 1e-3, 0.1]), 0.0), 1.0)
            return (x, x)
        return v
    if isinstance(v, bool):
        return (not v) if KIND == "complement" else v
    if isinstance(v, (int, float)):
        lo, up = float(v), float(v)
    elif isinstance(v, tuple) and len(v) == 2:
        lo, up = float(v[0]), float(v[1])
    else:
        return v
    if KIND == "complement":
        return (1 - up, 1 - lo) if isinstance(v, tuple) else 1 - lo
    if KIND == "boundary":
        x = RNG.choice(SPECIAL)
        return (x, x)
    if KIND == "perturb":
        d = RNG.choice([1e-9, 1e-6, 1e-3, 0.1])
        lo2 = min(max(lo + RNG.choice([-1, 1]) * d, 0.0), 1.0)
        up2 = min(max(up + RNG.choice([-1, 1]) * d, 0.0), 1.0)
        return (min(lo2, up2), max(lo2, up2))
    return v


def _snapshot(model):
    snap, problems = {}, []
    for node in list(model.graph.nodes):
        try:
            d = node.get_data()
        except BaseException:
            continue
        if d is None:
            continue
        try:
            t = d.detach().reshape(-1, 2) if d.numel() % 2 == 0 and d.numel() else None
        except Exception:
            t = None
        if t is None:
            continue
        rows = [[float(a), float(b)] for a, b in t.tolist()]
        snap[f"{node.name}|{getattr(node, 'formula_number', '')}"] = rows
        for lo, up in rows:
            if not (math.isfinite(lo) and math.isfinite(up)):
                problems.append((node.name, "non-finite bound", lo, up))
            elif lo < -1e-6 or up > 1 + 1e-6:
                problems.append((node.name, "bound outside [0,1]", lo, up))
            elif lo > up + 1e-4:            # float32 accumulation over many operands stays below this
                try:
                    flagged = bool(node.is_contradiction())
                except BaseException:
                    flagged = False
                if not flagged:
                    problems.append((node.name, "lower > upper not reported as contradiction", lo, up))
    return snap, problems


def _install():
    import lnn
    from lnn import Model
    orig_add, orig_infer, orig_train = Model.add_data, Model.infer, Model.train

    def add_data(self, data, *a, **kw):
        if KIND != "none":
            items = list(data.items())
            if KIND == "reorder":
                items = items[::-1]
            data = {k: _mutate_value(v) for k, v in items}
        return orig_add(self, data, *a, **kw)

    def run_guard(orig):
        def wrapped(self, *a, **kw):
            signal.setitimer(signal.ITIMER_REAL, 8)
            try:
                out = orig(self, *a, **kw)
            except MutantHang:
                if CURRENT["test"] is not None:
                    raise
                # a module that runs inference at import time (no test function): record and let collection continue
                EVENTS.append({"test": "(import-time code)", "kind": KIND, "finding": "hang", "detail": "an inference at import time did not finish within 8 s"})
                return (0, 0)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            snap, problems = _snapshot(self)
            SNAPSHOTS.setdefault(CURRENT["test"], []).append(snap)
            for p in problems:
                EVENTS.append({"test": CURRENT["test"], "kind": KIND, "finding": "invariant", "detail": p})
            return out
        return wrapped
    Model.add_data, Model.infer, Model.train = add_data, run_guard(orig_infer), run_guard(orig_train)


def pytest_configure(config):
    _install()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    CURRENT["test"] = item.nodeid.split("tests/")[-1]
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    out = yield
    rep = out.get_result()
    if rep.when != "call":
        return
    name = item.nodeid.split("tests/")[-1]
    if rep.passed:
        OUTCOMES[name] = "pass"
    elif call.excinfo is not None:
        et = call.excinfo.type
        if issubclass(et, AssertionError):
            OUTCOMES[name] = "assertion"                  # stale expectation after the mutation: not a finding
        elif issubclass(et, MutantHang):
            OUTCOMES[name] = "hang"
            EVENTS.append({"test": name, "kind": KIND, "finding": "hang", "detail": "an inference did not finish within 8 s"})
        else:
            OUTCOMES[name] = "exception"
            EVENTS.append({"test": name, "kind": KIND, "finding": "exception", "detail": f"{et.__name__}: {str(call.excinfo.value)[:160]}"})


def pytest_sessionfinish(session, exitstatus):
    if OUT:
        with open(OUT, "w") as f:
            json.dump({"kind": KIND, "seed": SEED, "outcomes": OUTCOMES, "events": EVENTS, "snapshots": SNAPSHOTS}, f)
