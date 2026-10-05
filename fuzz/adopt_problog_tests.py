"""Adopt the logical counterpart's tests: run ProbLog's own system tests (test/*.pl) through DeepProbLog.

For every ProbLog test program we read the expected outcome exactly as ProbLog's runner does
(`% atom probability` lines, or `% error <Name>`), then evaluate it with
  - ProbLog itself (sdd evaluatable; the repo's ddnnf one needs the external binary `dsharp`)  -> baseline
  - DeepProbLog ExactEngine
  - DeepProbLog ApproximateEngine (k=100) with the geometric_mean and ucs heuristics
and classify each outcome.
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
TESTS = os.path.join(HERE, "..", "frameworks", "problog", "test")
OUT = os.path.join(HERE, "..", "results", "adopt_problog_to_deepproblog.jsonl")
STRICT = 5e-8          # ProbLog's assertAlmostEqual (7 decimal places)
FLOAT32 = 1e-5         # DeepProbLog computes with float32 tensors


def read_result(filename):
    """Verbatim logic of problog/test/test_system.py::read_result."""
    results = {}
    with open(filename) as f:
        reading = False
        for l in f:
            l = l.strip()
            if l.startswith("%Expected outcome:"):
                reading = True
            elif reading:
                if l.lower().startswith("% error"):
                    return l[len("% error"):].strip()
                elif l.startswith("% "):
                    query, prob = l[2:].rsplit(None, 1)
                    results[query.strip()] = float(prob.strip())
                else:
                    reading = False
            if l.startswith("query(") and l.find("% outcome:") >= 0:
                pos = l.find("% outcome:")
                query = l[6:pos].strip().rstrip(".").rstrip()[:-1]
                prob = l[pos + 10:]
                results[query.strip()] = float(prob.strip())
    return results


def program_queries(text):
    """Atoms asked by the program's own `query(...)` statements."""
    out = []
    for l in text.splitlines():
        m = re.match(r"^\s*query\((.*)\)\s*\.\s*(?:%.*)?$", l)
        if m:
            out.append(m.group(1).strip())
    return out


def own_queries(filename):
    """The query(...) statements of a program, read with ProbLog's own parser (extended syntax included)."""
    from problog.logic import Term
    from problog.parser import DefaultPrologParser
    from problog.program import PrologFile, ExtendedPrologFactory
    prog = PrologFile(filename, parser=DefaultPrologParser(ExtendedPrologFactory()))
    return [t.args[0] for t in prog if isinstance(t, Term) and t.functor == "query" and t.arity == 1]


def features(text):
    tags = []
    if re.search(r"^\s*evidence\(", text, re.M): tags.append("evidence")
    if "<-" in text: tags.append("ad_arrow")
    if re.search(r";\s*[\d/.]+::", text) or re.search(r"::[^;\n]*;\s*[\d/.]+::", text): tags.append("annotated_disjunction")
    if re.search(r"^\s*:-", text, re.M): tags.append("directive")
    if re.search(r"\bt\(", text): tags.append("learnable_t")
    if re.search(r"\bsubquery|\bbuiltin|\bfindall|\bforall|\bbetween\(|\blength\(", text): tags.append("builtin_calls")
    if re.search(r"^\s*query\(", text, re.M): tags.append("query_stmt")
    return tags


