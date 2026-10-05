"""Standalone reproduction (no harness code): mutually exclusive facts in Scallop."""
import scallopy

def run(k=300, wmc=False):
    ctx = scallopy.ScallopContext(provenance="topkproofs", k=k, wmc_with_disjunctions=wmc)
    ctx.add_relation("a", (int,))
    # one annotated disjunction: exactly one of a(0), a(1), a(2) holds (or none, with the remaining mass)
    ctx.add_facts("a", [(0.0313, (1,)), (0.392, (0,)), (0.4039, (2,))], disjunctions=[[0, 1, 2]])
    ctx.add_rule("some() = a(y)")
    ctx.run()
    return list(ctx.relation("some"))

p = [0.0313, 0.392, 0.4039]
print("expected P(some a holds) if mutually exclusive  =", sum(p))
independent = 1.0
for x in p: independent *= (1 - x)
print("value if treated as INDEPENDENT (noisy-or)     =", 1 - independent)
for wmc in (False, True):
    print(f"scallopy topkproofs k=300 wmc_with_disjunctions={wmc}:", run(wmc=wmc))
for k in (1, 3, 10):
    print(f"scallopy topkproofs k={k:<3} wmc_with_disjunctions=False:", run(k=k))
