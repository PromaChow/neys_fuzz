"""D4: evaluation-mode invariance of DeepProbLog on ProbLog's own test programs.

For every program DeepProbLog already passes, the answers must not depend on HOW the questions are asked.
Modes compared against `batch_all` (all queries in one solve call, fresh model):
  singles      one solve call per query
  reversed     queries in reverse order
  duplicated   every query twice in one batch
  second_call  the same batch solved a second time on the same model (state leakage)
  cache        ExactEngine with cache=True (first and second call)
  approx_ucs   ApproximateEngine(k=100, ucs) in one batch (differential, not an invariance)
"""
import glob
import json
import os
import sys
import time
import warnings
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutTimeout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ADOPT = os.path.join(HERE, "..", "results", "adopt_problog_to_deepproblog.jsonl")
TESTS = os.path.join(HERE, "..", "frameworks", "problog", "test")
OUT = os.path.join(HERE, "..", "results", "invariance_dpl.jsonl")


def merged(results):
    out = {}
    for r in results:
        for k, v in r.result.items():
            out[str(k)] = float(v)
    return out


def run_modes(filename):
    warnings.filterwarnings("ignore")
    os.chdir(os.path.dirname(os.path.abspath(filename)))
    from adopt_problog_tests import own_queries
    from deepproblog.engines import ExactEngine, ApproximateEngine
    from deepproblog.model import Model
    from deepproblog.query import Query
    text = open(filename).read()
    qs = own_queries(filename)

    def fresh(engine="exact", cache=False):
        m = Model(text, [], load=False)
        eng = ExactEngine(m) if engine == "exact" else ApproximateEngine(m, 100, ApproximateEngine.ucs)
        m.set_engine(eng, cache=cache)
        return m
    batch = lambda items: [Query(q) for q in items]
    modes = {}
    m = fresh(); modes["batch_all"] = merged(m.solve(batch(qs)))
    m = fresh(); modes["singles"] = merged([r for q in qs for r in m.solve(batch([q]))])
    m = fresh(); modes["reversed"] = merged(m.solve(batch(list(reversed(qs)))))
    m = fresh(); modes["duplicated"] = merged(m.solve(batch(qs + qs)))
    m = fresh(); m.solve(batch(qs)); modes["second_call"] = merged(m.solve(batch(qs)))
    m = fresh(cache=True); m.solve(batch(qs)); modes["cache"] = merged(m.solve(batch(qs)))
    try:
        m = fresh("approx"); modes["approx_ucs"] = merged(m.solve(batch(qs)))
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        modes["approx_ucs"] = {"__error__": type(e).__name__}
    return modes


def task(path):
    t0 = time.time()
    try:
        return {"ok": True, "modes": run_modes(path), "secs": time.time() - t0}
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"ok": False, "error": type(e).__name__, "message": str(e)[:120]}


def close(a, b):
    return abs(a - b) <= 1e-9 + 1e-6 * max(abs(a), abs(b))


def main():
    rows = [json.loads(l) for l in open(ADOPT)]
    seeds = [r["program"] for r in rows if r["systems"]["dpl_exact"]["category"] == "pass_strict"
             and "directive" not in r["features"]]
    print(f"{len(seeds)} programs that DeepProbLog already passes (no directives)", flush=True)
    summary = {}
    with open(OUT, "w") as fo:
        for name in seeds:
            path = os.path.join(TESTS, name)
            ex = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))   # fresh worker per program
            fut = ex.submit(task, path)
            try:
                res = fut.result(timeout=60)
            except FutTimeout:
                res = {"ok": False, "error": "TIMEOUT", "message": ">60s"}
            except Exception as e:                      # e.g. BrokenProcessPool when the embedded Prolog kills the worker
                res = {"ok": False, "error": type(e).__name__, "message": str(e)[:80]}
            for pr in list(ex._processes.values()):
                pr.terminate()
            ex.shutdown(wait=False, cancel_futures=True)
            row = {"program": name, "ok": res["ok"], "diffs": {}}
            if res["ok"]:
                base = res["modes"]["batch_all"]
                for mode, vals in res["modes"].items():
                    if mode == "batch_all":
                        continue
                    if "__error__" in vals:
                        row["diffs"][mode] = [f"error {vals['__error__']}"]
                        continue
                    d = []
                    for k in set(base) | set(vals):
                        if k not in vals:
                            d.append(f"{k}: missing (batch {base[k]!r})")
                        elif k not in base:
                            d.append(f"{k}: extra ({vals[k]!r})")
                        elif not close(base[k], vals[k]):
                            d.append(f"{k}: batch {base[k]!r} vs {vals[k]!r}")
                    if d:
                        row["diffs"][mode] = d[:3]
            else:
                row["error"] = res.get("error")
            fo.write(json.dumps(row) + "\n")
            fo.flush()
            for mode, d in row["diffs"].items():
                summary[mode] = summary.get(mode, 0) + 1
    print("programs where a mode differs from batch_all:", summary)


if __name__ == "__main__":
    main()
