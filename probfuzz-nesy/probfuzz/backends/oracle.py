import os
from backends.backend import NesyBackend

FUZZ_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'fuzz'))


class Oracle(NesyBackend):
    """Not a system under test: exact possible-worlds semantics (fuzz/nesy_prog.py), the reference for the SMAPE metric.
    ProbFuzz compared systems with each other; an exact reference exists here because programs are small and discrete."""
    tool = 'oracle'

    def emit(self):
        facts = self.facts()
        groups = {}
        for i, (_, _, _, g) in enumerate(facts):
            if g is not None:
                groups.setdefault(g, []).append(i)
        rules = [(h, hv, pos, neg) for h, hv, pos, neg in self.rules]
        idb = self.idb_arity()
        return ("import itertools, sys\nsys.path.insert(0, %r)\n"
                "from nesy_prog import Prog, Rule, Atom, exact_probs\n"
                "D = %d\nFACTS = %r\nGROUPS = %r\nRULES = %r\nIDB = %r\nEDB = %r\n"
                "prog = Prog(D, EDB, IDB, [(r, tuple(t), p) for r, t, p, g in FACTS], [list(v) for v in GROUPS.values()],\n"
                "            [Rule(Atom(h, tuple(hv)), tuple(Atom(r, tuple(v)) for r, v in pos), tuple(Atom(r, tuple(v)) for r, v in neg))\n"
                "             for h, hv, pos, neg in RULES])\n"
                "EX = exact_probs(prog)\n"
                "def RES(rel, t):\n"
                "    return EX[rel][t] if rel in EX else None\n"
                % (FUZZ_DIR, self.domain(), facts, groups, rules, idb, self.edb_arity())) + self.printer(repr(self.query_tuples()))
