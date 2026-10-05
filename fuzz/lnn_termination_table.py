"""LNN: which single-quantifier models make Model.infer() return, and which never do (add_knowledge vs set_query)."""
import json
import subprocess
import sys

CODE = '''
import warnings, logging, sys
warnings.filterwarnings("ignore"); logging.disable(logging.CRITICAL)
sys.path.insert(0, "frameworks/LNN")
from lnn import Model, Variable, Fact, World, Exists, Forall
Q = {"Exists": Exists, "Forall": Forall}["%s"]
facts = {"all_true": {"a": Fact.TRUE, "b": Fact.TRUE}, "one_false": {"a": Fact.TRUE, "b": Fact.FALSE},
         "all_false": {"a": Fact.FALSE, "b": Fact.FALSE}, "bounds": {"a": (0.2, 0.7), "b": Fact.TRUE}}["%s"]
x = Variable("x"); m = Model(); P = m.add_predicates(1, "P")
F = Q(x, P(x), world=World.OPEN)
m.add_knowledge(F) if "%s" == "add_knowledge" else m.set_query(F)
m.add_data({P: facts}); m.infer(); print("ok")
'''
rows = []
for q in ("Exists", "Forall"):
    for data in ("all_true", "one_false", "all_false", "bounds"):
        res = {}
        for how in ("add_knowledge", "set_query"):
            try:
                r = subprocess.run([sys.executable, "-c", CODE % (q, data, how)], capture_output=True, text=True, timeout=8)
                res[how] = "returns" if "ok" in r.stdout else "error"
            except subprocess.TimeoutExpired:
                res[how] = "NEVER RETURNS"
        rows.append((q, data, res["add_knowledge"], res["set_query"]))
print(f"{'quantifier':10s} {'data':10s} {'add_knowledge':15s} {'set_query':10s}   (world OPEN, P(a), P(b) as listed)")
for r in rows:
    print(f"{r[0]:10s} {r[1]:10s} {r[2]:15s} {r[3]:10s}")
json.dump([dict(zip(("quantifier", "data", "add_knowledge", "set_query"), r)) for r in rows], open(__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "results", "lnn_termination_table.json"), "w"), indent=1)
