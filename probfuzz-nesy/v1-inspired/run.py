"""ProbFuzz-NeSy driver: complete template holes -> translate to every system -> compare with the exact oracle.

  python run.py --n 100 --special 0.0     # baseline: ordinary values only (what ProbFuzz's generator produced)
  python run.py --n 100 --special 0.4     # special values enabled (0, 1, epsilon, float32 limits, saturated networks)
Every finding is shrunk and written to results/*.jsonl.
"""
import argparse
import glob
import json
import multiprocessing as mp
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutTimeout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import il  # noqa: E402
import backends  # noqa: E402
from nesy_prog import exact_probs, shrink  # noqa: E402


def smape(a, b):
    d = abs(a) + abs(b)
    return 0.0 if d == 0 else 2 * abs(a - b) / d


def _task(args):
    kind, system, obj = args
    try:
        r = backends.run_symbolic(system, obj) if kind == "sym" else backends.run_neural(system, obj)
        return {"ok": True, "result": r}
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"ok": False, "error": type(e).__name__, "message": str(e)[:200]}


def _pool():
    return ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"))


def compare(system, want, got, tol):
    """List of (key, oracle, system value) beyond tolerance, and the max SMAPE."""
    bad, worst = [], 0.0
    for key, w in want.items():
        g = got.get(key, 0.0)
        worst = max(worst, smape(w, g))
        if abs(w - g) > tol + 1e-5 * abs(w):
            bad.append((key, w, g))
    return bad, worst


def flatten(res):
    return {(rel, t): v for rel, d in res.items() for t, v in d.items()}


def known_tag(system, case, bad):
    """Label deviations that earlier rounds already triaged (REPORT.md), so new behaviour stands out."""
    if system == "problog" and any(0 < w <= 1e-9 for _, w, _ in bad):
        return "known:problog-tiny-probability-limit"
    if system == "scallop_nn":
        return "known:F22-family-forward_function-categorical"
    if system.startswith("scallop") and getattr(case, "groups", None):
        return "known:F3-scallop-disjunction"
    if system == "dpl_approx_nn" and any(0.0 in row for row in getattr(case, "probs", [])):
        return "known:F15-dpl-approx-zero-prob-network-output"
    if system == "dpl_approx" and any(p[2] == 0.0 for p in getattr(case, "facts", [])):
        return "known:F4-dpl-approx-zero-prob"
    return "new"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="programs per template")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--special", type=float, default=0.4, help="rate of special values for holes (0 = baseline)")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--templates", default="*")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = a.out or os.path.join(HERE, "results", f"run_special{a.special}_s{a.seed}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    pools = {s: _pool() for s in backends.SYMBOLIC + backends.NEURAL}
    tally = {}
    t0 = time.time()

    def call(system, kind, obj):
        fut = pools[system].submit(_task, (kind, system, obj))
        try:
            return fut.result(timeout=a.timeout)
        except FutTimeout:
            for p in list(pools[system]._processes.values()):
                p.terminate()
            pools[system].shutdown(wait=False, cancel_futures=True)
            pools[system] = _pool()
            return {"ok": False, "error": "Timeout", "message": f">{a.timeout}s"}

    with open(out, "w") as f:
        for path in sorted(glob.glob(os.path.join(HERE, "templates", a.templates + ".tmpl"))):
            tmpl = il.load(path)
            name = tmpl["name"]
            for i in range(a.n):
                case = il.fill(tmpl, rng, a.special)
                neural = tmpl["neural"] is not None
                systems = backends.NEURAL if neural else backends.SYMBOLIC
                want = backends.oracle_neural(case) if neural else flatten(exact_probs(case))
                kind = "nn" if neural else "sym"
                # fire all systems, then collect (each has its own worker process)
                futs = {s: pools[s].submit(_task, (kind, s, case)) for s in systems}
                results = {}
                for s, fut in futs.items():
                    try:
                        results[s] = fut.result(timeout=a.timeout)
                    except FutTimeout:
                        for p in list(pools[s]._processes.values()):
                            p.terminate()
                        pools[s].shutdown(wait=False, cancel_futures=True)
                        pools[s] = _pool()
                        results[s] = {"ok": False, "error": "Timeout", "message": f">{a.timeout}s"}
                    except Exception as e:
                        pools[s] = _pool()
                        results[s] = {"ok": False, "error": "WorkerDied", "message": str(e)[:100]}
                vals = {}
                for s, r in results.items():
                    row = {"template": name, "case": i, "system": s, "program": case.to_text()}
                    if not r["ok"]:
                        neg = any(rl.neg for rl in getattr(case, "rules", []))
                        tag = ("candidate:dpl-approx-negation-unsupported" if s == "dpl_approx" and neg and r["error"] == "PrologError"
                               else "new")
                        row.update(outcome="crash" if r["error"] != "Timeout" else "timeout", error=r["error"], message=r["message"],
                                   tag=tag)
                    elif r["result"] is None:
                        continue                                  # system not applicable to this program
                    else:
                        got = r["result"] if neural else flatten(r["result"])
                        vals[s] = got
                        bad, worst = compare(s, want, got, backends.TOL[s])
                        row.update(outcome="mismatch" if bad else "ok", max_smape=worst)
                        if bad:
                            row.update(tag=known_tag(s, case, bad), n_bad=len(bad),
                                       example={"key": str(bad[0][0]), "oracle": bad[0][1], "system": bad[0][2]})
                            if not neural and row["tag"] == "new":
                                row["shrunk"] = shrink_case(s, case, a.timeout)
                    tally[(name, s, row["outcome"], row.get("tag", ""))] = tally.get((name, s, row["outcome"], row.get("tag", "")), 0) + 1
                    if row["outcome"] != "ok":
                        f.write(json.dumps(row, default=str) + "\n")
                        f.flush()
                # pairwise disagreement between systems that both ran
                names = sorted(vals)
                for x in range(len(names)):
                    for y in range(x + 1, len(names)):
                        s1, s2 = names[x], names[y]
                        tol = backends.TOL[s1] + backends.TOL[s2]
                        d = max((abs(vals[s1].get(k, 0.0) - vals[s2].get(k, 0.0)) for k in want), default=0.0)
                        if d > tol + 1e-5:
                            tally[(name, f"{s1}~{s2}", "disagree", "")] = tally.get((name, f"{s1}~{s2}", "disagree", ""), 0) + 1
            print(f"[{name}] done  ({time.time() - t0:.0f}s)", flush=True)
    for p in pools.values():
        p.shutdown(wait=False, cancel_futures=True)
    summary = {}
    for (name, s, outcome, tag), c in sorted(tally.items()):
        summary.setdefault(name, []).append(f"{s}: {outcome}{(' [' + tag + ']') if tag else ''} x{c}")
    with open(out.replace(".jsonl", ".summary.json"), "w") as f:
        json.dump({"args": vars(a), "tally": {" | ".join(k): v for k, v in tally.items()}}, f, indent=1)
    for name, lines in summary.items():
        print(f"\n== {name}")
        for ln in lines:
            print("  ", ln)
    print("results ->", out)


def shrink_case(system, prog, timeout):
    """Greedy delta-debug the program while `system` still deviates from the oracle."""
    pool = _pool()

    def still(p):
        try:
            r = pool.submit(_task, ("sym", system, p)).result(timeout=timeout)
            if not r["ok"] or r["result"] is None:
                return False
            bad, _ = compare(system, flatten(exact_probs(p)), flatten(r["result"]), backends.TOL[system])
            return bool(bad)
        except Exception:
            return False
    try:
        return shrink(prog, still).to_text()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
