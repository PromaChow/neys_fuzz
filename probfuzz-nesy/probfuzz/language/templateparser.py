import antlr4
from antlr4 import *
from language.antlr.TemplateLexer import TemplateLexer
from language.antlr.TemplateParser import TemplateParser
from language.mylistener import MyListener
from utils.utils import *


class TemplatePopulator():

    def __init__(self, output_dir, templatefile, models):
        self.output_dir = output_dir
        self.templatefile = templatefile
        self.models = models
        self.validModel = True

    def populate(self, structured=True):
        template = antlr4.FileStream(self.templatefile)
        lexer = TemplateLexer(template)
        stream = antlr4.CommonTokenStream(lexer)
        parser = TemplateParser(stream)
        listener = MyListener(self.models, parser, structured, special_enabled())
        template = parser.template()
        walker = ParseTreeWalker()
        walker.walk(listener, template)

        from language.checker import Checker
        checker = Checker(listener.distMap, listener.priors, listener.constMap)
        checker.visit(template)
        self.validModel = checker.valid
        return listener.data, listener.priors, listener.distMap, listener.constMap
