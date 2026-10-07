"""pytest plugin: run DeepProbLog's OWN tests with the inputs they build changed, and record what happens.

Not meant to be run directly; the fuzz_*.py scripts load it with `-p dpl_mutation_plugin`.

Configured by environment variables:
  DPL_MUT_KIND   none | probability | reorder | duplicate_rule | rename | engine_swap
  DPL_MUT_SEED   integer, makes every mutation reproducible
  DPL_MUT_OUT    JSONL file; one record per test is appended
  DPL_MUT_TMO    per-test timeout in seconds (default 20)

What is mutated (hooks on deepproblog.model.Model, the tests' real objects):
  Model.__init__   the program text          -> probability / reorder / duplicate_rule / rename
  Model.set_engine the inference engine      -> engine_swap
  Model.solve      (observe only)            -> range check on every returned probability;
                                                for rename, queries are renamed on the way in and
                                                result keys renamed back, so test code is unaware
Programs that come from a file (load=True) and programs without anything to mutate are left alone;
the record says `applied: false` so they are not counted as mutated runs.
"""
import json
import math
import os
import random
import signal
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
from mutation_helpers import statements, join, mutate_prob, clause_heads  # noqa: E402  (same folder)

KIND = os.environ.get("DPL_MUT_KIND", "none")
SEED = int(os.environ.get("DPL_MUT_SEED", "0"))
OUT = os.environ.get("DPL_MUT_OUT")
TIMEOUT = int(os.environ.get("DPL_MUT_TMO", "20"))

CUR = {"test": None, "applied": [], "range": [], "n_models": 0, "rename": None, "programs": []}


def _rng(tag):
    return random.Random(f"{SEED}:{CUR['test']}:{CUR['n_models']}:{tag}")


def _rename_term(t, old, new):
    from problog.logic import Term
    if type(t) is Term:
        f = new if t.functor == old else t.functor
        return Term(f, *[_rename_term(a, old, new) for a in t.args])
    return t


def _mutate_program(text):
    """Return (new_text, description), or None when this program has nothing to mutate.

    Keeps drawing (up to 20 times) until the program text really changes, so a shuffle that lands on the
    original order or a probability replaced by itself is never counted as a mutation. The first draw uses
    the same RNG stream as before, so earlier seeds still pick the same mutation when it already changed things.
    """
    original = join(statements(text))
    for attempt in range(20):
        r = _attempt(text, "prog" if attempt == 0 else f"prog{attempt}")
        if r and r[0] != original:
            return r
    return None


def _attempt(text, tag):
    rng = _rng(tag)
    stmts = statements(text)
    if KIND == "probability":
        r = mutate_prob(stmts, rng)
        return (join(r[0]), r[1]) if r else None
    if KIND == "reorder":
        s2 = list(stmts)
        rng.shuffle(s2)
        return (join(s2), "shuffle clause order") if len(stmts) > 1 else None
    if KIND == "duplicate_rule":
        rules = [i for i, s in enumerate(stmts) if ":-" in s and "::" not in s]
        if not rules:
            return None
        i = rng.choice(rules)
        return join(stmts + [stmts[i]]), f"duplicate rule #{i}"
    if KIND == "rename":
        names = sorted(clause_heads(stmts))
        if not names:
            return None
        import re
        n = rng.choice(names)
        new = n + "_rn"
        sub = lambda s: re.sub(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", new, s)
        CUR["rename"] = (n, new)
        return join([sub(s) for s in stmts]), f"rename predicate {n} -> {new}"
    return None


def _install():
    from deepproblog.model import Model
    orig_init, orig_set_engine, orig_solve = Model.__init__, Model.set_engine, Model.solve

    def init(self, program_string, networks, embeddings=None, load=True):
        CUR["n_models"] += 1
        CUR["rename"] = None
        if KIND in ("probability", "reorder", "duplicate_rule", "rename") and not load:
            r = _mutate_program(program_string)
            if r:
                CUR["programs"].append({"before": program_string, "after": r[0]})
                program_string = r[0]
                CUR["applied"].append(r[1])
        return orig_init(self, program_string, networks, embeddings, load)

    def set_engine(self, engine, **kw):
        if KIND == "engine_swap" and not kw.get("cache"):   # ApproximateEngine cannot cache: not a valid swap
            from deepproblog.engines import ExactEngine, ApproximateEngine
            if type(engine) is ExactEngine and ApproximateEngine is not None:
                engine = ApproximateEngine(self, 100, ApproximateEngine.geometric_mean)
                CUR["applied"].append("ExactEngine -> ApproximateEngine(k=100, geometric_mean)")
            elif ApproximateEngine is not None and type(engine) is ApproximateEngine:
                engine = ExactEngine(self)
                CUR["applied"].append("ApproximateEngine -> ExactEngine")
        return orig_set_engine(self, engine, **kw)

    def solve(self, batch):
        rn = CUR["rename"] if KIND == "rename" else None
        if rn:
            from deepproblog.query import Query
            batch = [Query(_rename_term(q.query, *rn), q.substitution, q.p, q.output_ind) for q in batch]
        results = orig_solve(self, batch)
        for res in results:
            for k, v in res.result.items():
                try:
                    x = float(v)
                except Exception:
                    continue
                if math.isnan(x) or x < -1e-9 or x > 1 + 1e-6:
                    CUR["range"].append(f"{k} = {x!r}")
            if rn:
                res.result = {_rename_term(k, rn[1], rn[0]): v for k, v in res.result.items()}
        return results

    Model.__init__, Model.set_engine, Model.solve = init, set_engine, solve


def pytest_configure(config):
    _install()


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout(f"TIMEOUT>{TIMEOUT}s")


def _begin(item):
    CUR.update(test=item.nodeid, applied=[], range=[], n_models=0, rename=None, programs=[])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    _begin(item)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT)
    CUR["t0"] = time.time()
    try:
        yield
    finally:
        signal.alarm(0)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if call.when != "call" and not (call.when == "setup" and rep.outcome != "passed"):
        return
    exc_type = exc_msg = None
    if call.excinfo is not None:
        exc_type = call.excinfo.type.__name__
        exc_msg = str(call.excinfo.value)[:300]
    rec = {"kind": KIND, "seed": SEED, "test": item.nodeid, "outcome": rep.outcome,
           "when": call.when, "exc_type": exc_type, "exc_msg": exc_msg,
           "applied": bool(CUR["applied"]), "mutations": list(CUR["applied"]), "programs": list(CUR["programs"]),
           "range_violations": list(CUR["range"]),
           "secs": round(time.time() - CUR.get("t0", time.time()), 3)}
    if OUT:
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
