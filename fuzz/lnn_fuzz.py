"""Property-based fuzzing of IBM's Logical Neural Networks (LNN) against closed-form and classical-logic oracles.

LNN stores a truth *interval* [lower, upper] in [0,1] per node and runs upward/downward inference with weighted
Lukasiewicz neurons (default: weights 1, bias 1 = plain Lukasiewicz logic). Oracles used here:
  upward_*    interval Lukasiewicz arithmetic (exact for monotone connectives)
  classical   with every leaf TRUE/FALSE the result must be the classical truth value of every node
  sound_*     with partial knowledge / asserted formulas, derived bounds must contain the truth value of the node in
              every classical world consistent with the knowledge (soundness); inconsistent knowledge must be flagged
  fol_*       first-order formulas over a small domain against brute-force classical semantics
  term_*      termination: infer() must return (a signal alarm turns an endless inference into a finding)
  input_*     invalid bounds / values: clean error vs crash vs silent acceptance
  order_*     invariance to the order in which knowledge/data are added, to repeated inference and to flush()
"""
import argparse
import itertools
import json
import math
import os
import random
import signal
import sys
import warnings

import logging
logging.disable(logging.CRITICAL)           # LNN logs every inference step; an alarm inside a log call would only add noise
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "LNN"))
import numpy as np
import torch
from lnn import Model, Proposition, And, Or, Not, Implies, Iff, XOr, Fact, World, Variable, Exists, Forall, Predicate

OUT = os.path.join(HERE, "..", "results", "lnn_fuzz.jsonl")
FINDINGS, COUNTS = [], {}
TOL = 2e-6
SPECIAL = [0.0, 1e-12, 1e-9, 1e-7, 1e-5, 0.5, 1 - 1e-5, 1 - 1e-7, 1 - 1e-9, 1.0]


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def with_timeout(seconds, fn):
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def rec(prop, ok, detail="", **kw):
    c = COUNTS.setdefault(prop, [0, 0])
    c[0 if ok else 1] += 1
    if not ok and c[1] <= 5:
        FINDINGS.append({"prop": prop, "detail": detail, **kw})


def val(rng):
    return rng.choice(SPECIAL) if rng.random() < 0.4 else rng.random()


def bounds(rng):
    a, b = val(rng), val(rng)
    return (min(a, b), max(a, b)) if rng.random() < 0.5 else (a, a)


def run(prop, fn):
    try:
        return with_timeout(10, fn)
    except Timeout:
        rec(prop + ":hang", False, "no result after 10 s")
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        rec(prop + ":exception", False, f"{type(e).__name__}: {str(e)[:200]}")


def node_bounds(node):
    d = node.get_data()
    return float(d[0]), float(d[1])


# ============================================================ L1 upward semantics (interval Lukasiewicz)
def o_and(bs):
    return (max(0.0, sum(l for l, u in bs) - (len(bs) - 1)), max(0.0, sum(u for l, u in bs) - (len(bs) - 1)))


def o_or(bs):
    return (min(1.0, sum(l for l, u in bs)), min(1.0, sum(u for l, u in bs)))


def o_not(b):
    return (1 - b[1], 1 - b[0])


def o_imp(a, b):
    return (min(1.0, 1 - a[1] + b[0]), min(1.0, 1 - a[0] + b[1]))


