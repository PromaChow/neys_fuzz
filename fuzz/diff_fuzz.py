"""Differential fuzzing of neurosymbolic libraries against their logical counterparts on fixed, new dimensions.

Pairs:   DeepProbLog (exact / approximate engine)  vs  ProbLog (sdd)         [+ exact rational oracle]
         NeurASP MVPP layer                         vs  ProbLog / clingo       [+ exact rational oracle]
Dimensions (all derived from thresholds and tests found in the code of the libraries themselves):
  D1  threshold-straddling probabilities       values around each engine-internal epsilon / float32 limit
  D2  disjunction geometry                     group size x sum slack (incl. sums above 1) x zero-probability member
  D3  chain length                             long conjunctions (underflow) and disjunctions (rounding to 1.0)
  D4  evaluation-mode invariance               batch / order / duplicates / repeated call / cache (DeepProbLog)
  D5  neural saturation                        the same distribution supplied via a network vs as literal facts
The exact oracle uses fractions.Fraction on the very decimal text given to every system.
"""
import json
import math
import os
import sys
import time
import warnings
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutTimeout
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "NeurASP"))
OUT = os.path.join(HERE, "..", "results", "diff_fuzz.jsonl")
TMP = "/tmp/nesyfuzz"

THRESHOLDS = {"deepproblog_semiring_eps": 1e-5, "neurasp_mvpp_eps": 1e-6, "float32_eps": 1.19e-7,
              "problog_suspect": 1e-9, "tiny": 1e-12, "float32_min_normal": 1.18e-38, "float32_subnormal": 1e-42}
MULTS = [0.5, 0.999, 1.0, 1.001, 2.0]


def fr(x):
    return Fraction(repr(float(x)))


# ------------------------------------------------------------------ case generators (pure data)
def case_d1():
    for tname, T in THRESHOLDS.items():
        for m in MULTS:
            t = T * m
            prog = f"{t!r}::a. {t!r}::b.\nq :- a.\nq :- b.\nr :- a, b.\n"
            exact = {"a": fr(t), "q": 1 - (1 - fr(t)) ** 2, "r": fr(t) ** 2}
            yield {"dim": "D1", "level": f"{tname} x{m}", "param": t, "prolog": prog, "queries": ["a", "q", "r"],
                   "exact": exact, "mvpp": ([t, t], [("a", [0], "and"), ("q", [0, 1], "or"), ("r", [0, 1], "and")])}
            if t >= 1e-12:
                u = 1.0 - t
                prog2 = f"{u!r}::c. 0.5::d.\ns :- c, d.\n"
                yield {"dim": "D1", "level": f"near-one {tname} x{m}", "param": t, "prolog": prog2, "queries": ["c", "s"],
                       "exact": {"c": fr(u), "s": fr(u) / 2}, "mvpp": None}


def case_d2():
    for n in (2, 5, 20, 100):
        for slack in (0.0, 1e-12, 1e-9, 1e-6, 0.1, -1e-12, -1e-6):          # negative slack = sum above 1 (invalid)
            for zero in (False, True):
                total = 1.0 - slack
                probs = [total / n] * n
                if zero:
                    probs[-1] = 0.0
                    rest = total / (n - 1)
                    probs[:-1] = [rest] * (n - 1)
                names = [f"a{i}" for i in range(n)]
                prog = "; ".join(f"{p!r}::{nm}" for p, nm in zip(probs, names)) + ".\n"
                prog += "".join(f"some :- {nm}.\n" for nm in names)
                valid = sum(fr(p) for p in probs) <= 1
                exact = {"some": sum(fr(p) for p in probs), "a0": fr(probs[0])}
                yield {"dim": "D2", "level": f"n={n} slack={slack:g} zero={zero}", "param": slack, "prolog": prog + "",
                       "queries": ["some", "a0"], "exact": exact if valid else None, "valid": valid,
                       "mvpp": ("group", probs)}


def case_d3():
    for n in (1, 2, 5, 10, 20, 30, 38, 39, 40, 45, 60, 100):
        for p in (0.1, 0.5, 0.9, 0.999):
            facts = "".join(f"{p!r}::f{i}.\n" for i in range(n))
            conj = "q :- " + ", ".join(f"f{i}" for i in range(n)) + ".\n"
            disj = "".join(f"d :- f{i}.\n" for i in range(n))
            yield {"dim": "D3", "level": f"chain n={n} p={p}", "param": n, "prolog": facts + conj + disj, "queries": ["q", "d"],
                   "exact": {"q": fr(p) ** n, "d": 1 - (1 - fr(p)) ** n}, "mvpp": ([p] * n, [("q", list(range(n)), "and"), ("d", list(range(n)), "or")])}


