"""Mutate the inputs of DeepProbLog's own tests and judge the results.

Pipeline:  seeds (traced from the original tests)  ->  mutants  ->  run on DeepProbLog  ->  oracles
Inputs mutated: probabilities (boundary / perturbed / complement), clause order, duplicated rules,
consistent predicate renaming, and the inference engine (Exact <-> Approximate).

Oracles (the original expected values no longer apply after a mutation):
  metamorphic   reorder / duplicate-rule / rename must not change any probability (vs the unmutated seed)
  ProbLog       independent exact evaluation of the mutated program (when it is plain ProbLog)
  invariants    0 <= p <= 1, no NaN, no crash, no hang
  differential  ExactEngine vs ApproximateEngine
"""
import argparse
import json
import math
import os
import random
import re
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutTimeout
import multiprocessing as mp

HERE = os.path.dirname(__file__)
SEEDS = os.path.join(HERE, "..", "results", "seeds", "deepproblog_seeds.json")
BOUNDARY = [0.0, 1.0, 1e-9, 1.0 - 1e-9, 1e-5, 1.0001e-5, 0.99999, 0.5]
BUILTINS = {"between", "list_to_tensor", "tensor_index", "less_than", "evaluate", "ith_word", "t", "nn",
            "query", "findall", "member", "append", "length", "is", "not", "true", "fail", "call"}
PROB_RE = re.compile(r"(?P<t>t\()?(?P<num>\d+\.\d+(?:e[-+]?\d+)?|\d+e[-+]?\d+|\d+)(?(t)\))\s*::")


# ------------------------------------------------------------------ program text helpers
def statements(text):
    """Split a program into statements (a statement ends with '.' at the end of a line)."""
    out, cur = [], []
    for line in text.splitlines():
        s = line.split("%")[0].rstrip()
        if not s.strip():
            continue
        cur.append(s)
        if s.endswith("."):
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return out


def join(stmts):
    return "\n".join(stmts) + "\n"


def fmt(p):
    return repr(float(p))


def mutate_prob(stmts, rng):
    """Replace one numeric probability; for annotated disjunctions rescale the other alternatives."""
    cands = [(i, m) for i, s in enumerate(stmts) for m in PROB_RE.finditer(s)]
    if not cands:
        return None
    i, m = rng.choice(cands)
    old = float(m.group("num"))
    kind = rng.choice(["boundary", "boundary", "perturb", "complement"])
    if kind == "boundary":
        new = rng.choice(BOUNDARY)
    elif kind == "perturb":
        new = min(max(old + rng.choice([-1, 1]) * rng.choice([1e-9, 1e-6, 1e-3, 0.1]), 0.0), 1.0)
    else:
        new = 1.0 - old
    s = stmts[i]
    matches = list(PROB_RE.finditer(s))
    repaired = ""
    pieces, last = [], 0
    others = [x for x in matches if x is not m]
    if ";" in s and others:                     # annotated disjunction: keep the group sum <= 1
        rest_old = sum(float(x.group("num")) for x in others)
        budget = max(1.0 - new, 0.0)
        scale = (budget / rest_old) if rest_old > 0 else 0.0
        if rest_old > budget:                   # only shrink; never push the group above 1
            repaired = f" (rescaled {len(others)} sibling alternative(s) by {scale:.6g})"
        else:
            scale = 1.0
    else:
        scale = 1.0
    for x in matches:
        pieces.append(s[last:x.start("num")])
        if x is m:
            pieces.append(fmt(new))
        else:
            pieces.append(fmt(float(x.group("num")) * scale) if scale != 1.0 else x.group("num"))
        last = x.end("num")
    pieces.append(s[last:])
    out = list(stmts)
    out[i] = "".join(pieces)
    return out, f"probability {old!r} -> {new!r} ({kind}){repaired}"


def clause_heads(stmts):
    names = set()
    for s in stmts:
        head = s.split(":-")[0]
        for m in re.finditer(r"(?<![A-Za-z0-9_])([a-z][A-Za-z0-9_]*)", head.split("::")[-1]):
            names.add(m.group(1))
    return names - BUILTINS


