"""LTNtorch: ImpliesGoguen() with its default stable=True scores a satisfied implication (false -> false) as ~0.

Documented formula (class docstring of ltn.fuzzy_ops.ImpliesGoguen):  x -> y = 1 if x <= y else y / x.
The stable version projects the antecedent with pi_0(x) = (1 - 1e-4) x + 1e-4, so for x <= 1e-3 the projection dominates.
"""
import os
import sys
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frameworks", "LTNtorch"))
import torch
from ltn import fuzzy_ops as F

stable, plain = F.ImpliesGoguen(), F.ImpliesGoguen(stable=False)
print(f"{'x':>9} {'y':>9} | {'doc formula':>11} {'stable=False':>12} {'stable=True (default)':>22}")
for x, y in [(0.0, 0.0), (0.0, 1e-5), (1e-6, 1e-6), (1e-5, 1e-5), (1e-4, 1e-4), (1e-3, 1e-3), (1e-2, 1e-2), (0.3, 0.3), (0.5, 0.5)]:
    tx, ty = torch.tensor([x]), torch.tensor([y])
    doc = 1.0 if x <= y else y / x
    print(f"{x:9.1e} {y:9.1e} | {doc:11.4f} {float(plain(tx, ty)):12.4f} {float(stable(tx, ty)):22.4f}")
