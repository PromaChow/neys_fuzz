"""ProbFuzz-style intermediate language (IL) for neurosymbolic programs.

A template is a small text file in which the *holes* (??NAME(args)) stand for the choices ProbFuzz leaves to its
generator: here they are the domain size, the number of probabilistic facts, the fact probabilities, the mutually
exclusive group sizes and their slack, and (for neural templates) the distribution a network emits.
Completing the holes yields a framework-independent `Prog` (reused from ../fuzz/nesy_prog.py) or a `NeuralCase`;
backends.py then translates that object to Scallop, DeepProbLog, ProbLog and NeurASP.

Template syntax (one directive per line, '#' starts a comment):
    template: <name>
    domain:   ??DOM(lo,hi)
    fact  <rel>/<arity> : ??FACTS(lo,hi)        independent probabilistic facts, probabilities from ??P
    group <rel>/<arity> : ??GROUP(lo,hi)        one mutually exclusive group (annotated disjunction), sum = 1 - ??SLACK
    idb   <rel>/<arity>
    rule  <head> :- <atom>, ..., not <atom>.    variables are upper-case
    neural: ??NN(classes_lo,classes_hi,inputs)  neural template: `inputs` categorical variables, query = their sum
"""
import os
import random
import re
import sys
from dataclasses import dataclass
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "fuzz"))
from nesy_prog import Prog, Rule, Atom  # noqa: E402

# Special values. ProbFuzz defined these (0, 1, epsilon, tiny) but its generator never enabled them; here the
# `special` rate is an explicit knob, 0.0 reproduces the ordinary-values baseline.
SPECIAL_P = [0.0, 1.0, 1e-12, 1e-9, 1e-6, 1.19e-7, 1e-5, 1.0 - 1e-5, 1.0 - 1e-9, 0.5]
SPECIAL_SLACK = [0.0, 1e-12, 1e-9, 1e-6, 0.1, 0.5]


def hole_p(rng: random.Random, special: float) -> float:
    if rng.random() < special:
        return rng.choice(SPECIAL_P)
    return round(rng.random(), 4)


@dataclass
class NeuralCase:
    n: int                      # classes
    probs: List[List[float]]    # one categorical distribution per input
    kinds: List[str]            # which hole option produced each row

    def to_text(self):
        return "\n".join(f"input{i} ({k}): {p}" for i, (k, p) in enumerate(zip(self.kinds, self.probs)))


def _atom(s: str) -> Atom:
    m = re.fullmatch(r"\s*(\w+)\s*\(([^)]*)\)\s*", s)
    if not m:
        raise ValueError(f"bad atom: {s!r}")
    return Atom(m.group(1), tuple(v.strip().lower() for v in m.group(2).split(",")))


def _split_body(body: str) -> List[str]:
    parts, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def _hole(spec: str, name: str):
    m = re.fullmatch(rf"\s*\?\?{name}\(([^)]*)\)\s*", spec)
    if not m:
        raise ValueError(f"expected ??{name}(...), got {spec!r}")
    return [int(x) for x in m.group(1).split(",") if x.strip()]


