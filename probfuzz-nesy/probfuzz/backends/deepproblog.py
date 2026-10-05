from backends.backend import NesyBackend
from backends.problog_text import LogicText


class DeepProbLog(NesyBackend, LogicText):
    tool = 'deepproblog'

    def emit(self):
        engine = ("ExactEngine(m)" if self.algorithm == 'exact'
                  else "ApproximateEngine(m, 200, ApproximateEngine.geometric_mean)")
        return ("import itertools, warnings\nwarnings.filterwarnings('ignore')\n"
                "from deepproblog.engines import ExactEngine, ApproximateEngine\n"
                "from deepproblog.model import Model\nfrom deepproblog.query import Query\n"
                "from problog.logic import Term, Constant\n"
                "D = %d\nPROGRAM = %r\n"
                "m = Model(PROGRAM, [], load=False)\nm.set_engine(%s)\n"
                "def RES(rel, t):\n"
                "    q = Term(rel, *[Constant(c) for c in t])\n"
                "    r = m.solve([Query(q)])[0].result\n"
                "    return r[q] if q in r else None\n"
                % (self.domain(), self.logic_text(), engine)) + self.printer(repr(self.query_tuples()))
