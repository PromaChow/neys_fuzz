"""Property-based fuzzing of Scallop (scallopy) against the possible-worlds oracle.

Properties checked per random program (each reported separately):
  exact_topk       topkproofs, large k   == exact enumeration
  exact_wmcdisj    same, wmc_with_disjunctions=True, programs with a disjunction group
  diff_value       difftopkproofs, large k, forward value == exact
  diff_grad        autograd gradient of the forward value == exact multilinear derivative
  grad_sign        monotone (negation-free) program => every gradient >= 0
  lowk_bound       monotone program, small k => value <= exact   (HYPOTHESIS, not a spec)
  permute          shuffling fact/rule order does not change topkproofs output
Outcome categories: ok / mismatch / exception / timeout.
"""
import argparse
import json
import os
import random
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutTimeout
import multiprocessing as mp

from nesy_prog import Prog, Rule, Atom, exact_probs, exact_grads, gen_prog, shrink

K_BIG = 300
TOL_F64 = 1e-9
TOL_F32 = 1e-4


# ---------------------------------------------------------------- Scallop glue
def scl_rule(r: Rule) -> str:
    body = [f"{a.rel}({','.join(a.vars)})" for a in r.pos]
    body += [f"not {a.rel}({','.join(a.vars)})" for a in r.neg]
    return f"{r.head.rel}({','.join(r.head.vars)}) = {', '.join(body)}"


def build_ctx(prog: Prog, provenance: str, k: int, wmc_disj=False, order=None):
    import scallopy
    ctx = scallopy.ScallopContext(provenance=provenance, k=k, wmc_with_disjunctions=wmc_disj)
    fact_order = order["facts"] if order else list(range(len(prog.facts)))
    rule_order = order["rules"] if order else list(range(len(prog.rules)))
    for rel, ar in prog.edb.items():
        ctx.add_relation(rel, tuple([int] * ar))
    by_rel = {}
    for i in fact_order:
        by_rel.setdefault(prog.facts[i][0], []).append(i)
    pos_in_rel = {}
    for rel, idxs in by_rel.items():
        for j, i in enumerate(idxs):
            pos_in_rel[i] = (rel, j)
    for rel, idxs in by_rel.items():
        elems = [(prog.facts[i][2], prog.facts[i][1]) for i in idxs]
        disj = None
        if prog.groups:
            disj = [[pos_in_rel[i][1] for i in g] for g in prog.groups if prog.facts[g[0]][0] == rel]
            disj = disj or None
        ctx.add_facts(rel, elems, disjunctions=disj)
    for ri in rule_order:
        ctx.add_rule(scl_rule(prog.rules[ri]))
    return ctx


def scallop_probs(prog, provenance="topkproofs", k=K_BIG, wmc_disj=False, order=None):
    ctx = build_ctx(prog, provenance, k, wmc_disj, order)
    ctx.run()
    out = {}
    for rel in prog.idb:
        try:
            out[rel] = {tuple(t): float(p) for (p, t) in ctx.relation(rel)}
        except Exception:
            out[rel] = {}
    return out