def upward_props(rng, n):
    for _ in range(n):
        k = rng.randint(2, 5)
        bs = [bounds(rng) for _ in range(k)]
        for name, ctor, ref in (("And", And, lambda b: o_and(b)), ("Or", Or, lambda b: o_or(b))):
            def case(name=name, ctor=ctor, ref=ref):
                ps = [Proposition(f"p{i}") for i in range(k)]
                f = ctor(*ps)
                m = Model(); m.add_knowledge(f)
                m.add_data({p: b for p, b in zip(ps, bs)})
                f.upward()
                got = node_bounds(f)
                want = ref(bs)
                d = max(abs(got[0] - want[0]), abs(got[1] - want[1]))
                rec(f"upward_{name}_n_ary", d <= TOL, f"k={k} inputs={bs} got={got} want={want}", inputs=bs, got=got, want=want)
                rec(f"upward_{name}_bounds_ordered", got[0] <= got[1] + 1e-7, f"lower {got[0]} > upper {got[1]}", inputs=bs)
            run("upward_" + name, case)
        a, b = bounds(rng), bounds(rng)

        def unary():
            A = Proposition("A"); N = Not(A)
            m = Model(); m.add_knowledge(N); m.add_data({A: a}); N.upward()
            got = node_bounds(N); want = o_not(a)
            rec("upward_Not", max(abs(got[0] - want[0]), abs(got[1] - want[1])) <= TOL, f"in={a} got={got} want={want}")
        run("upward_Not", unary)

        def implies():
            A = Proposition("A"); B = Proposition("B"); I = Implies(A, B)
            m = Model(); m.add_knowledge(I); m.add_data({A: a, B: b}); I.upward()
            got = node_bounds(I); want = o_imp(a, b)
            rec("upward_Implies", max(abs(got[0] - want[0]), abs(got[1] - want[1])) <= TOL, f"A={a} B={b} got={got} want={want}", A=a, B=b, got=got, want=want)
        run("upward_Implies", implies)

        pa, pb = a[0], b[0]                                     # point values for the derived connectives

        def iff():
            A = Proposition("A"); B = Proposition("B"); I = Iff(A, B)
            m = Model(); m.add_knowledge(I); m.add_data({A: (pa, pa), B: (pb, pb)}); I.upward()
            got = node_bounds(I); want = 1 - abs(pa - pb)
            rec("upward_Iff_point", abs(got[0] - want) <= 5e-6 and abs(got[1] - want) <= 5e-6, f"A={pa} B={pb} got={got} want={want}", got=got, want=want)
        run("upward_Iff", iff)

        def xor():
            A = Proposition("A"); B = Proposition("B"); X = XOr(A, B)
            m = Model(); m.add_knowledge(X); m.add_data({A: (pa, pa), B: (pb, pb)}); X.upward()
            got = node_bounds(X); want = max(0.0, min(1.0, pa + pb) - max(0.0, pa + pb - 1))   # (A or B) and not (A and B)
            rec("upward_XOr_point", abs(got[0] - want) <= 5e-6 and abs(got[1] - want) <= 5e-6, f"A={pa} B={pb} got={got} want={want}", got=got, want=want)
        run("upward_XOr", xor)


# ============================================================ L2/L3/L4 classical completeness and soundness
def rand_formula(rng, props, depth):
    if depth == 0 or rng.random() < 0.3:
        return rng.choice(props)
    op = rng.choice(["and", "or", "not", "imp", "iff", "xor"])
    if op == "not":
        return ("not", rand_formula(rng, props, depth - 1))
    return (op, rand_formula(rng, props, depth - 1), rand_formula(rng, props, depth - 1))


def classical(f, world):
    if isinstance(f, Proposition):
        return world[f.name]
    op = f[0]
    if op == "not":
        return not classical(f[1], world)
    a, b = classical(f[1], world), classical(f[2], world)
    return {"and": a and b, "or": a or b, "imp": (not a) or b, "iff": a == b, "xor": a != b}[op]


def show(f):
    if isinstance(f, Proposition):
        return f.name
    return "(" + f[0] + " " + " ".join(show(c) for c in f[1:]) + ")"


def has_duplicate_subformula(f):
    """True when two different non-leaf sub-trees are structurally identical (LNN identifies formulas by structure)."""
    seen, dup = {}, [False]

    def walk(t):
        if isinstance(t, Proposition):
            return t.name
        key = "(" + t[0] + " " + " ".join(walk(c) for c in t[1:]) + ")"
        if key in seen:
            dup[0] = True
        seen[key] = True
        return key
    walk(f)
    return dup[0]


def used_names(f):
    if isinstance(f, Proposition):
        return {f.name}
    return set().union(*[used_names(c) for c in f[1:]])