def rename(stmts, queries, rng):
    names = sorted(clause_heads(stmts))
    if not names:
        return None
    n = rng.choice(names)
    new = n + "_rn"
    sub = lambda s: re.sub(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", new, s)
    return [sub(s) for s in stmts], [sub(q) for q in queries], f"rename predicate {n} -> {new}"


# ------------------------------------------------------------------ execution (inside worker)
def _term(q):
    from problog.program import PrologString
    return list(PrologString(q + "."))[0]


def run_dpl(program, engine, queries):
    warnings.filterwarnings("ignore")
    import torch
    from deepproblog.engines import ExactEngine, ApproximateEngine
    from deepproblog.model import Model
    from deepproblog.query import Query
    m = Model(program, [], load=False)
    if engine["cls"] == "ExactEngine":
        m.set_engine(ExactEngine(m))
    else:
        h = ApproximateEngine.ucs if engine.get("heuristic") == "ucs" else ApproximateEngine.geometric_mean
        m.set_engine(ApproximateEngine(m, engine.get("k") or 10, h))
    out = {}
    for q in queries:
        t = _term(q)
        res = m.solve([Query(t)])[0].result
        out[q] = {str(k): float(v) for k, v in res.items()}
    return out


def run_problog(program, queries):
    from problog import get_evaluatable
    from problog.program import PrologString
    text = re.sub(r"t\(([^)]*)\)\s*::", r"\1 ::", program)
    text += "\n" + "\n".join(f"query({q})." for q in queries) + "\n"
    res = get_evaluatable().create_from(PrologString(text)).evaluate()
    out = {q: {} for q in queries}
    for term, val in res.items():
        for q in queries:
            if _unify_prefix(str(term), q):
                out[q][str(term)] = float(val)
    return out


def _unify_prefix(term_s, q):
    fq = re.match(r"[a-z][A-Za-z0-9_]*", q).group(0)
    return re.match(r"[a-z][A-Za-z0-9_]*", term_s) and re.match(r"[a-z][A-Za-z0-9_]*", term_s).group(0) == fq


def task(args):
    kind, program, engine, queries = args
    t0 = time.time()
    try:
        if kind == "dpl":
            r = run_dpl(program, engine, queries)
        else:
            r = run_problog(program, queries)
        return {"ok": True, "result": r, "secs": time.time() - t0}
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "secs": time.time() - t0}


class Runner:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.pool = None
        self._new()

    def _new(self):
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))

    def run(self, *a):
        fut = self.pool.submit(task, a)
        try:
            return fut.result(timeout=self.timeout)
        except FutTimeout:
            for p in list(self.pool._processes.values()):
                p.terminate()
            self.pool.shutdown(wait=False, cancel_futures=True)
            self._new()
            return {"ok": False, "error": f"TIMEOUT>{self.timeout}s", "secs": self.timeout}
        except Exception as e:
            self._new()
            return {"ok": False, "error": f"WORKER {type(e).__name__}: {e}", "secs": 0}


# ------------------------------------------------------------------ judging
def close(a, b):
    return abs(a - b) <= 1e-12 + 1e-5 * max(abs(a), abs(b))


def flat(res):
    """Merge all queries into one {ground term: probability} map (a term may answer several queries)."""
    return {k: v for q, d in res.items() for k, v in d.items()}


def rename_keys(res, old, new):
    sub = lambda s: re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", new, s)
    return {sub(q): {sub(k): v for k, v in d.items()} for q, d in res.items()}


