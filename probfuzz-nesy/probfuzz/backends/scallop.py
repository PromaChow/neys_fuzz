from backends.backend import NesyBackend


class Scallop(NesyBackend):
    tool = 'scallop'

    def emit(self):
        wmc = self.algorithm == 'wmcdisj'
        by_rel, groups = {}, {}
        for rel, t, p, g in self.facts():
            by_rel.setdefault(rel, []).append((p, t, g))
        lines = ["import itertools, warnings",
                 "warnings.filterwarnings('ignore')",
                 "import scallopy",
                 "D = %d" % self.domain(),
                 "ctx = scallopy.ScallopContext(provenance='topkproofs', k=300, wmc_with_disjunctions=%s)" % wmc]
        for rel, ar in self.edb_arity().items():
            lines.append("ctx.add_relation(%r, (%s))" % (rel, "int, " * ar))
        for rel, facts in by_rel.items():
            elems = [(p, t) for p, t, _ in facts]
            disj = {}
            for j, (_, _, g) in enumerate(facts):
                if g is not None:
                    disj.setdefault(g, []).append(j)
            lines.append("ctx.add_facts(%r, %r, disjunctions=%r)" % (rel, elems, list(disj.values()) or None))
        for head, hv, pos, neg in self.rules:
            body = ["%s(%s)" % (r, ",".join(v)) for r, v in pos] + ["not %s(%s)" % (r, ",".join(v)) for r, v in neg]
            lines.append("ctx.add_rule(%r)" % ("%s(%s) = %s" % (head, ",".join(hv), ", ".join(body))))
        lines.append("ctx.run()")
        lines.append("OUT = {rel: {tuple(t): p for (p, t) in ctx.relation(rel)} for rel, _ in %r}" % self.query_tuples())
        lines.append("RES = lambda rel, t: OUT[rel].get(t)")
        return "\n".join(lines) + "\n" + self.printer(repr(self.query_tuples()))