def build(f):
    if isinstance(f, Proposition):
        return f
    op = f[0]
    if op == "not":
        return Not(build(f[1]))
    a, b = build(f[1]), build(f[2])
    return {"and": And, "or": Or, "imp": Implies, "iff": Iff, "xor": XOr}[op](a, b)


def nodes_of(f, acc):
    """(tree, built node) pairs for every sub-formula, children first."""
    if isinstance(f, Proposition):
        return f
    node = None
    kids = [nodes_of(c, acc) for c in f[1:]]
    op = f[0]
    node = Not(*kids) if op == "not" else {"and": And, "or": Or, "imp": Implies, "iff": Iff, "xor": XOr}[op](*kids)
    acc.append((f, node))
    return node


def classical_props(rng, n):
    for case in range(n):
        names = ["a", "b", "c", "d"][:rng.randint(2, 4)]
        props = [Proposition(x) for x in names]
        tree = rand_formula(rng, props, rng.randint(1, 3))
        if isinstance(tree, Proposition):
            continue

        def go():
            acc = []
            root = nodes_of(tree, acc)
            m = Model()
            m.add_knowledge(root)
            full = {x: rng.random() < 0.5 for x in names}
            m.add_data({p: (Fact.TRUE if full[p.name] else Fact.FALSE) for p in props if p.name in used_names(tree)})
            m.infer()
            for sub, node in acc:
                want = classical(sub, full)
                lo, up = node_bounds(node)
                ok = (abs(lo - float(want)) <= 1e-6 and abs(up - float(want)) <= 1e-6)
                dup = has_duplicate_subformula(tree)
                tag = "classical_complete_upward" + (":duplicate_subformula" if dup else ":distinct_subformulas")
                rec(tag, ok, f"world={full} formula={show(tree)} sub={show(sub)} node bounds=({lo},{up}) classical={want}", world=full, formula=show(tree))
                rec("classical_state" + (":duplicate_subformula" if dup else ":distinct_subformulas"), node.state() is (Fact.TRUE if want else Fact.FALSE), f"state={node.state()} classical={want} formula={show(tree)}", world=full)
        run("classical", go)


def sound_props(rng, n):
    """Partial knowledge + asserted formulas: derived bounds must hold in every consistent classical world."""
    for case in range(n):
        names = ["a", "b", "c"][:rng.randint(2, 3)]
        props = [Proposition(x) for x in names]
        tree = rand_formula(rng, props, rng.randint(1, 3))
        if isinstance(tree, Proposition):
            continue
        asserted = rng.random() < 0.7
        known = {x: rng.random() < 0.5 for x in names if rng.random() < 0.5}
        asserted_value = rng.random() < 0.5

        def go():
            acc = []
            root = nodes_of(tree, acc)
            m = Model(); m.add_knowledge(root)
            data = {p: (Fact.TRUE if known[p.name] else Fact.FALSE) for p in props if p.name in known and p.name in used_names(tree)}
            if asserted:
                data[root] = Fact.TRUE if asserted_value else Fact.FALSE
            m.add_data(data)
            m.infer()
            worlds = []
            for bits in itertools.product([False, True], repeat=len(names)):
                w = dict(zip(names, bits))
                if any(w[k] != v for k, v in known.items() if k in used_names(tree)):
                    continue
                if asserted and classical(tree, w) != asserted_value:
                    continue
                worlds.append(w)
            if not worlds:
                contra = any(float(node.get_data()[0]) > float(node.get_data()[1]) + 1e-7 for _, node in acc) or \
                    any(bool(node.is_contradiction()) for _, node in acc + [(None, p) for p in props if p.name in used_names(tree)])
                rec("sound_inconsistent_flagged", contra, "knowledge has no classical model but no node is flagged as a contradiction",
                    known=known, asserted=asserted_value, formula=show(tree))
                return
            for sub, node in acc + [(p, p) for p in props if p.name in used_names(tree)]:
                vals_ = {float(classical(sub, w)) for w in worlds}
                lo, up = node_bounds(node)
                ok = lo <= min(vals_) + 1e-6 and up >= max(vals_) - 1e-6
                rec("sound_bounds_contain_all_models", ok, f"bounds=({lo},{up}) but models give {sorted(vals_)}", known=known,
                    asserted=asserted_value if asserted else None, formula=show(tree))
                if len(vals_) == 1 and lo == 0.0 and up == 1.0:
                    rec("info_incomplete_inference", False, "entailed value left UNKNOWN (inference incompleteness, informational)")
        run("sound", go)


