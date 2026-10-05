"""Minimal repro: DeepProbLog ApproximateEngine cannot negate a probabilistic fact (ExactEngine and ProbLog can)."""
import warnings; warnings.filterwarnings("ignore")
from deepproblog.engines import ExactEngine, ApproximateEngine
from deepproblog.model import Model
from deepproblog.query import Query
from problog.logic import Term, Constant
prog = "0.5::a. 0.3::b.\nq :- a, \\+b.\n"
for name, mk in (("exact", ExactEngine),
                 ("approx-ucs", lambda m: ApproximateEngine(m, 10, ApproximateEngine.ucs)),
                 ("approx-geometric_mean", lambda m: ApproximateEngine(m, 10, ApproximateEngine.geometric_mean))):
    m = Model(prog, [], load=False); m.set_engine(mk(m))
    try:
        r = m.solve([Query(Term("q"))])[0].result
        print(name, {str(k): float(v) for k, v in r.items()}, "(expected q = 0.5*0.7 = 0.35)")
    except BaseException as e:
        print(name, type(e).__name__, str(e)[:160])
