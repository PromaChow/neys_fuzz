import itertools
import subprocess as sp
import sys

import antlr4
from language.antlr.TemplateLexer import TemplateLexer
from language.antlr.TemplateParser import TemplateParser
from language.antlr.TemplateVisitor import TemplateVisitor
from utils.utils import *


class Backend(TemplateVisitor):
    def __init__(self, target_directory):
        self._directory = target_directory

    @staticmethod
    def run(self):
        return NotImplementedError

    def create_program(self):
        return NotImplementedError


class NesyBackend(Backend):
    """Common part of the NeSy backends. Like ProbFuzz's Stan/Edward/Pyro backends it is a visitor over the template's
    parse tree: it collects the rules and queries, takes the completed holes (priors, constants) from the populator,
    and each subclass renders a standalone program for its system (`emit`). Every generated program prints
    `RESULT <relation> <t0,t1,..> <probability>` lines and a final `DONE`; `run` executes it and keeps the output."""

    tool = None

    def __init__(self, file_dir, data_dict, prior_dict, distmap, constmap, templatefile, config, algorithm):
        super(NesyBackend, self).__init__(file_dir)
        self.data_dict = data_dict
        self.prior_dict = prior_dict
        self.distmap = distmap
        self.constmap = constmap
        self.templatefile = templatefile
        self.config = config
        self.algorithm = algorithm
        self.rules = []      # (head_rel, head_vars, [(rel, vars)], [(rel, vars)])
        self.queries = []

    # -- visitor part ------------------------------------------------------------------------------------------
    def visitTemplate(self, ctx):
        for child in ctx.children:
            self.visit(child)

    def visitLogicrule(self, ctx):
        def atom(a):
            return a.ID(0).getText(), tuple(v.getText().lower() for v in a.ID()[1:])
        pos, neg = [], []
        for lit in ctx.literal():
            (neg if lit.getChild(0).getText() == 'not' else pos).append(atom(lit.atom()))
        head = atom(ctx.atom())
        self.rules.append((head[0], head[1], pos, neg))

    def visitQuery(self, ctx):
        self.queries.append(ctx.ID().getText())

    # -- ground program -----------------------------------------------------------------------------------------
    def domain(self):
        dims = [d for p in self.prior_dict.values() for d in p['dims']]
        return max(dims) if dims else 3

    def edb_arity(self):
        return {n: (1 if p['prior']['name'] == 'categorical' else len(p['dims'])) for n, p in self.prior_dict.items()}

    def idb_arity(self):
        return {h: len(v) for (h, v, _, _) in self.rules}

    def facts(self):
        """[(relation, tuple, probability, group index or None)]; a categorical prior is one group of alternatives."""
        out, ngroups = [], 0
        for name, p in self.prior_dict.items():
            if p['prior']['name'] == 'categorical':
                for j, pr in enumerate(p['args']):
                    out.append((name, (j,), pr, ngroups))
                ngroups += 1
            else:
                for t in itertools.product(*[range(d) for d in p['dims']]):
                    out.append((name, t, p['args'][0], None))
        return out

    def query_tuples(self):
        ar = {**self.edb_arity(), **self.idb_arity()}
        return [(q, ar[q]) for q in self.queries]

    # -- driver part ------------------------------------------------------------------------------------------
    def progfile(self):
        return "{0}_{1}_prog.py".format(self.tool, self.algorithm)

    def create_program(self):
        template = antlr4.FileStream(self.templatefile)
        lexer = TemplateLexer(template)
        stream = antlr4.CommonTokenStream(lexer)
        parser = TemplateParser(stream)
        self.visit(parser.template())
        with open(self._directory + '/' + self.progfile(), 'w') as f:
            f.write(self.emit())

    def emit(self):
        raise NotImplementedError

    def run(self, timeout, prog_id, python_cmd):
        python_cmd = sys.executable if python_cmd == 'python' else python_cmd
        outname = "{0}_{1}_out_{2}".format(self.tool, self.algorithm, prog_id)
        try:
            p = sp.run([python_cmd, self.progfile()], cwd=self._directory, capture_output=True, text=True,
                       timeout=timeout)
            text = p.stderr + p.stdout
        except sp.TimeoutExpired as e:
            text = "TIMEOUT after {0}s\n".format(timeout)
        with open(self._directory + '/' + outname, 'w') as f:
            f.write(text)

    # -- shared text helpers ------------------------------------------------------------------------------------
    @staticmethod
    def printer(queries_expr):
        return ('for rel, arity in %s:\n'
                '    for t in itertools.product(range(D), repeat=arity):\n'
                '        v = RES(rel, t)\n'
                '        if v is not None:\n'
                '            print("RESULT", rel, ",".join(map(str, t)), repr(float(v)))\n'
                'print("DONE")\n') % queries_expr