def judge(m, base, got, oracle):
    """Return a list of (category, detail)."""
    f = []
    if not got["ok"]:
        err = got["error"]
        if oracle is not None and not oracle["ok"]:
            return [("consistent_rejection", err)]
        cat = "timeout" if err.startswith("TIMEOUT") else "exception"
        if m["input_valid"] is False:
            cat = "invalid_input_error"
        return [(cat, err)]
    res = got["result"]
    for k, v in flat(res).items():
        if math.isnan(v) or v < -1e-9 or v > 1 + 1e-6:
            f.append(("range_violation", f"{k} = {v!r}"))
    if m["input_valid"] is False:
        rejected_by_problog = oracle is not None and not oracle["ok"]
        cat = "missing_validation" if rejected_by_problog else "invalid_input_accepted_both"
        f.append((cat, f"DeepProbLog accepted and returned {dict(list(flat(res).items())[:3])}"
                       + (f"; ProbLog rejects: {oracle['error'][:60]}" if rejected_by_problog else "")))
    if m["expect"] == "same_as_seed" and base is not None and base["ok"]:
        want = base["result"]
        if m.get("renamed"):
            want = rename_keys(want, *m["renamed"])
        a, b = flat(want), flat(res)
        for key in set(a) | set(b):
            if not close(a.get(key, 0.0), b.get(key, 0.0)):
                f.append(("metamorphic_violation", f"{key}: seed={a.get(key, 0.0)!r} mutant={b.get(key, 0.0)!r}"))
    if oracle is not None and oracle["ok"] and m["input_valid"] is not False:
        a, b = flat(oracle["result"]), flat(res)
        approx = m["engine"]["cls"] == "ApproximateEngine"
        zero_fact = bool(re.search(r"(?<![0-9.])(?:t\()?0(?:\.0*)?\)?\s*::", m["program"]))
        for key in set(a) | set(b):
            want, have = a.get(key, 0.0), b.get(key, 0.0)
            if approx:
                if key not in b and want > 1e-12:
                    ground = not any(re.search(r"\b[A-Z_]", q) for q in m["queries"])
                    if zero_fact:
                        f.append(("approx_missing_zero_prob_fact", f"{key}: exact={want!r}, absent from ApproximateEngine result; program has a 0.0 fact"))
                    elif ground:
                        f.append(("approx_missing_ground", f"{key}: exact={want!r}, absent from ApproximateEngine result"))
                    # non-ground query with small k: a legitimately partial answer set, not a finding
                elif have > want + 1e-5 * max(1, want):
                    f.append(("approx_above_exact", f"{key}: approx={have!r} > exact={want!r}"))
            elif not close(want, have):
                if want < 1e-9 and have > want:      # ProbLog itself returns 0.0 for tiny probabilities
                    f.append(("oracle_limit_tiny_values", f"{key}: ProbLog={want!r} DeepProbLog={have!r} (ProbLog loses values below ~1e-9)"))
                    continue
                f.append(("oracle_mismatch", f"{key}: ProbLog={want!r} DeepProbLog({m['engine']['cls']})={have!r}"))
    return f


# ------------------------------------------------------------------ driver
def load_seeds():
    seeds = json.load(open(SEEDS))
    out = []
    for i, s in enumerate(seeds):
        if s["networks"] or not s["program"] or not s["queries"] or not s["engine"]:
            continue
        if s["engine"]["cls"] not in ("ExactEngine", "ApproximateEngine"):
            continue
        out.append(dict(s, id=i))
    return out


