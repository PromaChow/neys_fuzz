"""Property-based fuzzing of LTNtorch (Logic Tensor Networks) against closed-form fuzzy-logic semantics.

LTN is fuzzy, not probabilistic: truth values are degrees in [0,1] and every operator has a closed formula (printed in the
class docstrings of ltn/fuzzy_ops.py). The reference is therefore ltn_oracle.py (float64 NumPy), plus mathematical laws.

Property groups (same dimensions as the probabilistic-logic rounds):
  conn_*   connectives vs documented formula, range, classical boundary, commutativity, monotonicity, De Morgan,
           definability of implications, modus-ponens soundness, equivalence
  agg_*    aggregators vs formula, mask semantics, dim/keepdim, permutation, monotonicity, dtype, invalid p
  grad_*   autograd vs central finite differences (float64); finiteness of gradients at boundary values
  special  inputs at/around the library's own thresholds (eps = 1e-4, float32 limits), float64 vs float32
  quant_*  random quantified formulas vs a naive per-assignment evaluation (broadcasting / dim / mask logic)
  input_*  invalid inputs: clean error vs crash vs silent acceptance
"""
import argparse
import itertools
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
import ltn
from ltn import fuzzy_ops as F
import ltn_oracle as O

OUT = os.path.join(HERE, "..", "results", "ltn_fuzz.jsonl")
TOL = 3e-6          # float32 vs float64 reference
SPECIAL = [0.0, 1e-12, 1e-9, 1e-7, 1e-5, 9.9e-5, 1e-4, 1.01e-4, 0.5, 1 - 1e-4, 1 - 1e-5, 1 - 1e-7, 1.0]
FINDINGS = []
COUNTS = {}


def rec(prop, ok, detail="", **kw):
    c = COUNTS.setdefault(prop, [0, 0])
    c[0 if ok else 1] += 1
    if not ok and c[1] <= 5:                                  # keep the first 5 examples per property
        FINDINGS.append({"prop": prop, "detail": detail, **kw})


def vals(rng, n, special=0.5):
    out = []
    for _ in range(n):
        out.append(rng.choice(SPECIAL) if rng.random() < special else rng.random())
    return out


def T(xs, dtype=torch.float32):
    return torch.tensor(xs, dtype=dtype)


def guarded(prop, fn):
    try:
        fn()
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        rec(prop + ":exception", False, f"{type(e).__name__}: {str(e)[:200]}")


def make_op(cname, kw):
    return getattr(F, cname)(**kw)


# ====================================================================== connectives
def conn_props(rng, n):
    table = O.connective_table()
    for name, (cname, kw, oracle, arity) in table.items():
        op = make_op(cname, kw)
        for _ in range(n):
            xs, ys = vals(rng, 32), vals(rng, 32)
            x, y = T(xs), T(ys)
            x64, y64 = x.double().numpy(), y.double().numpy()
            args = (x,) if arity == 1 else (x, y)
            ref_args = (x64,) if arity == 1 else (x64, y64)
            out = op(*args)
            ref = np.asarray(oracle(*ref_args), dtype=np.float64)
            got = out.double().numpy()
            d = np.max(np.abs(got - ref))
            rec(f"conn_formula:{name}", d <= TOL, f"max|impl-doc formula|={d:.3g}",
                x=float(x[int(np.argmax(np.abs(got - ref)))]), y=float(y[int(np.argmax(np.abs(got - ref)))]),
                impl=float(got[int(np.argmax(np.abs(got - ref)))]), formula=float(ref[int(np.argmax(np.abs(got - ref)))]))
            rec(f"conn_range:{name}", bool(np.all((got >= 0) & (got <= 1)) and np.all(np.isfinite(got))), "output outside [0,1] or non-finite")
        # classical boundary: inputs in {0,1} must reproduce Boolean logic
        bx, by = T([0., 0., 1., 1.]), T([0., 1., 0., 1.])
        boole = {"Not": lambda a, b: 1 - a, "And": lambda a, b: a * b, "Or": lambda a, b: np.maximum(a, b),
                 "Implies": lambda a, b: np.maximum(1 - a, b)}
        kind = "Not" if name.startswith("Not") else "And" if name.startswith("And") else "Or" if name.startswith("Or") else "Implies"
        got = (op(bx) if arity == 1 else op(bx, by)).double().numpy()
        want = boole[kind](bx.double().numpy(), by.double().numpy())
        dev = float(np.max(np.abs(got - want)))
        worst = int(np.argmax(np.abs(got - want)))
        rec(f"conn_boolean_boundary:{name}", dev <= 1e-3, f"max deviation from Boolean truth table={dev:.3g}",
            x=float(bx[worst]), y=float(by[worst]), impl=float(got[worst]), boolean=float(want[worst]))