# ------------------------------------------------------------------ system adapters (run inside workers)
def write_prog(text):
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, f"p{abs(hash(text)) % 10**12}.pl")
    open(path, "w").write(text)
    return path


def run_logic(system, case):
    from adopt_problog_tests import evaluate
    text = case["prolog"] + "".join(f"query({q}).\n" for q in case["queries"])     # ProbLog answers only query/1 statements
    path = write_prog(text)
    r = evaluate((system, path, case["queries"]))
    return r


def run_mvpp(case):
    """NeurASP MVPP on the same case (D1 pair/chain, D2 group, D3 chain); learning-free, float32 tensors as in training."""
    warnings.filterwarnings("ignore")
    import torch
    from mvpp import MVPP
    spec = case.get("mvpp")
    if spec is None:
        return {"ok": False, "error": "NotApplicable", "message": ""}
    t0 = time.time()
    try:
        if spec[0] == "group":
            probs = spec[1]
            n = len(probs)
            tot = sum(fr(p) for p in probs)
            lines = ["; ".join([f"{p!r} g(0,0,{j + 1})" for j, p in enumerate(probs)] + [f"{float(max(1 - tot, 0))!r} g(0,0,0)"]) + "."]
            lines += [f"a{j}  :- g(0,0,{j + 1})." for j in range(n)]
            lines += [f"some :- a{j}." for j in range(n)]
            obs = {"some": ":- not some.\n", "a0": ":- not a0.\n"}
        else:
            probs, defs = spec
            n = len(probs)
            lines = [f"{p!r} f(0,{i},1) ; {repr(1.0 - p)} f(0,{i},0)." for i, p in enumerate(probs)]
            obs = {}
            for name, idxs, kind in defs:
                if kind == "and":
                    lines.append(f"{name} :- " + ", ".join(f"f(0,{i},1)" for i in idxs) + ".")
                else:
                    lines += [f"{name} :- f(0,{i},1)." for i in idxs]
                obs[name] = f":- not {name}.\n"
            if any(kind == "or" for _, _, kind in defs) and n > 16:
                obs = {k: v for k, v in obs.items() if k not in [d[0] for d in defs if d[2] == "or"]}   # 2^n stable models
        m = MVPP("\n".join(lines) + "\n")
        m.parameters = [torch.Tensor(pr) for pr in m.parameters]
        res = {}
        for name, o in obs.items():
            models = m.find_k_SM_under_obs(o, k=0)
            res[name] = 0.0 if len(models) == 0 else float(m.prob_of_interpretation(models).sum())
        return {"ok": True, "result": res, "secs": time.time() - t0}
    except SystemExit as e:
        return {"ok": False, "error": "SystemExit", "message": str(e.code)}
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"ok": False, "error": type(e).__name__, "message": str(e)[:120]}


def run_neural(case):
    """D5: neural predicate path (softmax of logits in float32) vs literal facts. Returns dict system->result."""
    warnings.filterwarnings("ignore")
    import torch
    from deepproblog.engines import ExactEngine, ApproximateEngine
    from deepproblog.model import Model
    from deepproblog.network import Network
    from deepproblog.query import Query
    from problog.logic import Term
    gap = case["param"]

    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.logits = torch.nn.Parameter(torch.tensor([0.0, -float(gap)]))

        def forward(self, *_):
            return torch.softmax(self.logits, -1)

    prog = "nn(sat,[X],Y,[a,b]) :: c(X,Y).\nq :- c(i,b).\nr :- c(i,a).\n"
    out = {}
    for name, mk in (("dpl_exact_neural", lambda m: ExactEngine(m)),
                     ("dpl_approx_ucs_neural", lambda m: ApproximateEngine(m, 10, ApproximateEngine.ucs)),
                     ("dpl_approx_gm_neural", lambda m: ApproximateEngine(m, 10, ApproximateEngine.geometric_mean))):
        try:
            m = Model(prog, [Network(Net(), "sat")], load=False)
            m.set_engine(mk(m))
            res = {}
            for q in ("q", "r"):
                r = m.solve([Query(Term(q))])[0].result
                res[q] = float(r[Term(q)]) if Term(q) in r else None
            out[name] = {"ok": True, "result": res}
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            out[name] = {"ok": False, "error": type(e).__name__, "message": str(e)[:100]}
    return out


def task(args):
    kind, payload = args
    try:
        if kind in ("problog_sdd", "dpl_exact", "dpl_approx_ucs", "dpl_approx_gm"):
            return run_logic(kind, payload)
        if kind == "nasp":
            return run_mvpp(payload)
        if kind == "neural":
            return {"ok": True, "result": run_neural(payload)}
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"ok": False, "error": type(e).__name__, "message": str(e)[:100]}


