"""LNN: two structurally identical sub-formulas built as separate objects are one graph node (Formula.__eq__/__hash__ compare
`structure`), but the second Python object is never updated. Upward inference then leaves it UNKNOWN even though every leaf is
known, and some shapes make infer() run forever. Reusing ONE object for both operands gives the right answer.
Each case runs in a child process with a 20 s limit.
"""
import subprocess
import sys

PRE = '''
import warnings, logging, sys
warnings.filterwarnings("ignore"); logging.disable(logging.CRITICAL)
sys.path.insert(0, "frameworks/LNN")
from lnn import Model, Proposition, And, Or, Not, Implies, Iff, Fact
a, b = Proposition("a"), Proposition("b")
'''
CASES = [
    ("Or(a,b) used twice, as ONE shared object: And(o, o)", "o = Or(a, b)\nroot = And(o, o)", {"a": True, "b": False}, "classical value: True"),
    ("Or(a,b) used twice, as TWO identical objects: And(Or(a,b), Or(a,b))", "root = And(Or(a, b), Or(a, b))", {"a": True, "b": False}, "classical value: True"),
    ("same with Implies: Implies(Or(a,b), Or(a,b)) (two objects)", "root = Implies(Or(a, b), Or(a, b))", {"a": True, "b": False}, "classical value: True"),
    ("implicit duplicate through Iff: And(Iff(a,b), Implies(b,a))", "root = And(Iff(a, b), Implies(b, a))", {"a": True, "b": True}, "classical value: True"),
    ("Implies(And(a,b), And(a,b)) (two objects), classical inputs", "root = Implies(And(a, b), And(a, b))", {"a": True, "b": True}, "classical value: True"),
    ("same, real-valued inputs: infer() runs forever", "root = Implies(And(a, b), And(a, b))", {"a": 0.9, "b": 0.8}, "Lukasiewicz value: 1.0"),
]
for label, build, world, note in CASES:
    code = PRE + build + "\nm = Model(); m.add_knowledge(root)\n" + \
        ("m.add_data({a: (%r, %r), b: (%r, %r)})\n" % (world['a'], world['a'], world['b'], world['b']) if isinstance(world['a'], float) else
         f"m.add_data({{a: Fact.TRUE if {world['a']} else Fact.FALSE, b: Fact.TRUE if {world['b']} else Fact.FALSE}})\n") + \
        "m.infer()\nprint('bounds', [round(float(x), 4) for x in root.get_data()], 'state', root.state())\n"
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        out = r.stdout.strip() or r.stderr.strip()[-100:]
    except subprocess.TimeoutExpired:
        out = "infer() did not return within 20 s"
    print(f"{label}\n    a={world['a']}, b={world['b']} ({note}) -> {out}")