# ----------------------------------------------------------------- evaluation (runs in a worker process)
def evaluate(task):
    """task = (system, filename, queries). Returns {'ok':..., 'result' | 'error', 'secs'}"""
    warnings.filterwarnings("ignore")
    system, filename, queries = task
    t0 = time.time()
    os.chdir(os.path.dirname(os.path.abspath(filename)))
    try:
        if system == "problog_sdd":
            from problog import get_evaluatable
            from problog.parser import DefaultPrologParser
            from problog.program import PrologFile, ExtendedPrologFactory
            parser = DefaultPrologParser(ExtendedPrologFactory())
            kc = get_evaluatable(name="sdd").create_from(PrologFile(filename, parser=parser))
            res = {str(k): float(v) for k, v in kc.evaluate().items()}
        else:
            from deepproblog.engines import ExactEngine, ApproximateEngine
            from deepproblog.model import Model
            from deepproblog.query import Query
            from problog.program import PrologString
            text = open(filename).read()
            if queries is None:
                queries = own_queries(filename)
            m = Model(text, [], load=False)
            if system == "dpl_exact":
                m.set_engine(ExactEngine(m))
            else:
                h = ApproximateEngine.ucs if system == "dpl_approx_ucs" else ApproximateEngine.geometric_mean
                m.set_engine(ApproximateEngine(m, 100, h))
            res = {}
            for q in queries:
                term = q if not isinstance(q, str) else list(PrologString(q + "."))[0]
                r = m.solve([Query(term)])[0].result
                for k, v in r.items():
                    res[str(k)] = float(v)
        return {"ok": True, "result": res, "secs": time.time() - t0}
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"ok": False, "error": type(e).__name__, "message": str(e)[:160], "secs": time.time() - t0}


def classify(correct, got):
    """Mirror ProbLog's check, then grade numeric agreement."""
    if not got["ok"]:
        if isinstance(correct, str):
            return ("error_match" if got["error"] == correct else "error_different",
                    f"expected {correct}, got {got['error']}: {got.get('message', '')[:80]}")
        return ("unexpected_error", f"{got['error']}: {got.get('message', '')[:100]}")
    if isinstance(correct, str):
        return ("missing_expected_error", f"expected error {correct} but computed {len(got['result'])} results")
    res = got["result"]
    worst, missing = 0.0, []
    for q, p in correct.items():
        if q not in res:
            if p > 1e-12:
                missing.append(q)
            continue
        worst = max(worst, abs(p - res[q]))
    extra = [k for k in res if k not in correct]
    if missing:
        return ("result_missing", f"absent from result although expected > 0: {missing[:3]}")
    if worst < STRICT and not extra:
        return ("pass_strict", f"max diff {worst:.2e}")
    if worst < FLOAT32 and not extra:
        return ("pass_float32", f"max diff {worst:.2e} (float32 precision)")
    if worst < FLOAT32:
        return ("pass_extra_keys", f"extra result keys {extra[:3]}")
    return ("mismatch", f"max diff {worst:.3g}")


class Pool:
    def __init__(self, timeout):
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


def main():
    files = sorted(glob.glob(os.path.join(TESTS, "*.pl")))
    pool = Pool(timeout=25)
    systems = ["problog_sdd", "dpl_exact", "dpl_approx_gm", "dpl_approx_ucs"]
    rows = []
    with open(OUT, "w") as fo:
        for i, fn in enumerate(files):
            name = os.path.basename(fn)
            correct = read_result(fn)
            text = open(fn).read()
            queries = None            # DeepProbLog systems extract the program's own queries in the worker
            row = {"program": name, "expected_kind": "error" if isinstance(correct, str) else "values",
                   "expected_error": correct if isinstance(correct, str) else None,
                   "n_queries": len(correct) if isinstance(correct, dict) else 0, "features": features(text), "systems": {}}
            for s in systems:
                got = pool.run((s, fn, queries))
                cat, detail = classify(correct, got)
                row["systems"][s] = {"category": cat, "detail": detail, "secs": round(got["secs"], 2)}
            rows.append(row)
            fo.write(json.dumps(row) + "\n")
            fo.flush()
            if (i + 1) % 20 == 0:
                print(f"[{i + 1}/{len(files)}]", flush=True)
    # summary
    import collections
    print(f"\n{len(rows)} ProbLog test programs adopted\n")
    for s in systems:
        c = collections.Counter(r["systems"][s]["category"] for r in rows)
        print(f"{s:15s}", dict(c.most_common()))


if __name__ == "__main__":
    main()