def conn_laws(rng, n):
    tab = O.connective_table()
    ops = {k: make_op(v[0], v[1]) for k, v in tab.items()}
    bin_and = ["AndMin", "AndLuk", "AndProdS", "AndProdU"]
    bin_or = ["OrMax", "OrLuk", "OrProbSumS", "OrProbSumU"]
    imps = ["ImpliesKleeneDienes", "ImpliesGodel", "ImpliesLuk", "ImpliesReichenbachS", "ImpliesReichenbachU",
            "ImpliesGoguenS", "ImpliesGoguenU"]
    for _ in range(n):
        x, y, z = T(vals(rng, 48)), T(vals(rng, 48)), T(vals(rng, 48))
        for k in bin_and + bin_or + ["ImpliesLuk"]:
            if k.startswith("Implies"):
                continue
            a, b = ops[k](x, y), ops[k](y, x)
            d = float((a - b).abs().max())
            rec(f"conn_commutative:{k}", d <= TOL, f"|f(x,y)-f(y,x)|={d:.3g}")
        # monotonicity: raise x (or y) -> and/or do not decrease; implication: down in x, up in y
        x2 = torch.maximum(x, T(vals(rng, 48, 0.0)))
        for k in bin_and + bin_or:
            d = float((ops[k](x, y) - ops[k](x2, y)).max())
            rec(f"conn_monotone:{k}", d <= TOL, f"f decreased by {d:.3g} when x increased")
        for k in imps:
            d = float((ops[k](x2, y) - ops[k](x, y)).max())
            e = float((ops[k](x, y) - ops[k](x, torch.maximum(y, x2))).max())
            rec(f"conn_monotone_implication:{k}", d <= TOL and e <= TOL, f"antecedent-up rise={d:.3g}, consequent-up drop={e:.3g}")
        # De Morgan with the standard negation
        for a, o_, tol in (("AndMin", "OrMax", TOL), ("AndLuk", "OrLuk", TOL), ("AndProdU", "OrProbSumU", TOL),
                           ("AndProdS", "OrProbSumS", 3e-4)):
            d = float((ops[o_](x, y) - (1 - ops[a](1 - x, 1 - y))).abs().max())
            rec(f"conn_demorgan:{a}/{o_}", d <= tol, f"|Or(x,y)-(1-And(1-x,1-y))|={d:.3g}")
        # implication defined through its disjunction: Imp(x,y) = Or(1-x, y)
        for imp, orr, tol in (("ImpliesLuk", "OrLuk", TOL), ("ImpliesKleeneDienes", "OrMax", TOL),
                              ("ImpliesReichenbachU", "OrProbSumU", TOL), ("ImpliesReichenbachS", "OrProbSumS", 5e-4)):
            d = float((ops[imp](x, y) - ops[orr](1 - x, y)).abs().max())
            rec(f"conn_implication_is_or:{imp}", d <= tol, f"|Imp(x,y)-Or(1-x,y)|={d:.3g}")
        # modus-ponens soundness for the residuated pairs: And(x, Imp(x,y)) <= y
        for a, i, tol in (("AndLuk", "ImpliesLuk", TOL), ("AndMin", "ImpliesGodel", TOL),
                          ("AndProdU", "ImpliesGoguenU", 1e-5), ("AndProdS", "ImpliesGoguenS", 5e-4)):
            d = float((ops[a](x, ops[i](x, y)) - y).max())
            rec(f"conn_modus_ponens:{a}/{i}", d <= tol, f"And(x,Imp(x,y)) exceeds y by {d:.3g}")
        # implication reflexivity Imp(x,x) = 1 holds for the residuated implications (not for S-implications)
        for k in ("ImpliesGodel", "ImpliesLuk", "ImpliesGoguenS", "ImpliesGoguenU"):
            d = float((1 - ops[k](x, x)).max())
            tol = 3e-4 if k.endswith("S") else TOL
            rec(f"conn_reflexive_implication:{k}", d <= tol, f"1-Imp(x,x)={d:.3g}")
        # Imp(0, y) = 1 for every y (ex falso)
        zero = torch.zeros_like(y)
        for k in imps:
            d = float((1 - ops[k](zero, y)).max())
            rec(f"conn_ex_falso:{k}", d <= 3e-4, f"1-Imp(0,y)={d:.3g}", y=float(y[int((1 - ops[k](zero, y)).argmax())]))


