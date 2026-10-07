"""Brute-force the formula that Scallop's wmc_with_disjunctions builds (as_boolean_formula.rs:31-41)
for the F3 repro group {0.0313, 0.392, 0.4039}, query = exists(a(_)) = a0 or a1 or a2."""
from itertools import product
p = [0.0313, 0.392, 0.4039]
def C(w):   # AND over i of ( OR_j  (not f_i if j==i else f_j) )   -- the per-group term, lines 32-40
    return all(any((not w[j]) if j == i else w[j] for j in range(3)) for i in range(3))
def weight(w):
    r = 1.0
    for x, q in zip(w, p): r *= q if x else 1 - q
    return r
worlds = list(product([False, True], repeat=3))
print("worlds where constraint C is true :", [''.join('1' if x else '0' for x in w) for w in worlds if C(w)])
print("worlds where C is false           :", [''.join('1' if x else '0' for x in w) for w in worlds if not C(w)], "(= exactly one member true)")
formula = lambda w: any(w)
indep   = sum(weight(w) for w in worlds if formula(w))
with_or = sum(weight(w) for w in worlds if formula(w) or C(w))     # what the code builds (OR)
with_and= sum(weight(w) for w in worlds if formula(w) and not C(w))  # exactly-one worlds only
print(f"default wmc (ignores exclusivity)          : {indep:.4f}   <- Scallop default 0.6489")
print(f"flag on: formula OR C (as coded)           : {with_or:.4f}   <- Scallop flag 1.0")
print(f"true answer (sum of exclusive members)     : {sum(p):.4f}   <- 0.8272")
