"""Standalone reproduction (no harness code): a probability-0.0 fact in DeepProbLog's ApproximateEngine."""
import warnings; warnings.filterwarnings("ignore")
from deepproblog.engines import ExactEngine, ApproximateEngine
from deepproblog.model import Model
from deepproblog.query import Query
from problog.logic import Term

def solve(prog, engine, k=50, heuristic=None):
    m = Model(prog, [], load=False)
    if engine == "exact":
        m.set_engine(ExactEngine(m))
    else:
        h = heuristic or ApproximateEngine.geometric_mean
        m.set_engine(ApproximateEngine(m, k, h))
    q = Term("q")
    res = m.solve([Query(q)])[0].result
    return float(res[q]) if q in res else "ABSENT"

print("heuristics available:", [n for n in dir(ApproximateEngine) if not n.startswith('_') and n not in ('ground','prepare','eval','train')])
progs = {
  "A: 0.0::z. 0.6::a. q :- a. q :- z.":            "0.0::z.\n0.6::a.\nq :- a.\nq :- z.\n",
  "B: t(0.0)::z. t(0.6)::a. q :- a. q :- z.":      "t(0.0)::z.\nt(0.6)::a.\nq :- a.\nq :- z.\n",
  "C: 0.0::z. 0.6::a. q :- a.   (z unused)":       "0.0::z.\n0.6::a.\nq :- a.\n",
  "D: 0.001::z. 0.6::a. q :- a. q :- z.":          "0.001::z.\n0.6::a.\nq :- a.\nq :- z.\n",
  "E: 0.0::z. 1.0::a. q :- a, z. q :- a.":         "0.0::z.\n1.0::a.\nq :- a, z.\nq :- a.\n",
}
for name, prog in progs.items():
    print(f"{name:48s} exact={solve(prog,'exact')}  approx={solve(prog,'approx')}")
print("\nvarying k on program A:", {k: solve(progs[list(progs)[0]], 'approx', k) for k in (1, 2, 5, 50)})
for hname in [n for n in dir(ApproximateEngine) if n in ('geometric_mean','ucs','learned_ratio','arithmetic_mean')]:
    print(f"heuristic {hname:16s} on program A:", solve(progs[list(progs)[0]], 'approx', 50, getattr(ApproximateEngine, hname)))
