"""LTNtorch: Quantifier called with an empty variable list is accepted; the result claims free variables it does not have,
and the dtype of a guarded quantifier result differs from an unguarded one."""
import os
import sys
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frameworks", "LTNtorch"))
import torch
import ltn
from ltn import fuzzy_ops as F

x = ltn.Variable("x", torch.rand(4, 1))
y = ltn.Variable("y", torch.rand(3, 1))
P = ltn.Predicate(func=lambda a, b: torch.sigmoid(a.sum(-1) + b.sum(-1)))
Forall = ltn.Quantifier(F.AggregPMeanError(p=2), quantifier="f")
r = Forall([], P(x, y))
print("Forall([], P(x,y)): value shape", tuple(r.value.shape), "| free_vars reported:", r.free_vars)
unguarded = Forall(x, P(x, y))
guarded = Forall(x, P(x, y), cond_vars=[x], cond_fn=lambda v: v.value[:, 0] > -1)      # condition true for every individual
print("unguarded dtype:", unguarded.value.dtype, "| guarded (all selected) dtype:", guarded.value.dtype)
print("NotGodel float64 in ->", F.NotGodel()(torch.tensor([0.0, 1.0], dtype=torch.float64)).dtype)
