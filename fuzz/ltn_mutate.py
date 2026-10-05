"""Mutate the inputs of LTNtorch's own tests (operator calls recorded by trace_ltn.py) and judge the results.

Operators (inputs of the tests):
  boundary    replace a random subset of truth values by 0, 1, 1e-9, 1-1e-9, the library threshold 1e-4, ...
  perturb     add +-1e-9 .. 0.1 (clipped to [0,1])
  complement  x -> 1 - x
  permute     shuffle the elements (same permutation for both operands / along the aggregated axes)
  swap        swap the two operands of a binary connective
  stable      flip the `stable` flag of the operator
  float64     run in double precision
Oracles: closed formula (ltn_oracle.py); metamorphic relations (permutation keeps results permuted, aggregators are
permutation-invariant, commutativity, stable vs unstable differ by at most the documented projection, float64 ~ float32).
"""
import argparse
import json
import math
import os
import random
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "LTNtorch"))
import numpy as np
import torch
from ltn import fuzzy_ops as F
import ltn_oracle as O

SEEDS = os.path.join(HERE, "..", "results", "seeds", "ltn_seeds.json")
SPECIAL = [0.0, 1.0, 1e-9, 1 - 1e-9, 1e-5, 1e-4, 1.01e-4, 1 - 1e-4, 0.5]
COMMUTATIVE = {"AndMin", "AndProd", "AndLuk", "OrMax", "OrProbSum", "OrLuk"}
AGG = {"AggregMin": O.agg_min, "AggregMean": O.agg_mean, "AggregPMean": None, "AggregPMeanError": None}


def tab_oracle(op, ctor):
    t = O.connective_table()
    key = op + ("S" if ctor.get("stable", True) else "U") if op in ("AndProd", "OrProbSum", "ImpliesReichenbach", "ImpliesGoguen") else op
    return t[key][2]


def agg_oracle(op, ctor):
    p, st = ctor.get("p", 2), ctor.get("stable", True)
    if op == "AggregMin":
        return lambda xs, m=None: O.agg_min(xs, m)
    if op == "AggregMean":
        return lambda xs, m=None: O.agg_mean(xs, m)
    if op == "AggregPMean":
        return lambda xs, m=None: O.agg_pmean(xs, m, p, st)
    return lambda xs, m=None: O.agg_pmean_error(xs, m, p, st)