def equiv_props(rng, n):
    pairs = [("AndMin", "ImpliesGodel"), ("AndLuk", "ImpliesLuk"), ("AndProd", "ImpliesGoguen")]
    for an, im in pairs:
        for stable in (True, False):
            kwa = {"stable": stable} if an == "AndProd" else {}
            kwi = {"stable": stable} if im == "ImpliesGoguen" else {}
            eq = F.Equiv(getattr(F, an)(**kwa), getattr(F, im)(**kwi))
            tag = f"{an}/{im}/{'S' if stable else 'U'}" if (an == "AndProd") else f"{an}/{im}"
            for _ in range(n):
                x, y = T(vals(rng, 48)), T(vals(rng, 48))
                rec(f"equiv_symmetric:{tag}", float((eq(x, y) - eq(y, x)).abs().max()) <= TOL, "Equiv(x,y) != Equiv(y,x)")
                d = float((1 - eq(x, x)).max())
                rec(f"equiv_reflexive:{tag}", d <= 3e-4, f"1-Equiv(x,x)={d:.3g}")


# ====================================================================== aggregators
def agg_props(rng, n):
    table = O.aggregator_table()
    for name, (cname, kw, oracle) in table.items():
        for _ in range(n):
            k = rng.randint(1, 12)
            xs = vals(rng, k)
            x = T(xs)
            mask = [rng.random() < 0.6 for _ in range(k)]
            op = getattr(F, cname)(**kw)
            ref = oracle(x.double().numpy())
            got = float(op(x, dim=0))
            rec(f"agg_formula:{name}", abs(got - ref) <= 1e-5, f"impl={got} formula={ref}", xs=xs)
            m = torch.tensor(mask)
            ref_m = oracle(x.double().numpy(), mask)
            got_m = float(op(x, dim=0, mask=m))
            same = (math.isnan(got_m) and math.isnan(ref_m)) or abs(got_m - ref_m) <= 1e-5
            rec(f"agg_mask_formula:{name}", same, f"impl={got_m} formula={ref_m} mask={mask}", xs=xs)
            if not any(mask):
                rec(f"agg_empty_mask_nan:{name}", not math.isnan(got_m), "empty mask returns NaN from the aggregator itself")
            if got == got:
                rec(f"agg_range:{name}", -1e-6 <= got <= 1 + 1e-6, f"value {got} outside [0,1]", xs=xs)
            perm = list(range(k)); rng.shuffle(perm)
            rec(f"agg_permutation:{name}", abs(float(op(x[perm], dim=0)) - got) <= 1e-6, "result depends on element order", xs=xs)
            # masked == filtered
            sel = [v for v, m_ in zip(xs, mask) if m_]
            if sel:
                rec(f"agg_mask_equals_filter:{name}", abs(float(op(T(sel), dim=0)) - got_m) <= 1e-6, "masked != aggregate of the selected elements")
            # monotone: raising one element never lowers the truth value
            i = rng.randrange(k)
            x2 = x.clone(); x2[i] = max(float(x2[i]), rng.random())
            rec(f"agg_monotone:{name}", float(op(x2, dim=0)) >= got - 1e-6, "value decreased when one element increased", xs=xs)
            # dtype consistency between masked and unmasked path
            rec(f"agg_dtype_consistent:{name}", op(x, dim=0, mask=m).dtype == op(x, dim=0).dtype,
                f"masked dtype {op(x, dim=0, mask=m).dtype} vs unmasked {op(x, dim=0).dtype}")
        # boundary: all ones -> 1, all zeros -> 0
        for k in (1, 3, 8):
            op = getattr(F, cname)(**kw)
            one, zero = float(op(torch.ones(k), dim=0)), float(op(torch.zeros(k), dim=0))
            rec(f"agg_boundary_ones:{name}", abs(one - 1) <= 1e-3, f"aggregate of k={k} ones = {one}")
            rec(f"agg_boundary_zeros:{name}", abs(zero) <= 1e-3, f"aggregate of k={k} zeros = {zero}")
        # dims / keepdim on a 3-D tensor
        x3 = torch.rand(3, 4, 5)
        op = getattr(F, cname)(**kw)
        for dims in [(0,), (1,), (2,), (0, 2), (1, 2), (0, 1, 2)]:
            for keep in (False, True):
                got = op(x3, dim=dims, keepdim=keep)
                moved = x3.double().numpy()
                axes = tuple(dims)
                rest = [a for a in range(3) if a not in axes]
                flat = np.transpose(moved, rest + list(axes)).reshape([moved.shape[a] for a in rest] + [-1])
                ref = np.array([oracle(flat[idx]) for idx in itertools.product(*[range(s) for s in flat.shape[:-1]])]).reshape(flat.shape[:-1])
                gshape = tuple(got.shape)
                exp_shape = tuple(1 if a in axes else moved.shape[a] for a in range(3)) if keep else tuple(moved.shape[a] for a in rest)
                rec(f"agg_dim_shape:{name}", gshape == exp_shape, f"dim={dims} keepdim={keep}: got shape {gshape}, expected {exp_shape}")
                if gshape == exp_shape:
                    g = got.double().numpy().reshape(ref.shape)
                    rec(f"agg_dim_values:{name}", np.max(np.abs(g - ref)) <= 1e-5, f"dim={dims} keepdim={keep} max diff {np.max(np.abs(g - ref)):.3g}")
    # invalid exponent p
    for cname in ("AggregPMean", "AggregPMeanError"):
        for p in (0, -1, 0.5, 100, float("inf")):
            try:
                v = float(getattr(F, cname)(p=p)(T([0.2, 0.8, 0.5]), dim=0))
                finite = math.isfinite(v) and 0 <= v <= 1
                rec(f"agg_invalid_p:{cname}", finite or p in (0.5,), f"p={p} silently returns {v}")
            except BaseException as e:
                rec(f"agg_invalid_p_raises:{cname}", True)


