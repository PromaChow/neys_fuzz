"""Where does DeepProbLog's ExactEngine spend its time: ProbLog, DeepProbLog's own code, torch, or others?"""
import cProfile, pstats, re, warnings, collections
warnings.filterwarnings("ignore")
from deepproblog.engines import ExactEngine
from deepproblog.model import Model
from deepproblog.query import Query
from problog.program import PrologString

def attribute(path):
    if "frameworks/problog/problog" in path: return "problog (counterpart)"
    if "deepproblog/src/deepproblog" in path: return "deepproblog (own code)"
    if "site-packages/torch" in path: return "torch"
    if "pysdd" in path: return "pysdd (C library)"
    if path.startswith("{") or path.startswith("<") or "/Frameworks/Python.framework" in path: return "python stdlib / builtins"
    return "other"

workloads = {
 "coins (3 facts, 2 rules)":    ("0.5::a. 0.6::b.\nc :- a, b.\nd :- a.\nd :- b.\n", ["c", "d"]),
 "disjunction of 100 (ProbLog test 11)": (
    "".join([f"1/100::a{i}; " for i in range(1, 100)]) + "1/100::a100 <- true.\n", ["a1", "a100"]),
 "chain of 12 conjunctions":    ("".join(f"0.9::f{i}.\n" for i in range(12)) + "q :- " + ", ".join(f"f{i}" for i in range(12)) + ".\n", ["q"]),
}
def run(prog, qs):
    m = Model(prog, [], load=False); m.set_engine(ExactEngine(m))
    for q in qs:
        m.solve([Query(list(PrologString(q + "."))[0])])

for name, (prog, qs) in workloads.items():
    run(prog, qs)                                   # warm-up (imports, caches)
    pr = cProfile.Profile(); pr.enable()
    for _ in range(15): run(prog, qs)
    pr.disable()
    st = pstats.Stats(pr)
    own = collections.Counter(); calls = collections.Counter()
    for (fn, ln, nm), (cc, nc, tt, ct, callers) in st.stats.items():
        own[attribute(fn)] += tt; calls[attribute(fn)] += nc
    tot, totc = sum(own.values()), sum(calls.values())
    print(f"\n{name}: total {tot*1000/15:.1f} ms per run")
    for k in sorted(own, key=own.get, reverse=True):
        print(f"   {k:26s} {100*own[k]/tot:5.1f}% of time   {100*calls[k]/totc:5.1f}% of function calls")
