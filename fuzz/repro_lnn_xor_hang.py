"""LNN: Model.infer() never returns for XOr when the formula is asserted TRUE and an operand is a near-classical soft value.

Found by mutating the data of LNN's own tests/reasoning/logic/propositional/test_Xor_1.py (a script that runs inference at
import time): its data (xor TRUE, P FALSE, Q TRUE, R TRUE) is classically contradictory and returns CONTRADICTION in 2 steps;
changing R from 1.0 to 0.999 makes infer() run forever. Each case runs in a child process with a 12 s limit.
"""
import subprocess
import sys

T = '''import warnings, logging, sys
warnings.filterwarnings("ignore"); logging.disable(logging.CRITICAL)
sys.path.insert(0, "frameworks/LNN")
from lnn import Propositions, XOr, Model, Fact
Q, R, S = Propositions("Q", "R", "S")
f = XOr(%s); m = Model(); m.add_knowledge(f); m.add_data(%s)
steps, _ = m.infer(); print("returned after", steps, "steps; XOr state:", f.state().name)
'''
cases = [
    ("XOr(Q,R,S)  TRUE, Q=TRUE, R=TRUE   (classical contradiction)", "Q, R, S", "{f: Fact.TRUE, Q: Fact.TRUE, R: Fact.TRUE}"),
    ("XOr(Q,R,S)  TRUE, Q=TRUE, R=0.9", "Q, R, S", "{f: Fact.TRUE, Q: Fact.TRUE, R: (0.9, 0.9)}"),
    ("XOr(Q,R,S)  TRUE, Q=TRUE, R=0.999", "Q, R, S", "{f: Fact.TRUE, Q: Fact.TRUE, R: (0.999, 0.999)}"),
    ("XOr(Q,R,S)  TRUE, Q=0.999, R=0.999", "Q, R, S", "{f: Fact.TRUE, Q: (0.999, 0.999), R: (0.999, 0.999)}"),
    ("XOr(Q,R)    TRUE, Q=TRUE, R=0.999", "Q, R", "{f: Fact.TRUE, Q: Fact.TRUE, R: (0.999, 0.999)}"),
    ("XOr(Q,R,S)  TRUE, Q=TRUE, R=FALSE  (consistent)", "Q, R, S", "{f: Fact.TRUE, Q: Fact.TRUE, R: Fact.FALSE}"),
]
for label, ops, data in cases:
    try:
        r = subprocess.run([sys.executable, "-c", T % (ops, data)], capture_output=True, text=True, timeout=12)
        out = r.stdout.strip() or r.stderr.strip()[-100:]
    except subprocess.TimeoutExpired:
        out = "infer() did not return within 12 s"
    print(f"{label:62s} -> {out}")
