"""Property-based fuzzing of DeepProbLog against the possible-worlds oracle.

Properties (each reported separately):
  dpl_exact_value    ExactEngine value == exact enumeration
  dpl_exact_grad     ExactEngine gradient (via SGD param grads) == exact multilinear derivative
  dpl_approx_value   ApproximateEngine, large k, value == exact
  dpl_approx_grad    ApproximateEngine, large k, gradient == exact
  dpl_engines_agree  ExactEngine vs ApproximateEngine (large k) agree
  dpl_lowk_bound     monotone program, ApproximateEngine small k: value <= exact (HYPOTHESIS)
  dpl_grad_sign      monotone program: every gradient >= 0
"""
import warnings
warnings.filterwarnings("ignore")
import torch
from problog.logic import Term, Constant
from nesy_prog import Prog, exact_probs, exact_grads

K_BIG = 200
MISSING = []   # filled by values_and_grads; reported once per program
TOL_V = 1e-5      # float32 tensors inside DeepProbLog
TOL_G = 1e-4


def program_text(prog: Prog, learnable: bool) -> str:
    lines = []
    in_group = prog.grouped()
    for i, (r, t, p) in enumerate(prog.facts):
        if i not in in_group:
            pre = f"t({p!r})" if learnable else f"{p!r}"
            lines.append(f"{pre}::{r}({','.join(map(str, t))}).")
    for g in prog.groups:
        alts = [f"{prog.facts[i][2]!r}::{prog.facts[i][0]}({','.join(map(str, prog.facts[i][1]))})" for i in g]
        lines.append("; ".join(alts) + ".")
    for r in prog.rules:
        body = [f"{a.rel}({','.join(v.upper() for v in a.vars)})" for a in r.pos]
        body += [f"\\+{a.rel}({','.join(v.upper() for v in a.vars)})" for a in r.neg]
        lines.append(f"{r.head.rel}({','.join(v.upper() for v in r.head.vars)}) :- {', '.join(body)}.")
    # Prolog rejects calls to undefined predicates; declare the empty ones explicitly
    defined = {f[0] for f in prog.facts} | {r.head.rel for r in prog.rules}
    for rel, ar in {**prog.edb, **prog.idb}.items():
        if rel not in defined:
            lines.append(f"{rel}({','.join(f'X{j}' for j in range(ar))}) :- fail.")
    return "\n".join(lines) + "\n"


def make_model(prog, engine, learnable, k=None):
    from deepproblog.engines import ExactEngine, ApproximateEngine
    from deepproblog.model import Model
    from deepproblog.optimizer import SGD
    m = Model(program_text(prog, learnable), [], load=False)
    if engine == "exact":
        m.set_engine(ExactEngine(m))
    else:
        m.set_engine(ApproximateEngine(m, k, ApproximateEngine.geometric_mean))
    if learnable:
        m.optimizer = SGD(m, 1.0)
    return m


def term_of(rel, t):
    return Term(rel, *[Constant(c) for c in t])


def values_and_grads(prog, engine, k=None, want_grads=True):
    from deepproblog.query import Query
    learnable = want_grads
    m = make_model(prog, engine, learnable, k)
    vals, grads = {}, {}
    for rel in prog.idb:
        vals[rel] = {}
        for t in prog.possible_tuples(rel):
            q = term_of(rel, t)
            if learnable:
                m.optimizer.zero_grad()
            res = m.solve([Query(q)])[0].result
            if q not in res:                      # ApproximateEngine omits underivable queries
                MISSING.append(f"{engine}: {rel}{t} absent from result dict")
                vals[rel][t] = 0.0
                if learnable:
                    grads[(rel, t)] = {fi: 0.0 for fi in range(len(prog.facts))}
                continue
            p = res[q]
            vals[rel][t] = float(p)
            if learnable:
                if isinstance(p, torch.Tensor) and p.requires_grad:
                    p.backward()
                g = {}
                for fi in range(len(prog.facts)):
                    g[fi] = float(m.optimizer._params_grad.get(fi, 0.0))
                grads[(rel, t)] = g
    return vals, grads


