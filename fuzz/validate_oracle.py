"""Cross-check the possible-worlds oracle (nesy_prog.exact_probs) against ProbLog.

If these disagree, the oracle (not a framework) is wrong, so this must pass
before any framework result is trusted.
"""
import random
import sys

from problog import get_evaluatable
from problog.program import PrologString

from nesy_prog import Prog, exact_probs, gen_prog


def to_problog(p: Prog) -> str:
    lines = []
    in_group = p.grouped()
    for i, (r, t, pr) in enumerate(p.facts):
        if i not in in_group:
            lines.append(f"{pr!r}::{r}({','.join(map(str, t))}).")
    for g in p.groups:
        alts = [f"{p.facts[i][2]!r}::{p.facts[i][0]}({','.join(map(str, p.facts[i][1]))})" for i in g]
        lines.append("; ".join(alts) + ".")
    for r in p.rules:
        body = [f"{a.rel}({','.join(v.upper() for v in a.vars)})" for a in r.pos]
        body += [f"\\+{a.rel}({','.join(v.upper() for v in a.vars)})" for a in r.neg]
        lines.append(f"{r.head.rel}({','.join(v.upper() for v in r.head.vars)}) :- {', '.join(body)}.")
    for rel in p.idb:
        for t in p.possible_tuples(rel):
            lines.append(f"query({rel}({','.join(map(str, t))})).")
    return "\n".join(lines)


def problog_probs(p: Prog):
    res = get_evaluatable().create_from(PrologString(to_problog(p))).evaluate()
    out = {r: {t: 0.0 for t in p.possible_tuples(r)} for r in p.idb}
    for term, val in res.items():
        rel = term.functor
        tup = tuple(int(a) for a in term.args)
        out[rel][tup] = float(val)
    return out


def main(n=300, seed=1):
    rng = random.Random(seed)
    worst, bad, skipped = 0.0, 0, 0
    for k in range(n):
        p = gen_prog(rng, allow_neg=True, allow_groups=True, boundary_rate=0.3)
        try:
            theirs = problog_probs(p)
        except Exception as e:  # ProbLog rejected the program: not an oracle error
            skipped += 1
            continue
        ours = exact_probs(p)
        for r in p.idb:
            for t in ours[r]:
                diff = abs(ours[r][t] - theirs[r][t])
                worst = max(worst, diff)
                if diff > 1e-9:
                    bad += 1
                    print("MISMATCH", r, t, ours[r][t], theirs[r][t])
                    print(p.to_text())
                    print(to_problog(p))
                    return 1
    print(f"oracle vs ProbLog: {n - skipped} programs compared, {skipped} skipped, "
          f"max abs diff {worst:.2e}, mismatches {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*(int(a) for a in sys.argv[1:])))