# ============================================================ L5 first-order vs brute-force classical semantics
def fol_props(rng, n):
    """Quantified formulas over three constants whose predicates are fully specified (every constant TRUE or FALSE).
    CLOSED-world predicates: the quantified value must be the classical one. OPEN-world predicates: the domain is not
    known to be complete, so Forall can only be refuted (FALSE) and Exists can only be proven (TRUE); anything else is UNKNOWN."""
    dom = ["a", "b", "c"]
    for case in range(n):
        world = rng.choice([World.OPEN, World.CLOSED])
        shape = rng.choice(["forall_P", "exists_P", "forall_imp", "exists_and", "forall_or_not"])
        facts = {c: rng.choice([True, False]) for c in dom}
        facts_q = {c: rng.choice([True, False]) for c in dom}
        use_query = rng.random() < 0.5

        def go():
            x = Variable("x")
            m = Model(); P = m.add_predicates(1, "P", world=world); Q = m.add_predicates(1, "Q", world=world)
            if shape == "forall_P":
                F = Forall(x, P(x)); vals_ = [facts[c] for c in dom]; kind = "forall"
            elif shape == "exists_P":
                F = Exists(x, P(x)); vals_ = [facts[c] for c in dom]; kind = "exists"
            elif shape == "forall_imp":
                F = Forall(x, Implies(P(x), Q(x))); vals_ = [(not facts[c]) or facts_q[c] for c in dom]; kind = "forall"
            elif shape == "exists_and":
                F = Exists(x, And(P(x), Q(x))); vals_ = [facts[c] and facts_q[c] for c in dom]; kind = "exists"
            else:
                F = Forall(x, Or(P(x), Not(Q(x)))); vals_ = [facts[c] or not facts_q[c] for c in dom]; kind = "forall"
            m.add_knowledge(F) if not use_query else m.set_query(F)
            m.add_data({P: {c: (Fact.TRUE if facts[c] else Fact.FALSE) for c in dom},
                        Q: {c: (Fact.TRUE if facts_q[c] else Fact.FALSE) for c in dom}})
            m.infer(max_steps=20)                    # bounded: termination is checked separately in term_props
            lo, up = node_bounds(F)
            if world is World.CLOSED:
                ref = all(vals_) if kind == "forall" else any(vals_)
                want = (float(ref), float(ref))
            elif kind == "forall":
                want = (0.0, 0.0) if not all(vals_) else (0.0, 1.0)
            else:
                want = (1.0, 1.0) if any(vals_) else (0.0, 1.0)
            ok = abs(lo - want[0]) <= 1e-6 and abs(up - want[1]) <= 1e-6
            informational = world is World.CLOSED
            # a CLOSED predicate world is not propagated to the quantifier/connective node, whose own (OPEN) world decides
            rec(f"{'info_world_not_propagated' if informational else 'fol_semantics'}:{world.name}:{shape}:{'query' if use_query else 'knowledge'}", ok,
                f"P={facts} Q={facts_q} bounds=({lo},{up}) expected={want}", P=facts, Q=facts_q, bounds=(lo, up), expected=want)
            rec("fol_bounds_ordered", lo <= up + 1e-7, f"lower {lo} > upper {up} (contradiction reported on consistent data)",
                world=world.name, shape=shape, P=facts, Q=facts_q)
        run("fol", go)


