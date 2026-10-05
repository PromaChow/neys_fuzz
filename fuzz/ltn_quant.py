"""Differential check of LTN's broadcasting, dimension and mask logic.

A random quantified formula over 1-3 variables is built from LTNObjects (tables of truth values) with ltn.Connective and
ltn.Quantifier, and evaluated a second time by brute force: one scalar evaluation per variable assignment, aggregators
computed with the closed formulas of ltn_oracle.py. Any difference is a defect in grounding/broadcasting/aggregation, not
in the fuzzy operators themselves (those are checked separately).
"""
import itertools
import random

import numpy as np
import torch
import ltn
from ltn import fuzzy_ops as F
import ltn_oracle as O

BIN = ["AndMin", "AndLuk", "AndProdS", "AndProdU", "OrMax", "OrLuk", "OrProbSumS", "OrProbSumU", "ImpliesKleeneDienes",
       "ImpliesGodel", "ImpliesLuk", "ImpliesReichenbachS", "ImpliesReichenbachU", "ImpliesGoguenS", "ImpliesGoguenU"]
UN = ["NotStandard", "NotGodel"]
SPECIAL = [0.0, 1e-9, 1e-5, 1e-4, 0.5, 1 - 1e-4, 1 - 1e-7, 1.0]
FORALL = [("AggregPMeanError", {"p": 1}), ("AggregPMeanError", {"p": 2}), ("AggregPMeanError", {"p": 3}),
          ("AggregPMeanError", {"p": 2, "stable": False}), ("AggregMin", {}), ("AggregMean", {})]
EXISTS = [("AggregPMean", {"p": 1}), ("AggregPMean", {"p": 2}), ("AggregPMean", {"p": 5}),
          ("AggregPMean", {"p": 2, "stable": False}), ("AggregMean", {})]


def oracle_agg(cname, kw):
    if cname == "AggregMin":
        return lambda xs: O.agg_min(xs)
    if cname == "AggregMean":
        return lambda xs: O.agg_mean(xs)
    if cname == "AggregPMean":
        return lambda xs: O.agg_pmean(xs, None, kw.get("p", 2), kw.get("stable", True))
    return lambda xs: O.agg_pmean_error(xs, None, kw.get("p", 2), kw.get("stable", True))


def val(rng):
    return rng.choice(SPECIAL) if rng.random() < 0.3 else rng.random()


def build(rng, vars_, sizes, depth):
    """Random formula tree. Leaves are tables over a random ordered subset of the variables."""
    if depth == 0 or rng.random() < 0.3:
        k = rng.randint(1, min(2, len(vars_)))
        vs = rng.sample(vars_, k)
        table = np.array([[val(rng)] for _ in range(int(np.prod([sizes[v] for v in vs])))], dtype=np.float32)
        table = table.reshape([sizes[v] for v in vs])
        return ("atom", tuple(vs), table)
    if rng.random() < 0.25:
        return ("un", rng.choice(UN), build(rng, vars_, sizes, depth - 1))
    return ("bin", rng.choice(BIN), build(rng, vars_, sizes, depth - 1), build(rng, vars_, sizes, depth - 1))


def ltn_eval(node):
    if node[0] == "atom":
        return ltn.LTNObject(torch.tensor(node[2]), list(node[1]))
    tab = O.connective_table()
    if node[0] == "un":
        cname, kw, _, _ = tab[node[1]]
        return ltn.Connective(getattr(F, cname)(**kw))(ltn_eval(node[2]))
    cname, kw, _, _ = tab[node[1]]
    return ltn.Connective(getattr(F, cname)(**kw))(ltn_eval(node[2]), ltn_eval(node[3]))


def desc(node):
    if node[0] == "atom":
        return {"atom": list(node[1]), "table": node[2].tolist()}
    if node[0] == "un":
        return {"op": node[1], "arg": desc(node[2])}
    return {"op": node[1], "left": desc(node[2]), "right": desc(node[3])}


def free_vars(node):
    if node[0] == "atom":
        return set(node[1])
    return set().union(*[free_vars(c) for c in node[2:] if isinstance(c, tuple)])


def naive(node, asg):
    """-> (value, ambiguous). `ambiguous` is set when a discontinuous operator (Godel/Goguen implication, Godel negation)
    sees operands closer than 1e-6: float32 (LTN) and float64 (this reference) may then fall on different branches."""
    tab = O.connective_table()
    if node[0] == "atom":
        return float(np.float64(node[2][tuple(asg[v] for v in node[1])])), False
    if node[0] == "un":
        v, a = naive(node[2], asg)
        amb = a or (node[1] == "NotGodel" and abs(v) <= 1e-6)
        return float(tab[node[1]][2](np.float64(v))), amb
    x, ax = naive(node[2], asg)
    y, ay = naive(node[3], asg)
    amb = ax or ay
    if node[1] in ("ImpliesGodel", "ImpliesGoguenU"):
        amb = amb or abs(x - y) <= 1e-6
    elif node[1] == "ImpliesGoguenS":
        amb = amb or abs(O.pi0(x) - y) <= 1e-6
    return float(tab[node[1]][2](np.float64(x), np.float64(y))), amb