def make_mutants(seed, rng, n):
    stmts = statements(seed["program"])
    eng, qs = seed["engine"], seed["queries"]
    ms = []
    ops = ["prob", "prob", "prob", "reorder", "dup_rule", "rename", "engine_swap", "invalid_group", "invalid_prob"]
    for _ in range(n):
        op = rng.choice(ops)
        m = {"seed": seed["id"], "test": seed["test"], "op": op, "engine": eng, "queries": qs,
             "input_valid": True, "expect": "oracle"}
        if op == "prob":
            r = mutate_prob(stmts, rng)
            if r is None:
                continue
            m["program"], m["desc"] = join(r[0]), r[1]
        elif op == "reorder":
            s2 = list(stmts)
            rng.shuffle(s2)
            if s2 == stmts:
                continue
            m.update(program=join(s2), desc="shuffle clause order", expect="same_as_seed")
        elif op == "dup_rule":
            rules = [i for i, s in enumerate(stmts) if ":-" in s and "::" not in s]
            if not rules:
                continue
            i = rng.choice(rules)
            s2 = list(stmts) + [stmts[i]]
            m.update(program=join(s2), desc=f"duplicate rule #{i}", expect="same_as_seed")
        elif op == "rename":
            r = rename(stmts, qs, rng)
            if r is None:
                continue
            old = r[2].split()[2]
            m.update(program=join(r[0]), queries=r[1], desc=r[2], expect="same_as_seed", renamed=(old, old + "_rn"))
        elif op == "engine_swap":
            if eng["cls"] == "ExactEngine":
                m["engine"] = {"cls": "ApproximateEngine", "k": rng.choice([1, 3, 100]),
                               "heuristic": rng.choice(["geometric_mean", "ucs"])}
            else:
                m["engine"] = {"cls": "ExactEngine", "k": None, "heuristic": None}
            m.update(program=join(stmts), desc=f"engine {eng['cls']} -> {m['engine']['cls']}")
        elif op == "invalid_group":
            ad = [i for i, s in enumerate(stmts) if ";" in s and len(PROB_RE.findall(s)) >= 2]
            if not ad:
                continue
            i = rng.choice(ad)
            s = stmts[i]
            first = PROB_RE.search(s)
            new = s[:first.start("num")] + "0.9" + s[first.end("num"):]
            ms2 = list(stmts)
            ms2[i] = new
            m.update(program=join(ms2), desc="make an annotated disjunction sum above 1 (invalid)",
                     input_valid=False)
        elif op == "invalid_prob":
            cands = [(i, x) for i, s in enumerate(stmts) for x in PROB_RE.finditer(s) if ";" not in s]
            if not cands:
                continue
            i, x = rng.choice(cands)
            bad = rng.choice(["1.5", "-0.5", "2.0"])
            s = stmts[i]
            ms2 = list(stmts)
            ms2[i] = s[:x.start("num")] + bad + s[x.end("num"):]
            m.update(program=join(ms2), desc=f"probability {x.group('num')} -> {bad} (outside [0,1])", input_valid=False)
        ms.append(m)
    return ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-seed", type=int, default=25)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "results", "dpl_mutation_results.jsonl"))
    a = ap.parse_args()
    rng = random.Random(a.rng)
    seeds = load_seeds()
    runner = Runner(a.timeout)
    print(f"{len(seeds)} usable seeds (no networks, with queries); {a.per_seed} mutants each", flush=True)
    summary, n_run = {}, 0
    with open(a.out, "w") as fout:
        for seed in seeds:
            base = runner.run("dpl", seed["program"], seed["engine"], seed["queries"])
            if not base["ok"]:
                print(f"skip seed {seed['id']} ({seed['test'].split('::')[-1]}): unmutated replay fails: {base['error'][:60]}", flush=True)
                continue
            base_oracle = runner.run("problog", seed["program"], seed["engine"], seed["queries"])
            fout.write(json.dumps({"kind": "seed_baseline", "seed": seed["id"], "test": seed["test"],
                                   "dpl_ok": base["ok"], "problog_ok": base_oracle["ok"],
                                   "dpl_error": base.get("error"), "problog_error": base_oracle.get("error")}) + "\n")
            for m in make_mutants(seed, rng, a.per_seed):
                got = runner.run("dpl", m["program"], m["engine"], m["queries"])
                oracle = runner.run("problog", m["program"], m["engine"], m["queries"]) if m["expect"] == "oracle" or m["op"] in ("invalid_group", "invalid_prob") else None
                findings = judge(m, base, got, oracle)
                n_run += 1
                key = m["op"]
                s = summary.setdefault(key, {"mutants": 0, "flagged": 0})
                s["mutants"] += 1
                if any(c not in ("consistent_rejection", "invalid_input_error", "oracle_limit_tiny_values") for c, _ in findings):
                    s["flagged"] += 1
                fout.write(json.dumps({"kind": "mutant", **{k: v for k, v in m.items()},
                                       "findings": findings,
                                       "dpl": got if not got["ok"] else {"ok": True}}) + "\n")
                fout.flush()
    print(f"ran {n_run} mutants")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
