"""LNN: the square/rectangle example of docsrc/source/education/examples/reasoning.md, run exactly as written."""
import logging
import os
import sys
import warnings
logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frameworks", "LNN"))
from lnn import Predicate, Variable, Exists, Implies, Forall, Model, Fact, World

model = Model()
x = Variable('x')
square, rectangle, foursides = Predicate('square'), Predicate('rectangle'), Predicate('foursides')
square_rect = Forall(x, Implies(square(x), rectangle(x)))
rect_foursides = Forall(x, Implies(rectangle(x), foursides(x)))
query = Exists(x, foursides(x))
model.add_knowledge(square, rectangle, square_rect, rect_foursides, query)
model.add_data({square: {'c': Fact.TRUE, 'k': Fact.TRUE}})
steps, facts_inferred = model.infer()
print("steps:", steps, "| facts inferred:", float(facts_inferred), "| query state:", query.state())
print("foursides groundings:", foursides.get_data().tolist(), "(the documentation expects {'c', 'k'} to be inferred)")
print("The axioms were added without world=World.AXIOM, so they are not asserted; the library's own test uses\n"
      "model.add_knowledge(square_rect, rect_foursides, world=World.AXIOM) and model.set_query(...).")
