from antlr4 import *
from language.antlr.TemplateVisitor import TemplateVisitor
from language.antlr.TemplateParser import *
from utils.utils import *


class Checker(TemplateVisitor):
    """Structured-validity check (ProbFuzz's `structured` mode): a completed template is rejected and regenerated
    when it is not a valid program. NeSy adaptation of the support check:
      * every distribution argument lies in its declared support (a probability is in [0,1]);
      * the alternatives of a categorical sum to at most 1;
      * every relation used in a rule is declared by a prior or defined by a rule, with a consistent arity;
      * every variable of a rule head and of a negated atom occurs in a positive atom of the body (safety)."""

    def __init__(self, distmap, priormap, constmap):
        self.distMap = distmap
        self.priorMap = priormap
        self.constMap = constmap
        self.valid = True
        self.arity = {}
        for name, p in priormap.items():
            self.arity[name] = 1 if p['prior']['name'] == 'categorical' else len(p['dims'])

    def visitTemplate(self, ctx):
        for p in self.priorMap.values():
            for arg in p['args']:
                if not (0.0 <= arg <= 1.0):
                    self.valid = False
            if p['prior']['name'] == 'categorical' and sum(p['args']) > 1.0:
                self.valid = False
        # pass 1: arities of derived relations; pass 2: bodies
        rules = [c for c in ctx.children if isinstance(c, TemplateParser.ModelContext) and c.logicrule() is not None]
        for m in rules:
            head = m.logicrule().atom()
            n = len(head.ID()) - 1
            if self.arity.setdefault(head.ID(0).getText(), n) != n:
                self.valid = False
        for m in rules:
            r = m.logicrule()
            pos_vars, neg_atoms = set(), []
            for lit in r.literal():
                atom = lit.atom()
                rel, vs = atom.ID(0).getText(), [v.getText() for v in atom.ID()[1:]]
                if rel not in self.arity or self.arity[rel] != len(vs):
                    self.valid = False
                if lit.getChild(0).getText() == 'not':
                    neg_atoms.append(vs)
                else:
                    pos_vars.update(vs)
            head_vars = [v.getText() for v in r.atom().ID()[1:]]
            if not set(head_vars) <= pos_vars or any(not set(vs) <= pos_vars for vs in neg_atoms):
                self.valid = False
        for q in ctx.query():
            if q.ID().getText() not in self.arity:
                self.valid = False