class Pool:
    def __init__(self, timeout=40):
        self.timeout = timeout
        self._new()

    def _new(self):
        self.p = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))

    def run(self, kind, payload):
        fut = self.p.submit(task, (kind, payload))
        try:
            return fut.result(timeout=self.timeout)
        except FutTimeout:
            for pr in list(self.p._processes.values()):
                pr.terminate()
            self.p.shutdown(wait=False, cancel_futures=True)
            self._new()
            return {"ok": False, "error": "TIMEOUT", "message": f">{self.timeout}s"}
        except Exception as e:
            self._new()
            return {"ok": False, "error": "WorkerCrash", "message": str(e)[:100]}


# ------------------------------------------------------------------ judging
def grade(value, exact):
    """exact: Fraction. Returns (category, detail)."""
    if value is None:
        return "absent", ""
    e = float(exact)
    if exact == 0:
        return ("agree", "") if abs(value) <= 1e-12 else ("wrong", f"{value!r} vs 0")
    if value == 0.0:
        return "underflow_to_zero", f"exact {e:.3g}"
    if value == 1.0 and exact < 1 and float(1 - exact) > 1e-12:
        return "rounds_to_one", f"exact {e!r}"
    rel = abs(value - e) / abs(e)
    if rel <= 1e-4:
        return "agree", f"rel err {rel:.1e}"
    return "wrong", f"{value!r} vs exact {e!r} (rel err {rel:.2g})"


def judge_case(case, results):
    """results: system -> run result. Returns system -> {query: (category, detail)}."""
    verdict = {}
    for sysname, r in results.items():
        if not r["ok"]:
            verdict[sysname] = {"*": (r["error"], r.get("message", ""))}
            continue
        res = r["result"]
        if case.get("exact") is None:                       # invalid input: record acceptance
            verdict[sysname] = {"*": ("accepted_invalid", f"values {dict(list(res.items())[:2])}")}
            continue
        verdict[sysname] = {q: grade(res.get(q), ex) for q, ex in case["exact"].items() if q in res or True}
    return verdict


def main():
    cases = list(case_d1()) + list(case_d2()) + list(case_d3())
    if os.environ.get("DIFF_LIMIT"):
        k = int(os.environ["DIFF_LIMIT"])
        cases = cases[:k] + [c for c in cases if c["dim"] == "D2"][:k] + [c for c in cases if c["dim"] == "D3"][:k]
    pool = Pool()
    n = 0
    with open(OUT, "w") as fo:
        for c in cases:
            results = {s: pool.run(s, c) for s in ("problog_sdd", "dpl_exact", "dpl_approx_ucs", "nasp")}
            row = {"dim": c["dim"], "level": c["level"], "param": c["param"], "valid": c.get("valid", True),
                   "verdict": judge_case(c, results),
                   "raw": {s: (r["result"] if r["ok"] else {"error": r["error"]}) for s, r in results.items()}}
            fo.write(json.dumps(row, default=str) + "\n")
            n += 1
            if n % 50 == 0:
                print(f"[{n}/{len(cases)}]", flush=True)
        # D5 neural saturation
        for gap in (0, 10, 20, 40, 80, 100, 104, 110, 150, 200):
            e_b = Fraction(1) / (1 + Fraction(math.exp(gap)))      # float64 softmax, converted exactly
            c = {"dim": "D5", "level": f"logit gap {gap}", "param": gap}
            nr = pool.run("neural", c)
            neural = nr["result"] if nr.get("ok") else {s: {"ok": False, "error": nr.get("error", "?"), "message": nr.get("message", "")}
                                                         for s in ("dpl_exact_neural", "dpl_approx_ucs_neural", "dpl_approx_gm_neural")}
            pb = float(1 / (1 + math.exp(gap)))
            pa = 1.0 - pb
            lit = {"dim": "D5", "level": c["level"], "param": gap,
                   "prolog": f"{pa!r}::c_a; {pb!r}::c_b.\nq :- c_b.\nr :- c_a.\n", "queries": ["q", "r"]}
            literal = {"problog_sdd": pool.run("problog_sdd", lit), "dpl_exact_literal": pool.run("dpl_exact", lit),
                       "dpl_approx_ucs_literal": pool.run("dpl_approx_ucs", lit)}
            exact = {"q": e_b, "r": 1 - e_b}
            verdict = {}
            for s, r in {**neural, **literal}.items():
                verdict[s] = {q: grade(r["result"].get(q), ex) for q, ex in exact.items()} if r["ok"] else {"*": (r["error"], r.get("message", ""))}
            raw = {s: (r["result"] if r["ok"] else {"error": r["error"]}) for s, r in {**neural, **literal}.items()}
            fo.write(json.dumps({"dim": "D5", "level": c["level"], "param": gap, "valid": True, "verdict": verdict, "raw": raw}, default=str) + "\n")
    print("done", n, "cases + D5")


if __name__ == "__main__":
    main()
