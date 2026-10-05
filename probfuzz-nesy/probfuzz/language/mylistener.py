import random
import numpy as np
from language.antlr.TemplateListener import TemplateListener
from language.antlr.TemplateParser import TemplateParser
from utils.utils import *


class MyListener(TemplateListener):
    """Completes the holes of a template: data (domain size), distributions (DIST/DISTX) and constants (CONST).

    NeSy adaptation: a prior `r := bernoulli(CONST)[n,m]` declares relation r/2 with n*m independent probabilistic
    facts; `d := categorical(CONST,CONST,CONST)` declares relation d/1 with one mutually exclusive group of 3 facts."""

    def __init__(self, models, parser, structured=True, special=False):
        self.data = dict()
        self.priors = dict()
        self.distMap = dict()
        self.constMap = dict()
        self.models = models
        self.structured = structured
        self.special = special

    def _gen(self, typ):
        return float(generate_primitives(typ if self.structured else 'f', 1, self.special)[0])

    def enterData(self, ctx=TemplateParser.DataContext):
        if ctx.dtype() is None:
            return
        name = ctx.ID().getText()
        prim = ctx.dtype().primitive().getText()
        if ctx.dtype().dims() is not None:
            size = [int(x.getText()) for x in ctx.dtype().dims().dim()]
            self.data[name] = np.random.uniform(0, 100, size)
        elif prim == 'int':
            # NeSy adaptation: an int datum is a domain size; ground programs stay small enough for the exact oracle
            self.data[name] = int(np.random.randint(2, 4))
        else:
            self.data[name] = np.random.uniform(0, 10)

    def _dims(self, distexpr):
        if distexpr.dims() is None:
            return []
        out = []
        for d in distexpr.dims().dim():
            out.append(int(d.getText()) if d.INT() is not None else int(self.data[d.getText()]))
        return out

    def enterPrior(self, ctx=TemplateParser.PriorContext):
        name = ctx.ID().getText()
        distexpr = ctx.distexpr()
        first = distexpr.children[0].getText()
        nparams = len(distexpr.params().param()) if distexpr.params() is not None else 0
        if first == 'DISTX':
            prior = random.choice([m for m in self.models if len(m['args']) == 1 and not m['args'][0].get('variadic')])
        elif first == 'DIST':
            prior = random.choice([m for m in self.models if m['args'][0].get('variadic') or len(m['args']) == nparams])
        else:
            prior = [m for m in self.models if m['name'] == first][0]
        arglist = []
        if prior['args'][0].get('variadic'):
            arglist = [self._gen(prior['args'][0]['type']) for _ in range(max(nparams, 2))]
        else:
            arglist = [self._gen(arg['type']) for arg in prior['args']]
        self.priors[name] = {'prior': prior, 'args': arglist, 'dims': self._dims(distexpr)}
