"""Does a failing ApproximateEngine run poison the process for later, valid runs?"""
import sys, warnings; warnings.filterwarnings("ignore")
from deepproblog.engines import ApproximateEngine
from deepproblog.model import Model
from deepproblog.query import Query
from problog.logic import Term
T = "/Users/promachowdhury/Claude/Projects/mutation/nesy-fuzz/frameworks/problog/test/"
GOOD = "0.5::a.\nq :- a.\n"

def solve(prog):
    m = Model(prog, [], load=False)
    m.set_engine(ApproximateEngine(m, 10, ApproximateEngine.ucs))
    return float(m.solve([Query(Term("q"))])[0].result[Term("q")])

mode = sys.argv[1]
if mode == "good_only":
    print("good program, fresh process ->", solve(GOOD), flush=True)
else:
    bad = open(T + "3_tossing_coin.pl").read()
    try:
        solve(bad)
    except BaseException as e:
        print("bad program ->", type(e).__name__, flush=True)
    for i in range(3):
        try:
            print(f"good program after the failure, attempt {i + 1} ->", solve(GOOD), flush=True)
        except BaseException as e:
            print(f"good program after the failure, attempt {i + 1} -> {type(e).__name__}: {str(e)[:70]}", flush=True)
    print("script reached its end", flush=True)