def scallop_diff(prog, k=K_BIG):
    """Return (values, grads): values[rel][tuple], grads[fact_idx][rel][tuple]."""
    import scallopy, torch
    ctx = scallopy.ScallopContext(provenance="difftopkproofs", k=k)
    idx_by_rel = {rel: [i for i, f in enumerate(prog.facts) if f[0] == rel] for rel in prog.edb}
    for rel, ar in prog.edb.items():
        types = tuple([int] * ar)
        mapping = [prog.facts[i][1] for i in idx_by_rel[rel]]
        if mapping:
            ctx.add_relation(rel, types, input_mapping=mapping)
        else:
            ctx.add_relation(rel, types)
    for r in prog.rules:
        ctx.add_rule(scl_rule(r))
    inputs = {}
    for rel, idxs in idx_by_rel.items():
        if idxs:
            inputs[rel] = torch.tensor([[prog.facts[i][2] for i in idxs]], dtype=torch.float32, requires_grad=True)
    values, grads = {}, {i: {} for i in range(len(prog.facts))}
    for rel in prog.idb:
        tuples = prog.possible_tuples(rel)
        fwd = ctx.forward_function(rel, output_mapping=tuples)
        res = fwd(**inputs)
        values[rel] = {t: float(res[0, j]) for j, t in enumerate(tuples)}
        for j, t in enumerate(tuples):
            gs = torch.autograd.grad(res[0, j], list(inputs.values()), retain_graph=True, allow_unused=True)
            for (irel, _), g in zip(inputs.items(), gs):
                for pos, fi in enumerate(idx_by_rel[irel]):
                    gv = 0.0 if g is None else float(g[0, pos])
                    grads[fi].setdefault(rel, {})[t] = gv
    return values, grads


# ---------------------------------------------------------------- comparisons
def compare(prog, want, got, tol, label):
    bad = []
    for rel in prog.idb:
        for t, w in want[rel].items():
            g = got.get(rel, {}).get(t, 0.0)
            if abs(w - g) > tol:
                bad.append(f"{label}: {rel}{t} exact={w:.9g} framework={g:.9g}")
    return bad


def check_prog(prog: Prog, mode: str):
    """Run all properties valid for this program; return list of (property, detail)."""
    findings = []

    def guard(name, fn):
        try:
            for d in fn() or []:
                findings.append((name, d))
        except BaseException as e:  # pyo3 panics derive from BaseException
            if isinstance(e, KeyboardInterrupt):
                raise
            findings.append((name + ":exception", f"{type(e).__name__}: {str(e)[:300]}"))

    want = exact_probs(prog)

    guard("exact_topk", lambda: compare(prog, want, scallop_probs(prog), TOL_F64, "topkproofs"))
    if prog.groups:
        guard("exact_wmcdisj", lambda: compare(
            prog, want, scallop_probs(prog, wmc_disj=True), TOL_F64, "topkproofs+wmc_with_disjunctions"))

    def permute():
        rng = random.Random(len(prog.facts) * 31 + len(prog.rules))
        fo, ro = list(range(len(prog.facts))), list(range(len(prog.rules)))
        rng.shuffle(fo); rng.shuffle(ro)
        a = scallop_probs(prog)
        b = scallop_probs(prog, order={"facts": fo, "rules": ro})
        bad = []
        for rel in prog.idb:
            for t in set(a[rel]) | set(b[rel]):
                if abs(a[rel].get(t, 0.0) - b[rel].get(t, 0.0)) > TOL_F64:
                    bad.append(f"permute: {rel}{t} {a[rel].get(t, 0.0)!r} vs {b[rel].get(t, 0.0)!r}")
        return bad
    guard("permute", permute)

    if mode == "indep":
        eg = exact_grads(prog)
        state = {}

        def diff():
            vals, grads = scallop_diff(prog)
            state["v"], state["g"] = vals, grads
            bad = compare(prog, want, vals, TOL_F32, "difftopkproofs value")
            return bad
        guard("diff_value", diff)

        def grad():
            if "g" not in state:
                return []
            bad = []
            for fi, per_rel in eg.items():
                for rel, per_t in per_rel.items():
                    for t, w in per_t.items():
                        g = state["g"].get(fi, {}).get(rel, {}).get(t, 0.0)
                        if abs(w - g) > TOL_F32 + 1e-3 * abs(w):
                            bad.append(f"diff_grad: d {rel}{t} / d fact#{fi}={prog.facts[fi][:2]} exact={w:.6g} framework={g:.6g}")
            return bad
        guard("diff_grad", grad)

        if prog.monotone():
            def sign():
                if "g" not in state:
                    return []
                bad = []
                for fi, per_rel in state["g"].items():
                    for rel, per_t in per_rel.items():
                        for t, g in per_t.items():
                            if g < -1e-6:
                                bad.append(f"grad_sign: d {rel}{t} / d fact#{fi} = {g:.6g} < 0 in a negation-free program")
                return bad
            guard("grad_sign", sign)

            def lowk():
                bad = []
                for k in (1, 3):
                    vals, _ = scallop_diff(prog, k=k)
                    for rel in prog.idb:
                        for t, v in vals[rel].items():
                            if v > want[rel][t] + 1e-5:
                                bad.append(f"lowk_bound(k={k}): {rel}{t} value {v:.6g} > exact {want[rel][t]:.6g}")
                return bad
            guard("lowk_bound", lowk)
    return findings


