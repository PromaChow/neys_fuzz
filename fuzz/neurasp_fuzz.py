"""Property-based fuzzing of NeurASP's MVPP engine against the possible-worlds oracle.

Each independent fact i becomes a two-valued MVPP variable   p f<i>(0,1) ; 1-p f<i>(0,0).
Each disjunction group becomes one multi-valued variable (plus an explicit 'none' value).
Observation for a query atom is the ASP constraint   :- not r(c...).
so inference_obs_exact(obs) = P(atom), and the learning gradient is d log P(atom) / d p.

Properties:
  nasp_exact_value   learnable (@) probabilities, oracle uses NeurASP's documented clamp to [eps,1-eps]
  nasp_fixed_value   non-learnable probabilities, no clamp
  nasp_grad          gradients_one_obs (the path used by training) == d log P / d p
  nasp_gradient_fn   MVPP.gradient(rule, atom, obs) (no callers in the repo) == d log P / d p
  nasp_inference_obs_exact_api   the public MVPP.inference_obs_exact() == exact
"""
import os
import sys
import warnings
import dataclasses

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frameworks", "NeurASP"))
import torch
from nesy_prog import Prog, exact_probs, exact_grads

EPS = 1e-6
TOL = 1e-5


def clamp(p):
    # MVPP.normalize_probs only rewrites probabilities that are <= 0 or >= 1
    if p >= 1.0:
        return 1.0 - EPS
    if p <= 0.0:
        return EPS
    return p


def args(t):
    return ",".join(map(str, t))


def mvpp_text(prog: Prog, learnable: bool):
    """Return (program text, index of MVPP rule for each independent fact)."""
    at = "@" if learnable else ""
    lines, rule_of = [], {}
    in_group = prog.grouped()
    L = max([2] + [len(g) + 1 for g in prog.groups])     # common number of values per variable
    n = 0
    for i, (rel, t, p) in enumerate(prog.facts):
        if i in in_group:
            continue
        q = repr(1.0 - p)
        alts = [f"{at}{p!r} f(0,{i},1)", f"{at}{q} f(0,{i},0)"]
        alts += [f"0.0 f(0,{i},{v})" for v in range(2, L)]      # padding values with probability 0
        lines.append(" ; ".join(alts) + ".")
        rule_of[i] = n
        n += 1
    for gi, g in enumerate(prog.groups):
        total = sum(prog.facts[i][2] for i in g)
        alts = [f"{at}{prog.facts[i][2]!r} g(0,{gi},{j + 1})" for j, i in enumerate(g)]
        alts.append(f"{at}{max(1.0 - total, 0.0)!r} g(0,{gi},0)")
        alts += [f"0.0 g(0,{gi},{v})" for v in range(len(g) + 1, L)]
        lines.append(" ; ".join(alts) + ".")
        n += 1
    for i, (rel, t, p) in enumerate(prog.facts):
        if i in in_group:
            gi = next(k for k, g in enumerate(prog.groups) if i in g)
            j = prog.groups[gi].index(i) + 1
            lines.append(f"{rel}({args(t)}) :- g(0,{gi},{j}).")
        else:
            lines.append(f"{rel}({args(t)}) :- f(0,{i},1).")
    for r in prog.rules:
        body = [f"{a.rel}({','.join(v.upper() for v in a.vars)})" for a in r.pos]
        body += [f"not {a.rel}({','.join(v.upper() for v in a.vars)})" for a in r.neg]
        lines.append(f"{r.head.rel}({','.join(v.upper() for v in r.head.vars)}) :- {', '.join(body)}.")
    return "\n".join(lines) + "\n", rule_of


def obs_for(rel, t):
    return f":- not {rel}({args(t)}).\n"


def build(prog, learnable):
    from mvpp import MVPP
    text, rule_of = mvpp_text(prog, learnable)
    m = MVPP(text)
    # exactly what NeurASP.learn does before using the MVPP: tensor parameters + normalize_probs
    m.parameters = [torch.Tensor(pr) for pr in m.parameters]
    m.normalize_probs()
    return m, rule_of