# ====================================================================== gradients
def num_grad(f, x, h=1e-6):
    g = torch.zeros_like(x)
    for i in range(x.numel()):
        e = torch.zeros_like(x); e.view(-1)[i] = h
        g.view(-1)[i] = (f(x + e) - f(x - e)).sum() / (2 * h)
    return g


def grad_props(rng, n):
    tab = O.connective_table()
    for name, (cname, kw, oracle, arity) in tab.items():
        if cname in ("NotGodel", "ImpliesGodel", "ImpliesGoguen", "AndMin", "OrMax") and False:
            continue
        op = make_op(cname, kw)
        for _ in range(n):
            xs = [rng.uniform(0.05, 0.95) for _ in range(6)]
            ys = [rng.uniform(0.05, 0.95) for _ in range(6)]
            x = T(xs, torch.float64).requires_grad_(True); y = T(ys, torch.float64).requires_grad_(arity == 2)
            f = (lambda a: op(a)) if arity == 1 else (lambda a: op(a, y.detach()))
            out0 = op(x) if arity == 1 else op(x, y)
            if not out0.requires_grad:
                rec(f"grad_graph_connected:{name}", False, "output is detached from the autograd graph (no gradient path)")
                break
            out0.sum().backward()
            ref = num_grad(f, T(xs, torch.float64))
            g = x.grad if x.grad is not None else torch.zeros_like(x)      # no graph path = zero gradient
            d = float((g - ref).abs().max())
            rec(f"grad_fd_interior:{name}", d <= 1e-4, f"autograd vs finite difference differ by {d:.3g}")
        # boundary points: gradient must be finite
        for bx, by in itertools.product([0.0, 1.0, 1e-9, 1 - 1e-9], repeat=2):
            x = T([bx], torch.float64).requires_grad_(True); y = T([by], torch.float64).requires_grad_(True)
            out = op(x) if arity == 1 else op(x, y)
            if not out.requires_grad:
                break
            out.sum().backward()
            gx = float(x.grad[0]) if x.grad is not None else 0.0
            gy = float(y.grad[0]) if (arity == 2 and y.grad is not None) else 0.0
            fin = math.isfinite(gx) and math.isfinite(gy)
            rec(f"grad_finite_boundary:{name}", fin, f"x={bx} y={by}: dx={gx} dy={gy}", x=bx, y=by)
    for name, (cname, kw, oracle) in O.aggregator_table().items():
        op = getattr(F, cname)(**kw)
        for _ in range(n):
            xs = [rng.uniform(0.05, 0.95) for _ in range(rng.randint(2, 7))]
            x = T(xs, torch.float64).requires_grad_(True)
            op(x, dim=0).backward()
            ref = num_grad(lambda a: op(a, dim=0), T(xs, torch.float64))
            d = float((x.grad - ref).abs().max())
            rec(f"grad_fd_interior:{name}", d <= 1e-4, f"autograd vs finite difference differ by {d:.3g}", xs=xs)
        for xs in ([0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.0, 1.0, 0.5], [1e-9, 1 - 1e-9, 0.5], [0.0], [1.0]):
            x = T(xs, torch.float64).requires_grad_(True)
            op(x, dim=0).backward()
            rec(f"grad_finite_boundary:{name}", bool(torch.isfinite(x.grad).all()), f"xs={xs}: grad={x.grad.tolist()}", xs=xs)