def compare(prog, want, got, tol, label):
    bad = []
    for rel in prog.idb:
        for t, w in want[rel].items():
            g = got.get(rel, {}).get(t, 0.0)
            if abs(w - g) > tol + 1e-5 * abs(w):
                bad.append(f"{label}: {rel}{t} exact={w:.9g} framework={g:.9g}")
    return bad


def compare_grads(prog, eg, grads, label):
    bad = []
    for fi, per_rel in eg.items():
        for rel, per_t in per_rel.items():
            for t, w in per_t.items():
                g = grads.get((rel, t), {}).get(fi, 0.0)
                if abs(w - g) > TOL_G + 1e-3 * abs(w):
                    bad.append(f"{label}: d {rel}{t} / d fact#{fi}={prog.facts[fi][:2]} exact={w:.6g} framework={g:.6g}")
    return bad


def check_prog(prog: Prog, mode: str):
    findings = []

    def guard(name, fn):
        try:
            for d in fn() or []:
                findings.append((name, d))
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            findings.append((f"{name}:exception:{type(e).__name__}", f"{type(e).__name__}: {str(e)[:300]}"))

    want = exact_probs(prog)
    indep = (mode == "indep")
    cyclic = prog.is_cyclic()      # SLD-style proof search is not expected to terminate on cycles
    del MISSING[:]
    st = {}

    def exact():
        v, g = values_and_grads(prog, "exact", want_grads=indep)
        st["ev"], st["eg"] = v, g
        return compare(prog, want, v, TOL_V, "ExactEngine value")
    guard("dpl_exact_value", exact)

    if indep:
        egr = exact_grads(prog)

        def exact_grad():
            return compare_grads(prog, egr, st.get("eg", {}), "ExactEngine grad") if st.get("eg") else []
        guard("dpl_exact_grad", exact_grad)

    def approx():
        if cyclic:
            return []
        v, g = values_and_grads(prog, "approx", K_BIG, want_grads=indep)
        st["av"], st["ag"] = v, g
        return compare(prog, want, v, TOL_V, f"ApproximateEngine(k={K_BIG}) value")
    guard("dpl_approx_value", approx)

    if indep:
        guard("dpl_approx_grad", lambda: compare_grads(prog, egr, st.get("ag", {}), f"ApproximateEngine(k={K_BIG}) grad") if st.get("ag") else [])

    def agree():
        if "ev" not in st or "av" not in st:
            return []
        bad = []
        for rel in prog.idb:
            for t in st["ev"][rel]:
                if abs(st["ev"][rel][t] - st["av"][rel][t]) > TOL_V:
                    bad.append(f"engines disagree: {rel}{t} exact-engine={st['ev'][rel][t]:.9g} approx-engine={st['av'][rel][t]:.9g}")
        return bad
    guard("dpl_engines_agree", agree)

    if MISSING:
        findings.append(("dpl_approx_missing_result", MISSING[0] + f"  (+{len(MISSING) - 1} more); ExactEngine returns 0.0 for these"))

    if indep and prog.monotone() and not cyclic:
        def lowk():
            bad = []
            for k in (1, 3):
                v, _ = values_and_grads(prog, "approx", k, want_grads=False)
                for rel in prog.idb:
                    for t, x in v[rel].items():
                        if x > want[rel][t] + 1e-5:
                            bad.append(f"lowk_bound(k={k}): {rel}{t} value {x:.6g} > exact {want[rel][t]:.6g}")
            return bad
        guard("dpl_lowk_bound", lowk)

        def sign():
            bad = []
            for key in ("eg", "ag"):
                for (rel, t), g in st.get(key, {}).items():
                    for fi, x in g.items():
                        if x < -1e-6:
                            bad.append(f"grad_sign[{key}]: d {rel}{t} / d fact#{fi} = {x:.6g} < 0 in a negation-free program")
            return bad
        guard("dpl_grad_sign", sign)
    return findings
