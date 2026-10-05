import os
from backends.backend import NesyBackend

NEURASP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frameworks', 'NeurASP'))


class NeurASP(NesyBackend):
    tool = 'neurasp'

    def mvpp_text(self):
        """Each independent fact is a two-valued MVPP variable, each categorical one multi-valued variable (+ 'none');
        padded with probability-0 values so that all variables have the same number of values."""
        facts = self.facts()
        groups = {}
        for i, (rel, t, p, g) in enumerate(facts):
            if g is not None:
                groups.setdefault(g, []).append(i)
        L = max([2] + [len(m) + 1 for m in groups.values()])
        lines = []
        for i, (rel, t, p, g) in enumerate(facts):
            if g is None:
                alts = ["%r f(0,%d,1)" % (p, i), "%r f(0,%d,0)" % (1.0 - p, i)] + ["0.0 f(0,%d,%d)" % (i, v) for v in range(2, L)]
                lines.append(" ; ".join(alts) + ".")
        for g, members in groups.items():
            total = sum(facts[i][2] for i in members)
            alts = ["%r g(0,%d,%d)" % (facts[i][2], g, j + 1) for j, i in enumerate(members)]
            alts.append("%r g(0,%d,0)" % (max(1.0 - total, 0.0), g))
            alts += ["0.0 g(0,%d,%d)" % (g, v) for v in range(len(members) + 1, L)]
            lines.append(" ; ".join(alts) + ".")
        for i, (rel, t, p, g) in enumerate(facts):
            args = ",".join(map(str, t))
            if g is None:
                lines.append("%s(%s) :- f(0,%d,1)." % (rel, args, i))
            else:
                lines.append("%s(%s) :- g(0,%d,%d)." % (rel, args, g, groups[g].index(i) + 1))
        for head, hv, pos, neg in self.rules:
            body = ["%s(%s)" % (r, ",".join(x.upper() for x in v)) for r, v in pos]
            body += ["not %s(%s)" % (r, ",".join(x.upper() for x in v)) for r, v in neg]
            lines.append("%s(%s) :- %s." % (head, ",".join(x.upper() for x in hv), ", ".join(body)))
        return "\n".join(lines) + "\n"

    def emit(self):
        return ("import itertools, sys, warnings\nwarnings.filterwarnings('ignore')\n"
                "sys.path.insert(0, %r)\nimport torch\nfrom mvpp import MVPP\n"
                "D = %d\nm = MVPP(%r)\n"
                "m.parameters = [torch.Tensor(pr) for pr in m.parameters]\nm.normalize_probs()\n"
                "def RES(rel, t):\n"
                "    models = m.find_k_SM_under_obs(':- not %%s(%%s).\\n' %% (rel, ','.join(map(str, t))), k=0)\n"
                "    return float(m.prob_of_interpretation(models).sum()) if len(models) else 0.0\n"
                % (NEURASP_DIR, self.domain(), self.mvpp_text())) + self.printer(repr(self.query_tuples()))
