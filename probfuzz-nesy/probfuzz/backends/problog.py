from backends.backend import NesyBackend
from backends.problog_text import LogicText


class ProbLog(NesyBackend, LogicText):
    tool = 'problog'

    def emit(self):
        return ("import itertools, warnings\nwarnings.filterwarnings('ignore')\n"
                "from problog.program import PrologString\nfrom problog import get_evaluatable\n"
                "D = %d\nPROGRAM = %r\nQ = %r\n"
                "text = PROGRAM + ''.join('query(%%s(%%s)).\\n' %% (rel, ','.join(map(str, t))) for rel, ar in Q "
                "for t in itertools.product(range(D), repeat=ar))\n"
                "got = {str(k): float(v) for k, v in get_evaluatable().create_from(PrologString(text)).evaluate().items()}\n"
                "RES = lambda rel, t: got.get('%%s(%%s)' %% (rel, ','.join(map(str, t))), 0.0)\n"
                % (self.domain(), self.logic_text(), self.query_tuples())) + self.printer(repr(self.query_tuples()))