# ====================================================================== special values: dtype, thresholds
def special_props(rng, n):
    tab = O.connective_table()
    for name, (cname, kw, oracle, arity) in tab.items():
        op = make_op(cname, kw)
        for _ in range(n):
            xs, ys = vals(rng, 32, 0.8), vals(rng, 32, 0.8)
            a32 = op(*(([T(xs)] if arity == 1 else [T(xs), T(ys)])))
            a64 = op(*(([T(xs, torch.float64)] if arity == 1 else [T(xs, torch.float64), T(ys, torch.float64)])))
            d = float((a32.double() - a64).abs().max())
            rec(f"special_float32_vs_float64:{name}", d <= 1e-5, f"float32 and float64 results differ by {d:.3g}")
            rec(f"special_output_dtype:{name}", a32.dtype == torch.float32 and a64.dtype == torch.float64,
                f"output dtypes {a32.dtype}/{a64.dtype} for float32/float64 inputs")
        # integer and bool inputs (truth values given as 0/1 tensors)
        for dt in (torch.int64, torch.bool, torch.float16, torch.bfloat16):
            try:
                xi = torch.tensor([0, 1, 0, 1]).to(dt); yi = torch.tensor([0, 0, 1, 1]).to(dt)
                out = op(xi) if arity == 1 else op(xi, yi)
                want = oracle(xi.double().numpy()) if arity == 1 else oracle(xi.double().numpy(), yi.double().numpy())
                d = float(np.max(np.abs(out.double().numpy() - np.asarray(want))))
                rec(f"special_dtype_{str(dt)[6:]}:{name}", d <= 1e-2, f"result differs from float64 by {d:.3g} (out dtype {out.dtype})")
            except BaseException as e:
                rec(f"special_dtype_{str(dt)[6:]}:{name}", False, f"{type(e).__name__}: {str(e)[:120]}")


