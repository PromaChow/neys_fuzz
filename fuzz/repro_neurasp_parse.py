"""Standalone reproduction: plain, valid ASP programs that NeurASP's MVPP rejects (clingo accepts all of them)."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "../frameworks/NeurASP")
import clingo
from mvpp import MVPP

def clingo_models(text):
    ctl = clingo.Control(["0", "--warn=none"]); ctl.add("base", [], text); ctl.ground([("base", [])])
    out = []; ctl.solve(on_model=lambda m: out.append(sorted(str(a) for a in m.symbols(atoms=True)))); return out

cases = {
  "choice rule with leading lower bound":  "1 { a; b } 1.\n",
  "same rule, bound written as '0 {'":     "0 { a; b } 1.\n",
  "cardinality body with leading bound":   "p :- 1 { a; b } 2.\na.\n",
  "plain facts (control, should work)":    "a. b.\n",
  "valid program ending in a line comment (string input)": "a. % done",
  "valid program ending in a block comment (string input)": "a.\n%* end *%",
}
for name, text in cases.items():
    ref = clingo_models(text)
    try:
        got = [sorted(m) for m in MVPP(text).find_all_SM_under_obs("")]
        verdict = "same as clingo" if sorted(map(tuple, got)) == sorted(map(tuple, ref)) else f"DIFFERENT: clingo={ref} neurasp={got}"
    except SystemExit as e:
        verdict = f"SystemExit({e.code})  [the library terminates the whole process]"
    except BaseException as e:
        verdict = f"{type(e).__name__}: {e}"
    print(f"{name:55s} clingo: {len(ref)} answer set(s) | NeurASP: {verdict}")