def mutate_tensor(arr, rng, kind):
    a = np.array(arr, dtype=np.float64)
    flat = a.reshape(-1)
    if kind == "boundary":
        for i in rng.sample(range(flat.size), max(1, flat.size // 3)):
            flat[i] = rng.choice(SPECIAL)
    elif kind == "perturb":
        for i in range(flat.size):
            flat[i] = min(max(flat[i] + rng.choice([-1, 1]) * rng.choice([1e-9, 1e-6, 1e-3, 0.1]), 0.0), 1.0)
    elif kind == "complement":
        flat[:] = 1.0 - flat
    return a.reshape(np.shape(arr))


def run_seed(seed, rng, n, out):
    op, ctor, args, kw = seed["op"], seed["ctor"], seed["args"], seed["kwargs"]
    if op == "Equiv":                      # needs its two inner operators; covered by ltn_fuzz.equiv_props
        return
    is_agg = op in AGG
    if is_agg and kw.get("mask") is not None and np.shape(kw["mask"]) != np.shape(args[0]):
        return                             # the library's own negative test (mask of the wrong shape must be rejected)
    kinds = ["boundary", "perturb", "complement", "permute", "stable", "float64"] + ([] if is_agg else ["swap"])
    for _ in range(n):
        kind = rng.choice(kinds)
        ctor_m = dict(ctor)
        dtype = torch.float32
        arrs = [np.array(a, dtype=np.float64) for a in args]
        mask = None if kw.get("mask") is None else np.array(kw["mask"], dtype=bool)
        perm = None
        if kind in ("boundary", "perturb", "complement"):
            arrs = [mutate_tensor(a, rng, kind) for a in arrs]
        elif kind == "permute":
            if is_agg:
                ax = rng.randrange(arrs[0].ndim)
                perm = np.random.RandomState(rng.randrange(10 ** 6)).permutation(arrs[0].shape[ax])
                arrs = [np.take(arrs[0], perm, axis=ax)]
                mask = None if mask is None else np.take(mask, perm, axis=ax)
            else:
                perm = np.random.RandomState(rng.randrange(10 ** 6)).permutation(arrs[0].size)
                arrs = [a.reshape(-1)[perm].reshape(a.shape) for a in arrs]
        elif kind == "swap":
            arrs = arrs[::-1]
        elif kind == "stable":
            if "stable" not in ctor_m:
                continue
            ctor_m["stable"] = not ctor_m["stable"]
        elif kind == "float64":
            dtype = torch.float64
        op_obj = getattr(F, op)(**ctor_m)
        tens = [torch.tensor(a, dtype=dtype) for a in arrs]
        rec = {"test": seed["test"].split("::")[-1], "op": op, "mutation": kind}
        try:
            if is_agg:
                dim = kw.get("dim")
                dim = tuple(dim) if isinstance(dim, list) else dim
                kwargs = {k: v for k, v in kw.items() if k in ("keepdim",)}
                if dim is not None:
                    kwargs["dim"] = dim
                if mask is not None:
                    kwargs["mask"] = torch.tensor(mask)
                got = op_obj(tens[0], **kwargs).double().numpy()
                dims = dim if dim is not None else tuple(range(arrs[0].ndim))
                ref = O.agg_axes(agg_oracle(op, ctor_m), np.asarray(tens[0].double().numpy()), dims, kw.get("keepdim", False), mask)
                bad_nan = np.isnan(got) & ~np.isnan(ref)
                diff = np.where(np.isnan(got) & np.isnan(ref), 0.0, np.abs(got - ref))
                tol = 2e-5
                fails = []
                if bad_nan.any() or float(np.nanmax(diff, initial=0.0)) > tol:
                    fails.append(("formula_mismatch", f"max diff {float(np.nanmax(diff, initial=0.0)):.3g}"))
                if np.any((got < -1e-6) | (got > 1 + 1e-6)):
                    fails.append(("range", f"value outside [0,1]: {got.min()}..{got.max()}"))
                agg_axes_ = set(a_ % arrs[0].ndim for a_ in (dim if isinstance(dim, tuple) else ([dim] if dim is not None else range(arrs[0].ndim))))
                if kind == "permute" and ax in agg_axes_:              # aggregate must not depend on element order
                    base = op_obj(torch.tensor(np.array(args[0]), dtype=dtype), **{**kwargs, **({"mask": torch.tensor(np.array(kw["mask"], dtype=bool))} if kw.get("mask") is not None else {})}).double().numpy()
                    if not np.allclose(base, got, atol=1e-5, equal_nan=True):
                        fails.append(("permutation_invariance", f"{np.max(np.abs(base - got)):.3g}"))
            else:
                got = op_obj(*tens).double().numpy()
                ref = tab_oracle(op, ctor_m)(*[a for a in [t.double().numpy() for t in tens]])
                diff = np.abs(got - np.asarray(ref))
                fails = []
                if float(diff.max(initial=0.0)) > 3e-6:
                    fails.append(("formula_mismatch", f"max diff {float(diff.max()):.3g}"))
                if np.any((got < 0) | (got > 1)) or not np.all(np.isfinite(got)):
                    fails.append(("range", "value outside [0,1] or non-finite"))
                if kind == "swap" and op in COMMUTATIVE:
                    base = op_obj(*[torch.tensor(np.array(a), dtype=dtype) for a in args]).double().numpy()
                    if not np.allclose(base, got, atol=3e-6):
                        fails.append(("commutativity", f"{np.max(np.abs(base - got)):.3g}"))
                if kind == "permute":
                    base = op_obj(*[torch.tensor(np.array(a), dtype=dtype) for a in args]).double().numpy().reshape(-1)[perm]
                    if not np.allclose(base, got.reshape(-1), atol=3e-6):
                        fails.append(("permutation_equivariance", f"{np.max(np.abs(base - got.reshape(-1))):.3g}"))
                if kind == "stable":                                   # stable and unstable differ only by the projection
                    other = getattr(F, op)(**dict(ctor_m, stable=not ctor_m["stable"]))
                    if op != "ImpliesGoguen":
                        dd = np.max(np.abs(other(*tens).double().numpy() - got))
                        if dd > 3e-4:
                            fails.append(("stable_vs_unstable", f"{dd:.3g} > projection bound 3e-4"))
                if kind == "float64":
                    g32 = op_obj(*[torch.tensor(a, dtype=torch.float32) for a in arrs]).double().numpy()
                    if not np.allclose(g32, got, atol=1e-5):
                        fails.append(("precision_float32_vs_float64", f"{np.max(np.abs(g32 - got)):.3g}"))
                    if op_obj(*tens).dtype != torch.float64:
                        fails.append(("output_dtype", f"float64 input gives {op_obj(*tens).dtype}"))
            for name, detail in fails:
                out.append({**rec, "finding": name, "detail": detail})
            out.append({**rec, "finding": "ok" if not fails else "fail", "count": 1})
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            out.append({**rec, "finding": "exception", "detail": f"{type(e).__name__}: {str(e)[:160]}"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-seed", type=int, default=30)
    ap.add_argument("--rng", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "results", "ltn_mutation_results.jsonl"))
    a = ap.parse_args()
    rng = random.Random(a.rng)
    seeds = json.load(open(SEEDS))
    out = []
    for s in seeds:
        run_seed(s, rng, a.per_seed, out)
    with open(a.out, "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    import collections
    mutants = sum(1 for r in out if r["finding"] in ("ok", "fail", "exception"))
    c = collections.Counter((r["finding"], r["op"]) for r in out if r["finding"] not in ("ok", "fail"))
    print(f"{len(seeds)} seeds, {mutants} mutants, results -> {a.out}")
    byf = collections.Counter(r["finding"] for r in out if r["finding"] not in ("ok", "fail"))
    print("findings by kind:", dict(byf))
    for (k, op), v in sorted(c.items()):
        print(f"  {k:30s} {op:22s} {v}")


if __name__ == "__main__":
    main()