def load(path: str) -> dict:
    d = {"name": os.path.basename(path), "domain": None, "facts": [], "groups": [], "idb": {}, "rules": [], "neural": None}
    for raw in open(path):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        if line.startswith("template:"):
            d["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("domain:"):
            d["domain"] = _hole(line.split(":", 1)[1], "DOM")
        elif line.startswith("neural:"):
            d["neural"] = _hole(line.split(":", 1)[1], "NN")
        elif line.startswith(("fact", "group")):
            kind, rest = line.split(None, 1)
            decl, hole = rest.split(":", 1)
            rel, ar = decl.strip().split("/")
            d["facts" if kind == "fact" else "groups"].append((rel, int(ar), _hole(hole, "FACTS" if kind == "fact" else "GROUP")))
        elif line.startswith("idb"):
            rel, ar = line[3:].strip().split("/")
            d["idb"][rel] = int(ar)
        elif line.startswith("rule"):
            head, _, body = line[4:].strip().rstrip(".").partition(":-")
            pos, neg = [], []
            for part in _split_body(body):
                part = part.strip()
                (neg if part.startswith("not ") else pos).append(_atom(part[4:] if part.startswith("not ") else part))
            d["rules"].append(Rule(_atom(head), tuple(pos), tuple(neg)))
        else:
            raise ValueError(f"unknown directive: {line!r}")
    return d


def fill(tmpl: dict, rng: random.Random, special: float):
    """Complete the holes of a loaded template."""
    if tmpl["neural"]:
        return fill_neural(tmpl, rng, special)
    lo, hi = tmpl["domain"]
    dom = rng.randint(lo, hi)
    edb, facts, groups = {}, [], []
    import itertools
    for rel, ar, (flo, fhi) in tmpl["facts"]:
        edb[rel] = ar
        cands = list(itertools.product(range(dom), repeat=ar))
        rng.shuffle(cands)
        for t in cands[:rng.randint(flo, min(fhi, len(cands)))]:
            facts.append((rel, t, hole_p(rng, special)))
    for rel, ar, (glo, ghi) in tmpl["groups"]:
        edb[rel] = ar
        cands = list(itertools.product(range(dom), repeat=ar))
        rng.shuffle(cands)
        members = cands[:rng.randint(glo, min(ghi, len(cands)))]
        slack = rng.choice(SPECIAL_SLACK) if rng.random() < special else rng.random() * 0.5
        raw = [rng.random() + 0.05 for _ in members]
        if rng.random() < special:
            raw[rng.randrange(len(raw))] = 0.0                      # zero-probability member
        tot = sum(raw) or 1.0
        idxs = []
        for t, x in zip(members, raw):
            idxs.append(len(facts))
            facts.append((rel, t, x / tot * (1.0 - slack)))        # sum <= 1 up to rounding
        # guard float rounding: never exceed 1 by more than the oracle tolerates
        s = sum(facts[i][2] for i in idxs)
        if s > 1.0:
            for i in idxs:
                r, t, p = facts[i]
                facts[i] = (r, t, p / s)
        groups.append(idxs)
    return Prog(dom, edb, dict(tmpl["idb"]), facts, groups, list(tmpl["rules"]))


NN_KINDS = ["uniform", "random", "peaked", "one-hot", "near-one-hot", "zero-tail", "tiny-tail"]


def fill_neural(tmpl: dict, rng: random.Random, special: float) -> NeuralCase:
    clo, chi, k = tmpl["neural"]
    n = rng.randint(clo, chi)
    rows, kinds = [], []
    ordinary = ["uniform", "random", "peaked"]
    for _ in range(k):
        kind = rng.choice(NN_KINDS) if rng.random() < special else rng.choice(ordinary)
        hot = rng.randrange(n)
        if kind == "uniform":
            p = [1.0 / n] * n
        elif kind == "random":
            r = [rng.random() + 0.01 for _ in range(n)]
            p = [x / sum(r) for x in r]
        elif kind == "peaked":
            p = [0.1 / (n - 1)] * n
            p[hot] = 0.9
        elif kind == "one-hot":
            p = [0.0] * n
            p[hot] = 1.0
        elif kind == "near-one-hot":
            eps = rng.choice([1e-7, 1e-9, 1e-12])
            p = [eps / (n - 1)] * n
            p[hot] = 1.0 - eps
        elif kind == "zero-tail":
            p = [0.0] * n
            a, b = rng.sample(range(n), 2)
            p[a], p[b] = 0.5, 0.5
        else:  # tiny-tail
            p = [1e-30] * n
            p[hot] = 1.0 - 1e-30 * (n - 1)
        rows.append(p)
        kinds.append(kind)
    return NeuralCase(n, rows, kinds)