# ---------------------------------------------------------------- worker side
def _check(prog, mode):
    import importlib
    return importlib.import_module(os.environ.get("FUZZ_TARGET", "scallop_fuzz")).check_prog(prog, mode)


def worker_case(args):
    prog, mode, do_shrink = args
    t0 = time.time()
    findings = _check(prog, mode)
    out = []
    for name, detail in findings:
        entry = {"property": name, "detail": detail, "program": prog.to_text()}
        if do_shrink and not name.endswith(":exception") or (do_shrink and name.endswith(":exception")):
            base = name

            def still(p, base=base):
                try:
                    return any(f[0] == base for f in _check(p, mode))
                except BaseException:
                    return False
            small = shrink(prog, still)
            entry["minimized"] = small.to_text()
            entry["minimized_detail"] = [d for (n, d) in _check(small, mode) if n == base][:3]
        out.append(entry)
    return out, time.time() - t0


# ---------------------------------------------------------------- driver
def make_pool():
    return ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", choices=["indep", "group"], default="indep")
    ap.add_argument("--neg", action="store_true")
    ap.add_argument("--boundary", type=float, default=0.3)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-shrink", action="store_true")
    ap.add_argument("--target", default="scallop_fuzz")
    a = ap.parse_args()
    os.environ["FUZZ_TARGET"] = a.target

    rng = random.Random(a.seed)
    out_path = a.out or f"../results/{a.target.split('_')[0]}_{a.mode}{'_neg' if a.neg else ''}_s{a.seed}.jsonl"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pool = make_pool()
    counts, timeouts, programs_with_finding = {}, 0, 0
    t_start = time.time()
    with open(out_path, "w") as f:
        for i in range(a.n):
            prog = gen_prog(rng, allow_neg=a.neg, allow_groups=(a.mode == "group"),
                            boundary_rate=a.boundary)
            fut = pool.submit(worker_case, (prog, a.mode, not a.no_shrink))
            try:
                entries, dt = fut.result(timeout=a.timeout)
            except FutTimeout:
                timeouts += 1
                entries = [{"property": "timeout", "detail": f">{a.timeout}s", "program": prog.to_text()}]
                for p in list(pool._processes.values()):
                    p.terminate()
                pool.shutdown(wait=False, cancel_futures=True)
                pool = make_pool()
            except Exception as e:
                entries = [{"property": "harness_crash", "detail": f"{type(e).__name__}: {e}", "program": prog.to_text()}]
                pool = make_pool()
            if entries:
                programs_with_finding += 1
            for e in entries:
                e.update({"case": i, "seed": a.seed, "mode": a.mode, "neg": a.neg})
                counts[e["property"]] = counts.get(e["property"], 0) + 1
                f.write(json.dumps(e) + "\n")
            f.flush()
            if (i + 1) % 25 == 0:
                print(f"[{i + 1}/{a.n}] findings so far: {counts}  ({time.time() - t_start:.0f}s)", flush=True)
    pool.shutdown(wait=False, cancel_futures=True)
    print(f"DONE {a.n} programs, {programs_with_finding} with at least one finding, {time.time() - t_start:.0f}s")
    print("counts by property:", json.dumps(counts, indent=1))
    print("results ->", out_path)


if __name__ == "__main__":
    main()