def run(rng, n, rec):
    for case in range(n * 3):
        names = ["x", "y", "z"][:rng.randint(1, 3)]
        sizes = {v: rng.randint(1, 4) for v in names}
        ind = {v: np.array([[val(rng)] for _ in range(sizes[v])], dtype=np.float32) for v in names}
        tree = build(rng, names, sizes, rng.randint(1, 3))
        fv = sorted(free_vars(tree))
        vobj = {v: ltn.Variable(v, torch.tensor(ind[v])) for v in names}
        try:
            f = ltn_eval(tree)
        except BaseException as e:
            rec("quant_connective_tree:exception", False, f"{type(e).__name__}: {str(e)[:160]}")
            continue
        # unquantified: compare the full grounding
        lv = list(f.free_vars)
        got = f.value.double().numpy()
        dims_ok = sorted(lv) == fv and list(got.shape) == [sizes[v] for v in lv]
        rec("quant_grounding_shape", dims_ok, f"free vars {lv} shape {list(got.shape)} expected vars {fv}")
        if dims_ok:
            ref = np.empty(got.shape)
            amb = np.zeros(got.shape, dtype=bool)
            for idx in itertools.product(*[range(sizes[v]) for v in lv]):
                ref[idx], amb[idx] = naive(tree, dict(zip(lv, idx)))
            d = float(np.max(np.abs(got - ref)[~amb])) if (~amb).any() else 0.0
            rec("quant_grounding_values", d <= 1e-5, f"max diff {d:.3g}", free=lv, sizes=sizes, tree=desc(tree))
        # quantify a random subset of the free variables, optionally guarded
        if not fv:
            continue
        k = rng.randint(1, len(fv))
        qv = rng.sample(fv, k)
        is_forall = rng.random() < 0.5
        cname, kw = rng.choice(FORALL if is_forall else EXISTS)
        Q = ltn.Quantifier(getattr(F, cname)(**{a: b for a, b in kw.items()}), quantifier="f" if is_forall else "e")
        guard = rng.random() < 0.5
        thr = rng.random()
        cond_names = None
        try:
            if guard:
                cond_names = rng.sample(names, rng.randint(1, min(2, len(names))))
                if len(cond_names) == 1:
                    fn = lambda a, t=thr: a.value[:, 0] < t
                else:
                    fn = lambda a, b, t=thr: (a.value[:, 0] + b.value[:, 0]) < t * 2
                out = Q([vobj[v] for v in qv], f, cond_vars=[vobj[v] for v in cond_names], cond_fn=fn)
            else:
                out = Q([vobj[v] for v in qv], f)
        except BaseException as e:
            rec("quant_quantifier:exception", False, f"{type(e).__name__}: {str(e)[:200]}", guard=guard, qv=qv, cond=cond_names, tree_vars=fv)
            continue
        olv = list(out.free_vars)
        rest = [v for v in lv if v not in qv] if guard is False else None
        # remaining free variables = those of the formula (plus guard-only variables) not quantified
        expected_vars = sorted(set(fv + (cond_names or [])) - set(qv))
        shape_ok = sorted(olv) == expected_vars and list(out.value.shape) == [sizes[v] for v in olv]
        rec("quant_result_shape", shape_ok, f"result free vars {olv} shape {list(out.value.shape)} expected vars {expected_vars}", guard=guard, qv=qv, cond=cond_names)
        if not shape_ok:
            continue
        agg = oracle_agg(cname, kw)
        rep = 1.0 if is_forall else 0.0
        ref = np.empty(out.value.shape) if olv else np.empty(())
        ambq = np.zeros(out.value.shape, dtype=bool) if olv else np.zeros((), dtype=bool)
        all_vars = sorted(set(fv + (cond_names or [])))
        for idx in itertools.product(*[range(sizes[v]) for v in olv]):
            base = dict(zip(olv, idx))
            xs = []
            any_amb = False
            for qidx in itertools.product(*[range(sizes[v]) for v in qv]):
                asg = {**base, **dict(zip(qv, qidx))}
                full = dict(asg)
                for v in all_vars:
                    full.setdefault(v, 0)
                if guard:
                    if len(cond_names) == 1:
                        sel = ind[cond_names[0]][asg[cond_names[0]], 0] < thr
                    else:
                        sel = (np.float32(ind[cond_names[0]][asg[cond_names[0]], 0]) + np.float32(ind[cond_names[1]][asg[cond_names[1]], 0])) < thr * 2
                    if not sel:
                        continue
                v_, a_ = naive(tree, full)
                xs.append(v_)
                any_amb = any_amb or a_
            if guard and not xs:
                r = rep
            else:
                r = agg(np.array(xs))
                if guard and (r != r):
                    r = rep
            if olv:
                ref[idx] = r
                ambq[idx] = any_amb
            else:
                ref = np.float64(r)
                ambq = np.array(any_amb)
        gotq = out.value.double().numpy()
        if np.any(np.isnan(gotq)) and not np.any(np.isnan(ref)):
            rec("quant_nan_result", False, f"NaN result for {cname}{kw} guard={guard}", qv=qv, cond=cond_names)
        else:
            ambq = np.asarray(ambq)
            diff = np.abs(gotq - ref)
            d = float(np.max(diff[~ambq])) if (~ambq).any() else 0.0
            rec(f"quant_values:{'guarded' if guard else 'plain'}", d <= 2e-5, f"{cname}{kw} max diff {d:.3g}", qv=qv, cond=cond_names, free=fv, sizes=sizes, tree=desc(tree), thr=thr, got=gotq.tolist(), ref=np.asarray(ref).tolist(), ind={k: v[:, 0].tolist() for k, v in ind.items()}, agg=[cname, kw], forall=is_forall)
        rec("quant_result_dtype", out.value.dtype == torch.float32, f"result dtype {out.value.dtype} (guard={guard})")
