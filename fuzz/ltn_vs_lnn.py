"""Differential test: LTNtorch vs IBM LNN on the same Lukasiewicz formulas (the 'logical counterpart' dimension).

Both libraries claim standard Lukasiewicz semantics for And / Or / Not / Implies (LNN: unweighted neurons with weights 1,
bias 1; LTN: AndLuk, OrLuk, NotStandard, ImpliesLuk). Random formula trees over point truth values (ordinary and special
values) must therefore evaluate identically, up to float32 rounding. Disagreement is a defect in one of them.
"""
import itertools
import json
import signal
import logging
import os
import random
import sys
import warnings

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "LNN"))
sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "LTNtorch"))
import torch
from lnn import Model, Proposition, And as LAnd, Or as LOr, Not as LNot, Implies as LImp
from ltn import fuzzy_ops as F

SPECIAL = [0.0, 1e-9, 1e-5, 1e-4, 0.5, 1 - 1e-4, 1 - 1e-5, 1 - 1e-9, 1.0]
LTN = {"and": F.AndLuk(), "or": F.OrLuk(), "imp": F.ImpliesLuk(), "not": F.NotStandard()}
LNN = {"and": LAnd, "or": LOr, "imp": LImp, "not": LNot}


def gen(rng, names, depth):
    if depth == 0 or rng.random() < 0.25:
        return ("leaf", rng.choice(names))
    op = rng.choice(["and", "or", "imp", "not"])
    if op == "not":
        return ("not", gen(rng, names, depth - 1))
    return (op, gen(rng, names, depth - 1), gen(rng, names, depth - 1))


def ltn_eval(t, env):
    if t[0] == "leaf":
        return torch.tensor([env[t[1]]], dtype=torch.float32)
    if t[0] == "not":
        return LTN["not"](ltn_eval(t[1], env))
    return LTN[t[0]](ltn_eval(t[1], env), ltn_eval(t[2], env))


def lnn_build(t, props):
    if t[0] == "leaf":
        return props[t[1]]
    if t[0] == "not":
        return LNN["not"](lnn_build(t[1], props))
    return LNN[t[0]](lnn_build(t[1], props), lnn_build(t[2], props))


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def dup(t, seen=None):
    """True when the tree contains two structurally identical non-leaf sub-trees (separate objects in the LNN build)."""
    seen = set() if seen is None else seen
    found = [False]

    def walk(x):
        if x[0] == "leaf":
            return x[1]
        key = "(" + x[0] + " " + " ".join(walk(c) for c in x[1:]) + ")"
        if key in seen:
            found[0] = True
        seen.add(key)
        return key
    walk(t)
    return found[0]


def main(n=400, seed=0):
    rng = random.Random(seed)
    names = ["a", "b", "c"]
    stats = {"distinct": [0, 0], "duplicate": [0, 0]}      # [agree, differ]
    hangs = 0
    examples = []
    for _ in range(n):
        tree = gen(rng, names, rng.randint(1, 3))
        if tree[0] == "leaf":
            continue
        env = {k: (rng.choice(SPECIAL) if rng.random() < 0.4 else rng.random()) for k in names}
        used = {x for x in _leaves(tree)}
        props = {k: Proposition(k) for k in used}
        kind = "duplicate" if dup(tree) else "distinct"
        try:
            signal.setitimer(signal.ITIMER_REAL, 5)
            root = lnn_build(tree, props)
            m = Model(); m.add_knowledge(root)
            m.add_data({props[k]: (env[k], env[k]) for k in used})
            m.infer()
            lo, up = (float(v) for v in root.get_data())
        except Timeout:
            hangs += 1
            stats[kind][1] += 1
            continue
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        ref = float(ltn_eval(tree, env))
        d = max(abs(lo - ref), abs(up - ref))
        if d <= 5e-6:
            stats[kind][0] += 1
        else:
            stats[kind][1] += 1
            if len(examples) < 5:
                examples.append({"kind": kind, "tree": str(tree), "env": env, "lnn": (lo, up), "ltn": ref, "diff": d})
    ok = sum(v[0] for v in stats.values()); bad = sum(v[1] for v in stats.values())
    print(f"seed {seed}: LTN vs LNN on {ok + bad} random Lukasiewicz formulas: {ok} agree, {bad} differ ({hangs} of the differences are LNN hangs)")
    print("   formulas without repeated sub-formulas: %d agree / %d differ;  with a repeated sub-formula: %d agree / %d differ" % (
        stats["distinct"][0], stats["distinct"][1], stats["duplicate"][0], stats["duplicate"][1]))
    for e in examples:
        print("  ", json.dumps(e, default=str)[:400])
    return stats


def _leaves(t):
    if t[0] == "leaf":
        yield t[1]
    else:
        for c in t[1:]:
            yield from _leaves(c)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400, int(sys.argv[2]) if len(sys.argv) > 2 else 0)