# ============================================================ L9 learning (parameters stay finite and in range)
def learn_props(rng, n):
    from lnn import Direction, Loss
    for case in range(n):
        k = rng.randint(2, 3)
        kind = rng.choice([And, Or])
        loss = rng.choice([Loss.CONTRADICTION, Loss.UNCERTAINTY])
        direction = rng.choice([None, Direction.UPWARD, Direction.DOWNWARD])
        facts = [rng.choice([Fact.TRUE, Fact.FALSE, bounds(rng)]) for _ in range(k)]

        def go():
            ps = [Proposition(f"p{i}") for i in range(k)]
            f = kind(*ps, world=World.AXIOM)
            m = Model(); m.add_knowledge(f); m.add_data({p: v for p, v in zip(ps, facts)})
            kw = {"losses": {loss: 1}}
            if direction is not None:
                kw["direction"] = direction
            m.train(**kw)
            w = f.params("weights"); b = f.params("bias")
            finite = bool(torch.isfinite(w).all() and torch.isfinite(b).all())
            rec("learn_params_finite", finite, f"{kind.__name__} k={k} facts={facts} loss={loss.name} dir={direction}: weights={w.tolist()} bias={float(b)}")
            wmax = getattr(f.neuron, "w_max", None)
            wmax = float("inf") if wmax is None else float(wmax)      # the library clamps weights to [0, w_max] (no upper limit if unset)
            rec("learn_weights_in_range", bool(((w >= -1e-6) & (w <= wmax + 1e-6)).all()), f"weights {w.tolist()} outside [0,{wmax}]", facts=str(facts), loss=loss.name)
            rec("learn_bias_in_range", bool(-1e-6 <= float(b) <= 1 + 1e-6), f"bias {float(b)} outside [0,1]", facts=str(facts), loss=loss.name)
            lo_up = [node_bounds(p) for p in ps]
            rec("learn_bounds_valid", all(0 <= l <= u <= 1 for l, u in lo_up) or any(l > u for l, u in lo_up), f"bounds after training {lo_up}")
        run("learn", go)


# ============================================================ L8 termination
def term_props():
    x = Variable("x")
    for quant, qname in ((Exists, "Exists"), (Forall, "Forall")):
        for world in (World.OPEN, World.CLOSED):
            for pattern, facts in (("all_true", {"a": Fact.TRUE, "b": Fact.TRUE}), ("one_false", {"a": Fact.TRUE, "b": Fact.FALSE}),
                                   ("all_false", {"a": Fact.FALSE, "b": Fact.FALSE}), ("bounds", {"a": (0.2, 0.7), "b": Fact.TRUE})):
                for how in ("add_knowledge", "set_query"):
                    def go():
                        m = Model(); P = m.add_predicates(1, "P")
                        F = quant(x, P(x), world=world)
                        m.add_knowledge(F) if how == "add_knowledge" else m.set_query(F)
                        m.add_data({P: facts})
                        m.infer()
                        rec(f"term_infer_returns:{how}", True)
                    try:
                        with_timeout(6, go)
                    except Timeout:
                        rec(f"term_infer_returns:{how}", False, f"{qname} world={world.name} data={pattern}: infer() did not return within 6 s",
                            quantifier=qname, world=world.name, data=pattern, how=how)
                    except BaseException as e:
                        rec(f"term_infer_returns:{how}", True)


# ============================================================ L6 invalid inputs
def input_props():
    def tryit(label, fn, accept_is_bad=True):
        try:
            fn()
            rec("input_invalid_rejected", not accept_is_bad, f"{label}: accepted silently")
        except BaseException as e:
            rec("input_invalid_rejected", True)
            if not isinstance(e, (ValueError, TypeError, AttributeError, AssertionError, KeyError)):
                rec("input_clean_error_type", False, f"{label}: {type(e).__name__}: {str(e)[:100]}")
    for label, bad in (("lower above upper", (0.8, 0.2)), ("negative lower", (-0.1, 0.5)), ("upper above one", (0.2, 1.5)),
                       ("NaN", (float("nan"), float("nan"))), ("inf", (0.0, float("inf"))), ("string", ("x", "y"))):
        def go(bad=bad):
            A = Proposition("A"); m = Model(); m.add_knowledge(A); m.add_data({A: bad}); m.infer()
            lo, up = node_bounds(A)
            if not (0 <= lo <= up <= 1):
                raise ValueError(f"stored bounds ({lo}, {up})")
        tryit(label, go)
    def unknown_node():
        A = Proposition("A"); B = Proposition("B"); m = Model(); m.add_knowledge(A); m.add_data({B: Fact.TRUE})
    tryit("data for a node that is not in the model", unknown_node)
    def empty_and():
        And()
    tryit("And() with no operands", empty_and)
    def single_and():
        A = Proposition("A"); f = And(A); m = Model(); m.add_knowledge(f); m.add_data({A: Fact.TRUE}); m.infer()
        rec("input_unary_and_value", node_bounds(f) == (1.0, 1.0), f"And(A) with A TRUE has bounds {node_bounds(f)}")
    run("input_single_and", single_and)
    def dup_name():
        A1, A2 = Proposition("A"), Proposition("A"); m = Model(); m.add_knowledge(And(A1, A2))
    tryit("two propositions with the same name", dup_name)