# ====================================================================== invalid / odd inputs through the public API
def input_props():
    C = ltn.Connective(F.AndMin())
    ok_obj = ltn.Constant(T([0.5]))
    for bad, label in ((-0.1, "negative"), (1.1, "above one"), (float("nan"), "NaN"), (float("inf"), "inf")):
        try:
            C(ok_obj, ltn.Constant(T([bad])))
            rec("input_invalid_truth_value_rejected", False, f"{label} truth value accepted by Connective")
        except ValueError:
            rec("input_invalid_truth_value_rejected", True)
        except BaseException as e:
            rec("input_invalid_truth_value_rejected", False, f"{label}: unexpected {type(e).__name__}: {str(e)[:100]}")
    # quantifier with an empty variable list
    x = ltn.Variable("x", torch.rand(4, 1))
    y = ltn.Variable("y", torch.rand(3, 1))
    P = ltn.Predicate(func=lambda a, b: torch.sigmoid(a.sum(-1) + b.sum(-1)))
    Forall = ltn.Quantifier(F.AggregPMeanError(p=2), quantifier="f")
    try:
        r = Forall([], P(x, y))
        rec("input_quantifier_empty_vars", False, f"Forall([]) accepted and returned value of shape {tuple(r.value.shape)} with free vars {r.free_vars}")
    except BaseException as e:
        rec("input_quantifier_empty_vars", True, f"{type(e).__name__}")
    # quantify a variable that does not occur in the formula
    z = ltn.Variable("z", torch.rand(5, 1))
    try:
        r = Forall(z, P(x, y))
        rec("input_quantifier_unused_variable", False, f"Forall over a variable not in the formula accepted; result shape {tuple(r.value.shape)} free vars {r.free_vars}")
    except BaseException as e:
        rec("input_quantifier_unused_variable", True, f"{type(e).__name__}: {str(e)[:100]}")
    # diag with different sizes, diag side effect after an exception
    try:
        ltn.diag(x, y)
        rec("input_diag_size_mismatch", False, "diag accepted variables with 4 and 3 individuals")
    except ValueError:
        rec("input_diag_size_mismatch", True)
    # variable labels
    try:
        ltn.Variable("x y", torch.rand(2, 1))
        rec("input_variable_label_with_space", True)
    except BaseException as e:
        rec("input_variable_label_with_space", True)
    # SatAgg on non-scalar, on empty
    for xs, label in ((torch.tensor([]), "empty tensor"), (torch.tensor([0.5, 0.5]), "vector")):
        try:
            v = ltn.fuzzy_ops.SatAgg()(xs)
            rec("input_sataggregation_bad_shape", False, f"SatAgg accepted a {label}: {v}")
        except BaseException as e:
            rec("input_sataggregation_bad_shape", True, f"{type(e).__name__}")
    try:
        v = ltn.fuzzy_ops.SatAgg()()
        rec("input_sataggregation_no_formulas", False, f"SatAgg() with no formula returned {v}")
    except BaseException as e:
        rec("input_sataggregation_no_formulas", True, f"{type(e).__name__}")


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--groups", default="conn,laws,equiv,agg,grad,special,input,quant")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    torch.manual_seed(a.seed)
    groups = set(a.groups.split(","))
    if "conn" in groups: guarded("conn", lambda: conn_props(rng, a.n))
    if "laws" in groups: guarded("laws", lambda: conn_laws(rng, a.n))
    if "equiv" in groups: guarded("equiv", lambda: equiv_props(rng, a.n))
    if "agg" in groups: guarded("agg", lambda: agg_props(rng, a.n))
    if "grad" in groups: guarded("grad", lambda: grad_props(rng, max(5, a.n // 4)))
    if "special" in groups: guarded("special", lambda: special_props(rng, max(5, a.n // 4)))
    if "input" in groups: guarded("input", input_props)
    if "quant" in groups:
        import ltn_quant
        guarded("quant", lambda: ltn_quant.run(rng, a.n, rec))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        for r in FINDINGS:
            f.write(json.dumps(r, default=str) + "\n")
        f.write(json.dumps({"summary": {k: {"ok": v[0], "fail": v[1]} for k, v in sorted(COUNTS.items())}, "seed": a.seed, "n": a.n}) + "\n")
    bad = {k: v for k, v in sorted(COUNTS.items()) if v[1]}
    total = sum(v[0] + v[1] for v in COUNTS.values())
    print(f"{total} checks, {len(COUNTS)} properties, {len(bad)} with at least one failure")
    for k, v in bad.items():
        print(f"  {k:60s} fail {v[1]:5d} / {v[0] + v[1]:5d}")
    print("results ->", a.out)


if __name__ == "__main__":
    main()
