"""Minimal reproduction: two categorical (disjunctive) input mappings in one Scallop program collide on disjunction id 0."""
import itertools, warnings; warnings.filterwarnings("ignore")
import numpy as np, torch, scallopy
from scallopy.input_mapping import InputMapping

p1 = torch.tensor([[0.7, 0.3]]); p2 = torch.tensor([[0.4, 0.6]])        # two categorical variables with 2 values each
exact = {s: sum(float(p1[0, a]) * float(p2[0, b]) for a, b in itertools.product(range(2), repeat=2) if a + b == s) for s in range(3)}

def run(categorical_1, categorical_2):
    ctx = scallopy.ScallopContext(provenance="difftopkproofs", k=10)
    ctx.add_relation("d1", int, range(2)); ctx.add_relation("d2", int, range(2))
    if categorical_1: ctx.set_input_mapping("d1", range(2), disjunctive=True)
    if categorical_2: ctx.set_input_mapping("d2", range(2), disjunctive=True)
    ctx.add_rule("s(a + b) = d1(a), d2(b)")
    return ctx.forward_function("s", [0, 1, 2], dispatch="serial")(d1=p1, d2=p2).detach().numpy()[0]

print("exact P(sum=0,1,2) =", [round(exact[s], 4) for s in range(3)], " total 1.0")
print("both categorical, scallopy as shipped   ->", run(True, True).round(4), " total", run(True, True).sum().round(4))

# the proposed one-line fix: give every relation the context's shared counter instead of a fresh Counter()
orig = InputMapping.process_tensor
def patched(self, tensor, batched=False, mutual_exclusion_counter=None):
    return orig(self, tensor, batched, mutual_exclusion_counter or SHARED)
class _C:
    def __init__(self): self.n = 0
    def get_and_increment(self): self.n += 1; return self.n - 1
SHARED = _C()
InputMapping.process_tensor = patched
print("both categorical, with a shared counter ->", run(True, True).round(4), " total", run(True, True).sum().round(4))