# ============================================================ L7 invariance
def order_props(rng, n):
    for case in range(n):
        names = ["a", "b", "c"]
        props = [Proposition(x) for x in names]
        tree = rand_formula(rng, props, 2)
        if isinstance(tree, Proposition):
            continue
        known = {x: rng.random() < 0.5 for x in names if rng.random() < 0.6}
        val_ = rng.random() < 0.5

        def once(reverse, twice, reflush):
            props = [Proposition(x) for x in names]
            t = rebuild(tree, {p.name: p for p in props})
            acc = []; root = nodes_of(t, acc)
            m = Model(); m.add_knowledge(root)
            items = list({p: (Fact.TRUE if known[p.name] else Fact.FALSE) for p in props if p.name in known and p.name in used_names(tree)}.items()) + [(root, Fact.TRUE if val_ else Fact.FALSE)]
            if reverse:
                items = items[::-1]
            if reflush:
                m.add_data(dict(items)); m.infer(); m.flush()
            m.add_data(dict(items))
            m.infer()
            if twice:
                m.infer()
            return [node_bounds(node) for _, node in acc] + [node_bounds(p) for p in props if p.name in used_names(tree)]

        def go():
            base = once(False, False, False)
            for label, args in (("data_order", (True, False, False)), ("repeated_infer", (False, True, False)), ("flush_reload", (False, False, True))):
                other = once(*args)
                ok = all(abs(a[0] - b[0]) <= 1e-6 and abs(a[1] - b[1]) <= 1e-6 for a, b in zip(base, other))
                rec(f"order_{label}", ok, f"bounds differ: {base} vs {other}", formula=show(tree), known=known)
        run("order", go)


def rebuild(tree, byname):
    if isinstance(tree, Proposition):
        return byname[tree.name]
    return (tree[0],) + tuple(rebuild(c, byname) for c in tree[1:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--groups", default="upward,classical,sound,fol,term,input,order,learn")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    g = set(a.groups.split(","))
    if "upward" in g: upward_props(rng, a.n)
    if "classical" in g: classical_props(rng, a.n)
    if "sound" in g: sound_props(rng, a.n)
    if "fol" in g: fol_props(rng, max(10, a.n // 2))
    if "term" in g: term_props()
    if "input" in g: input_props()
    if "order" in g: order_props(rng, a.n // 2)
    if "learn" in g: learn_props(rng, a.n // 2)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        for r in FINDINGS:
            f.write(json.dumps(r, default=str) + "\n")
        f.write(json.dumps({"summary": {k: {"ok": v[0], "fail": v[1]} for k, v in sorted(COUNTS.items())}, "seed": a.seed, "n": a.n}) + "\n")
    bad = {k: v for k, v in sorted(COUNTS.items()) if v[1]}
    total = sum(v[0] + v[1] for v in COUNTS.values())
    print(f"{total} checks, {len(COUNTS)} properties, {len(bad)} with a failure")
    for k, v in bad.items():
        print(f"  {k:62s} fail {v[1]:5d} / {v[0] + v[1]:5d}")
    print("results ->", a.out)


if __name__ == "__main__":
    main()
