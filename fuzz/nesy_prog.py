"""Framework-independent probabilistic-logic program model.

A Prog is a small Datalog program over integer constants with independent
probabilistic facts and optional mutually exclusive groups (annotated
disjunctions). exact_probs() is the oracle: it enumerates all possible worlds
(the distribution semantics) and sums the probability of the worlds in which
each derived tuple holds.
"""
import itertools
import random
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

BOUNDARY_PROBS = [0.0, 1.0, 1e-9, 1.0 - 1e-9, 1e-5, 0.99999, 0.5]


@dataclass(frozen=True)
class Atom:
    rel: str
    vars: Tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    head: Atom
    pos: Tuple[Atom, ...]
    neg: Tuple[Atom, ...] = ()


@dataclass
class Prog:
    d: int                                   # domain is {0..d-1}
    edb: Dict[str, int]                      # relation -> arity
    idb: Dict[str, int]
    facts: List[Tuple[str, Tuple[int, ...], float]]
    groups: List[List[int]] = field(default_factory=list)   # indices into facts, mutually exclusive
    rules: List[Rule] = field(default_factory=list)

    # -- helpers -----------------------------------------------------------
    def monotone(self) -> bool:
        return all(not r.neg for r in self.rules)

    def is_cyclic(self) -> bool:
        deps = {r: set() for r in self.idb}
        for rule in self.rules:
            for a in rule.pos + rule.neg:
                if a.rel in self.idb:
                    deps[rule.head.rel].add(a.rel)
        state = {}
        def dfs(n):
            state[n] = 1
            for m in deps[n]:
                if state.get(m) == 1 or (m not in state and dfs(m)):
                    return True
            state[n] = 2
            return False
        return any(n not in state and dfs(n) for n in deps)

    def grouped(self):
        return {i for g in self.groups for i in g}

    def possible_tuples(self, rel):
        arity = self.idb[rel]
        return list(itertools.product(range(self.d), repeat=arity))

    def to_text(self) -> str:
        lines = [f"domain 0..{self.d - 1}"]
        for i, (r, t, p) in enumerate(self.facts):
            g = [k for k, grp in enumerate(self.groups) if i in grp]
            lines.append(f"{p!r}::{r}{t}" + (f"  [group {g[0]}]" if g else ""))
        for r in self.rules:
            body = [f"{a.rel}({','.join(a.vars)})" for a in r.pos] + \
                   [f"not {a.rel}({','.join(a.vars)})" for a in r.neg]
            lines.append(f"{r.head.rel}({','.join(r.head.vars)}) :- {', '.join(body)}")
        return "\n".join(lines)


# -- exact semantics ------------------------------------------------------
def _eval_world(prog: Prog, world_facts) -> Dict[str, set]:
    """Least fixpoint of the rules in one deterministic world."""
    db: Dict[str, set] = {r: set() for r in list(prog.edb) + list(prog.idb)}
    for (rel, tup) in world_facts:
        db[rel].add(tup)
    changed = True
    while changed:
        changed = False
        for rule in prog.rules:
            vs = sorted({v for a in rule.pos + rule.neg + (rule.head,) for v in a.vars})
            for vals in itertools.product(range(prog.d), repeat=len(vs)):
                env = dict(zip(vs, vals))
                ok = all(tuple(env[v] for v in a.vars) in db[a.rel] for a in rule.pos)
                if ok:
                    ok = all(tuple(env[v] for v in a.vars) not in db[a.rel] for a in rule.neg)
                if ok:
                    t = tuple(env[v] for v in rule.head.vars)
                    if t not in db[rule.head.rel]:
                        db[rule.head.rel].add(t)
                        changed = True
    return db


def exact_probs(prog: Prog, override: Optional[Dict[int, float]] = None) -> Dict[str, Dict[tuple, float]]:
    """P(tuple in IDB relation) for every possible tuple, by world enumeration."""
    override = override or {}
    probs = [override.get(i, f[2]) for i, f in enumerate(prog.facts)]
    in_group = prog.grouped()
    indep = [i for i in range(len(prog.facts)) if i not in in_group]

    # units: each independent fact -> choices [(False,1-p),(True,p)]
    #        each group           -> choices [(none, rest), (fact_j, p_j) ...]
    units = []
    for i in indep:
        units.append([((), 1.0 - probs[i]), ((i,), probs[i])])
    for g in prog.groups:
        total = sum(probs[i] for i in g)
        assert total <= 1.0 + 1e-12, f"invalid group: probabilities sum to {total}"
        units.append([((), max(1.0 - total, 0.0))] + [((i,), probs[i]) for i in g])

    out = {r: {t: 0.0 for t in prog.possible_tuples(r)} for r in prog.idb}
    for combo in itertools.product(*units):
        w = 1.0
        chosen = []
        for (ids, pr) in combo:
            w *= pr
            chosen.extend(ids)
        if w == 0.0:
            continue
        db = _eval_world(prog, [(prog.facts[i][0], prog.facts[i][1]) for i in chosen])
        for r in prog.idb:
            for t in db[r]:
                out[r][t] += w
    return out


