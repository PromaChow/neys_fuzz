class LogicText(object):
    """Renders the ground program as a ProbLog / DeepProbLog source text (both read the same syntax)."""

    def logic_text(self):
        lines, groups = [], {}
        for rel, t, p, g in self.facts():
            atom = "%s(%s)" % (rel, ",".join(map(str, t)))
            if g is None:
                lines.append("%r::%s." % (p, atom))
            else:
                groups.setdefault(g, []).append("%r::%s" % (p, atom))
        for alts in groups.values():
            lines.append("; ".join(alts) + ".")
        for head, hv, pos, neg in self.rules:
            body = ["%s(%s)" % (r, ",".join(x.upper() for x in v)) for r, v in pos]
            body += ["\\+%s(%s)" % (r, ",".join(x.upper() for x in v)) for r, v in neg]
            lines.append("%s(%s) :- %s." % (head, ",".join(x.upper() for x in hv), ", ".join(body)))
        return "\n".join(lines) + "\n"