def prob_of_obs(m, obs):
    models = m.find_k_SM_under_obs(obs, k=0)         # all stable models, as indices of values
    if len(models) == 0:
        return 0.0
    return float(m.prob_of_interpretation(models).sum())


def inference(prog, learnable):
    m, rule_of = build(prog, learnable)
    vals = {}
    for rel in prog.idb:
        vals[rel] = {t: prob_of_obs(m, obs_for(rel, t)) for t in prog.possible_tuples(rel)}
    return m, rule_of, vals


def clamped(prog: Prog) -> Prog:
    facts = [(r, t, clamp(p)) for (r, t, p) in prog.facts]
    return dataclasses.replace(prog, facts=facts)


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

    st = {}
    indep = mode == "indep"

    def exact_learnable():
        cp = clamped(prog) if indep else prog      # clamp applies to '@' probabilities of every rule
        want = exact_probs(cp)
        m, rule_of, vals = inference(prog, True)
        st.update(m=m, rule_of=rule_of, cp=cp, want=want)
        return [f"NeurASP value: {rel}{t} exact={want[rel][t]:.9g} framework={vals[rel][t]:.9g}"
                for rel in prog.idb for t in want[rel] if abs(want[rel][t] - vals[rel][t]) > TOL]
    guard("nasp_exact_value", exact_learnable)

    def fixed():
        want = exact_probs(prog)
        _, _, vals = inference(prog, False)
        return [f"NeurASP value (non-learnable): {rel}{t} exact={want[rel][t]:.9g} framework={vals[rel][t]:.9g}"
                for rel in prog.idb for t in want[rel] if abs(want[rel][t] - vals[rel][t]) > TOL]
    guard("nasp_fixed_value", fixed)

    def api_exact():
        m, _ = build(prog, False)
        rel = next(iter(prog.idb))
        t = prog.possible_tuples(rel)[0]
        got = float(m.inference_obs_exact(obs_for(rel, t)))
        want = exact_probs(prog)[rel][t]
        return [] if abs(got - want) <= TOL else [f"MVPP.inference_obs_exact({rel}{t}) exact={want:.9g} framework={got:.9g}"]
    guard("nasp_inference_obs_exact_api", api_exact)

    if indep and "m" in st:
        eg = exact_grads(st["cp"])
        want = st["want"]

        def expected(fi, rel, t):   # d log P(atom) / d p_i
            P = want[rel][t]
            return None if P <= 1e-12 else eg[fi][rel][t] / P

        def grad():
            bad = []
            for rel in prog.idb:
                for t in prog.possible_tuples(rel):
                    if want[rel][t] <= 1e-12:
                        continue
                    g = st["m"].gradients_one_obs(obs_for(rel, t))
                    for fi, ri in st["rule_of"].items():
                        e, got = expected(fi, rel, t), float(g[ri][0])
                        if abs(e - got) > 1e-4 + 1e-4 * abs(e):
                            bad.append(f"NeurASP gradients_one_obs: d log P({rel}{t}) / d fact#{fi}={prog.facts[fi][:2]} exact={e:.6g} framework={got:.6g}")
            return bad
        guard("nasp_grad", grad)

        def grad_fn():
            bad = []
            for rel in prog.idb:
                for t in prog.possible_tuples(rel):
                    if want[rel][t] <= 1e-12:
                        continue
                    for fi, ri in st["rule_of"].items():
                        e = expected(fi, rel, t)
                        got = st["m"].gradient(ri, 0, obs_for(rel, t))
                        if abs(e - got) > 1e-4 + 1e-4 * abs(e):
                            bad.append(f"NeurASP MVPP.gradient(): d log P({rel}{t}) / d fact#{fi} exact={e:.6g} framework={got:.6g}")
            return bad
        guard("nasp_gradient_fn", grad_fn)
    return findings
