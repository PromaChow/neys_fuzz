"""Single fact  t::a.  query(a)  across magnitudes: where does each system stop returning t?"""
import warnings; warnings.filterwarnings("ignore")
from problog import get_evaluatable
from problog.program import PrologString
from deepproblog.engines import ExactEngine, ApproximateEngine
from deepproblog.model import Model
from deepproblog.query import Query
from problog.logic import Term

def problog(t):
    r = get_evaluatable(name="sdd").create_from(PrologString(f"{t!r}::a.\nquery(a).\n")).evaluate()
    return float(list(r.values())[0])

def dpl(t, approx=False):
    m = Model(f"{t!r}::a.\n", [], load=False)
    m.set_engine(ApproximateEngine(m, 10, ApproximateEngine.ucs) if approx else ExactEngine(m))
    r = m.solve([Query(Term("a"))])[0].result
    return float(r[Term("a")]) if Term("a") in r else None

print(f"{'t':>9s} | {'ProbLog':>12s} | {'DeepProbLog exact':>18s} | {'DeepProbLog approx(ucs)':>24s}")
first = {}
for k in list(range(6, 16)) + [20, 25, 30, 35, 37, 38, 39, 40, 41, 42, 44, 45, 46]:
    t = float(f"1e-{k}")
    vals = {"problog": problog(t), "dpl": dpl(t), "dpl_approx": dpl(t, True)}
    ok = {s: (v is not None and abs(v - t) <= 1e-3 * t) for s, v in vals.items()}
    for s in ok:
        if not ok[s] and s not in first: first[s] = t
    show = lambda v: "ABSENT" if v is None else (f"{v:.3g}" if v else "0.0")
    print(f"{t:9.0e} | {show(vals['problog']):>12s}{'' if ok['problog'] else ' <-- wrong':8s} | {show(vals['dpl']):>10s}{'' if ok['dpl'] else ' <-- wrong':8s} | {show(vals['dpl_approx']):>12s}{'' if ok['dpl_approx'] else ' <-- wrong'}")
print("\nlargest t at which each system first returns a wrong value (scanning downward):", {k: f"{v:.0e}" for k, v in first.items()})
