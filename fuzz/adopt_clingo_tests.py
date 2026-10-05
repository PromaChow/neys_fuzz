"""Adopt the logical counterpart's tests: run clingo's own plain-ASP programs through NeurASP's MVPP layer.

Reference  = clingo itself (python API, atoms=True so no #show filtering), all answer sets.
Adopted    = NeurASP `MVPP(program).find_all_SM_under_obs('')`, given as a file path and as a string
             (the two parse paths of MVPP.parse differ).
Corpus     = every .lp under app/clingo/tests and examples/ that is a plain ASP program (no #script, no #include).
"""
import glob
import json
import os
import re
import sys
import time
import warnings
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutTimeout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "frameworks", "clingo")
OUT = os.path.join(HERE, "..", "results", "adopt_clingo_to_neurasp.jsonl")
MAX_MODELS = 300


def corpus():
    files = []
    for sub in ("app/clingo/tests/lp", "app/clingo/tests/python", "app/clingo/tests/lua", "examples"):
        files += glob.glob(os.path.join(ROOT, sub, "**", "*.lp"), recursive=True)
    keep, skipped = [], {"#script": 0, "#include": 0, "too_big": 0, "unreadable": 0}
    for f in sorted(set(files)):
        try:
            t = open(f, errors="replace").read()
        except Exception:
            skipped["unreadable"] += 1
            continue
        if "#script" in t:
            skipped["#script"] += 1
        elif "#include" in t:
            skipped["#include"] += 1
        elif len(t) > 150_000:
            skipped["too_big"] += 1
        else:
            keep.append(f)
    return keep, skipped


def models_of(text_or_none, path, system):
    warnings.filterwarnings("ignore")
    if system == "clingo":
        import clingo
        ctl = clingo.Control([str(MAX_MODELS + 1), "--warn=none"])
        ctl.load(path)
        ctl.ground([("base", [])])
        out = []
        ctl.solve(on_model=lambda m: out.append(sorted(str(a) for a in m.symbols(atoms=True))))
        return out
    sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "NeurASP"))
    from mvpp import MVPP
    arg = path if system == "neurasp_file" else open(path, errors="replace").read()
    m = MVPP(arg)
    return [sorted(x) for x in m.find_all_SM_under_obs("")]


def evaluate(task):
    system, path = task
    t0 = time.time()
    try:
        ms = models_of(None, path, system)
        return {"ok": True, "models": ms, "secs": time.time() - t0}
    except SystemExit as e:                          # NeurASP calls sys.exit() on programs it cannot parse
        return {"ok": False, "error": "SystemExit", "message": f"sys.exit({e.code})", "secs": time.time() - t0}
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"ok": False, "error": type(e).__name__, "message": str(e)[:140], "secs": time.time() - t0}


class Pool:
    def __init__(self, timeout=40):
        self.timeout = timeout
        self._new()

    def _new(self):
        self.p = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))

    def run(self, task):
        fut = self.p.submit(evaluate, task)
        try:
            return fut.result(timeout=self.timeout)
        except FutTimeout:
            for pr in list(self.p._processes.values()):
                pr.terminate()
            self.p.shutdown(wait=False, cancel_futures=True)
            self._new()
            return {"ok": False, "error": "TIMEOUT", "message": f">{self.timeout}s", "secs": self.timeout}
        except Exception as e:
            self._new()
            return {"ok": False, "error": "WorkerCrash", "message": str(e)[:100], "secs": 0}


def compare(ref, got):
    if not got["ok"]:
        return got["error"], got.get("message", "")
    a = {tuple(m) for m in ref["models"]}
    b = {tuple(m) for m in got["models"]}
    if a == b:
        return "identical", f"{len(a)} answer set(s)"
    return "different_models", f"clingo {len(a)} answer set(s), NeurASP {len(b)}; only-clingo {len(a - b)}, only-NeurASP {len(b - a)}"


def main():
    files, skipped = corpus()
    print(f"{len(files)} plain-ASP programs; skipped {skipped}", flush=True)
    pool = Pool()
    rows, n_ref_bad = [], 0
    with open(OUT, "w") as fo:
        for i, f in enumerate(files):
            ref = pool.run(("clingo", f))
            rel = os.path.relpath(f, ROOT)
            if not ref["ok"] or len(ref["models"]) > MAX_MODELS:
                n_ref_bad += 1
                fo.write(json.dumps({"program": rel, "excluded": "clingo reference " + (ref.get("error") or f">{MAX_MODELS} models")}) + "\n")
                continue
            row = {"program": rel, "n_models": len(ref["models"]), "systems": {}}
            for s in ("neurasp_file", "neurasp_string"):
                got = pool.run((s, f))
                cat, detail = compare(ref, got)
                row["systems"][s] = {"category": cat, "detail": detail, "secs": round(got["secs"], 2)}
            rows.append(row)
            fo.write(json.dumps(row) + "\n")
            fo.flush()
            if (i + 1) % 25 == 0:
                print(f"[{i + 1}/{len(files)}]", flush=True)
    import collections
    print(f"\n{len(rows)} programs adopted ({n_ref_bad} excluded: clingo reference failed or too many models)")
    for s in ("neurasp_file", "neurasp_string"):
        print(f"{s:15s}", dict(collections.Counter(r["systems"][s]["category"] for r in rows).most_common()))


if __name__ == "__main__":
    main()