def exact_grads(prog: Prog) -> Dict[int, Dict[str, Dict[tuple, float]]]:
    """d P(tuple) / d p_i for independent facts. P is multilinear in each p_i, so
    the derivative is exactly P(. | f_i true) - P(. | f_i false)."""
    g = {}
    in_group = prog.grouped()
    for i in range(len(prog.facts)):
        if i in in_group:
            continue
        hi = exact_probs(prog, {i: 1.0})
        lo = exact_probs(prog, {i: 0.0})
        g[i] = {r: {t: hi[r][t] - lo[r][t] for t in hi[r]} for r in hi}
    return g


# -- random generation -----------------------------------------------------
def _sample_prob(rng: random.Random, boundary_rate: float) -> float:
    if rng.random() < boundary_rate:
        return rng.choice(BOUNDARY_PROBS)
    return round(rng.random(), 4)


def gen_prog(rng: random.Random, *, allow_neg=False, allow_groups=False,
             boundary_rate=0.3, max_facts=8) -> Prog:
    d = rng.choice([2, 3])
    n_edb = rng.randint(1, 3)
    edb = {f"a{i}": rng.choice([1, 2]) for i in range(n_edb)}
    n_idb = rng.randint(1, 2)
    idb = {f"r{i}": rng.choice([1, 2]) for i in range(n_idb)}

    # facts
    cands = [(r, t) for r, ar in edb.items() for t in itertools.product(range(d), repeat=ar)]
    rng.shuffle(cands)
    nf = rng.randint(2, min(max_facts, len(cands)))
    facts = [(r, t, _sample_prob(rng, boundary_rate)) for (r, t) in cands[:nf]]

    groups: List[List[int]] = []
    if allow_groups and nf >= 3 and rng.random() < 0.6:
        # one group over 2-3 facts of one relation; renormalise to sum <= 1
        by_rel: Dict[str, List[int]] = {}
        for i, (r, _, _) in enumerate(facts):
            by_rel.setdefault(r, []).append(i)
        rel_opts = [v for v in by_rel.values() if len(v) >= 2]
        if rel_opts:
            idxs = rng.choice(rel_opts)[:3]
            raw = [rng.random() + 0.05 for _ in idxs]
            total = sum(raw) + (rng.random() if rng.random() < 0.5 else 0.0)
            for i, x in zip(idxs, raw):
                r, t, _ = facts[i]
                # floor (not round) so the group's probabilities can never sum above 1
                facts[i] = (r, t, int(x / total * 10000) / 10000.0)
            groups.append(idxs)

    # rules
    rels = {**edb, **idb}
    var_pool = ["x", "y", "z", "w"]
    rules: List[Rule] = []
    for h, har in idb.items():
        for _ in range(rng.randint(1, 3)):
            nb = rng.randint(1, 3)
            pos = []
            for _ in range(nb):
                r = rng.choice(list(rels))
                pos.append(Atom(r, tuple(rng.choice(var_pool[:3]) for _ in range(rels[r]))))
            bound = sorted({v for a in pos for v in a.vars})
            head_vars = tuple(rng.choice(bound) for _ in range(har))
            neg = ()
            if allow_neg and rng.random() < 0.4:
                r = rng.choice(list(edb))
                neg = (Atom(r, tuple(rng.choice(bound) for _ in range(edb[r]))),)
            rules.append(Rule(Atom(h, head_vars), tuple(pos), neg))
    return Prog(d, edb, idb, facts, groups, rules)


# -- shrinking ------------------------------------------------------------
def shrink(prog: Prog, still_fails) -> Prog:
    """Greedy delta-debugging: drop rules, facts, and body atoms while still_fails."""
    cur = prog
    progress = True
    while progress:
        progress = False
        for i in range(len(cur.rules)):
            cand = replace(cur, rules=cur.rules[:i] + cur.rules[i + 1:])
            if cand.rules and still_fails(cand):
                cur, progress = cand, True
                break
        if progress:
            continue
        gset = cur.grouped()
        for i in range(len(cur.facts)):
            if i in gset:
                continue
            facts = cur.facts[:i] + cur.facts[i + 1:]
            groups = [[j - (j > i) for j in g] for g in cur.groups]
            cand = replace(cur, facts=facts, groups=groups)
            if still_fails(cand):
                cur, progress = cand, True
                break
        if progress:
            continue
        for ri, r in enumerate(cur.rules):
            for bi in range(len(r.pos)):
                if len(r.pos) == 1:
                    continue
                npos = r.pos[:bi] + r.pos[bi + 1:]
                if not set(r.head.vars) <= {v for a in npos for v in a.vars}:
                    continue
                if any(not set(a.vars) <= {v for p in npos for v in p.vars} for a in r.neg):
                    continue
                nr = Rule(r.head, npos, r.neg)
                cand = replace(cur, rules=cur.rules[:ri] + [nr] + cur.rules[ri + 1:])
                if still_fails(cand):
                    cur, progress = cand, True
                    break
            if progress:
                break
    return cur
