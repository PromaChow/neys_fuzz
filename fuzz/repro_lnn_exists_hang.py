"""LNN: Model.infer() never returns for a model with a quantified formula added through add_knowledge().

The program is the library's own tests/reasoning/logic/fol/test_square_rectangle.py, with the Exists query registered with
add_knowledge() (as the documentation example does) instead of set_query(). The script runs each variant in a child
process with a 20 s limit.
"""
import subprocess
import sys

BODY = '''
import warnings, logging; warnings.filterwarnings("ignore"); logging.disable(logging.CRITICAL)
sys.path.insert(0, "frameworks/LNN")
from lnn import Predicate, Variable, Exists, Implies, Forall, Model, Fact, World
x = Variable("x")
square, rectangle, foursides = Predicate("square"), Predicate("rectangle"), Predicate("foursides")
square_rect = Forall(x, Implies(square(x), rectangle(x)))
rect_foursides = Forall(x, Implies(rectangle(x), foursides(x)))
query = Exists(x, foursides(x))
model = Model()
model.add_knowledge(square_rect, rect_foursides, world=World.AXIOM)
%s
model.add_data({square: {"c": Fact.TRUE, "k": Fact.TRUE}})
steps, inferred = model.infer()
print("returned: steps=%%s inferred=%%s query=%%s" %% (steps, float(inferred), query.state()))
'''
for label, line in (("query registered with set_query()   (library test)", "model.set_query(query)"),
                    ("query registered with add_knowledge() (docs style)", "model.add_knowledge(query)")):
    try:
        r = subprocess.run([sys.executable, "-c", "import sys\n" + BODY % line], capture_output=True, text=True, timeout=20)
        print(f"{label}: {r.stdout.strip() or r.stderr.strip()[-120:]}")
    except subprocess.TimeoutExpired:
        print(f"{label}: infer() did not return within 20 s")

print()
print("Minimal form: Exists(x, P(x)) with P(a), P(b) TRUE, add_knowledge + infer(max_steps=N)")
for n in (1, 2, 5, 10):
    code = ('import sys,warnings,logging\nwarnings.filterwarnings("ignore"); logging.disable(logging.CRITICAL)\nsys.path.insert(0,"frameworks/LNN")\n'
            'from lnn import Model, Variable, Fact, Exists\nx=Variable("x"); m=Model(); P=m.add_predicates(1,"P"); m.add_data({P:{"a":Fact.TRUE,"b":Fact.TRUE}})\n'
            f'E=Exists(x,P(x)); m.add_knowledge(E); s,i=m.infer(max_steps={n}); print("steps",s,"bounds updates reported",float(i),"state",E.state())')
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    print(f"  max_steps={n:2d}: {r.stdout.strip()}")
print("The count of reported bounds updates grows by 1.0 per step although the bounds are already [1,1]: the quantifier\n"
      "neuron is rebuilt on every pass (unary_operator._create_neuron), so the 'no update' convergence test is never reached.")
