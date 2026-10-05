"""Final classification of the ProbLog -> DeepProbLog adoption (read the raw results, no re-running of engines)."""
import json, os, sys, collections, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adopt_problog_tests import own_queries
T = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frameworks", "problog", "test")
rows = [json.loads(l) for l in open(os.path.join(T, "..", "..", "..", "results", "adopt_problog_to_deepproblog.jsonl"))]
PASS = {"pass_strict", "error_match", "pass_extra_keys"}

def classify(r, system):
    cat = r["systems"][system]["category"]
    text = open(os.path.join(T, r["program"])).read()
    nq = len(own_queries(os.path.join(T, r["program"])))
    if cat in PASS:
        return "pass"
    if nq == 0 and ("query(" in text or "consult" in text):
        return "inconclusive: queries given as rules / in consulted files (not asked)"
    if "evidence" in r["features"]:
        return "FAIL: evidence(...) ignored"
    if cat == "unexpected_error" and "Tensor" in r["systems"][system]["detail"]:
        return "FAIL: aggregate builtin crashes (Tensor vs float)"
    if cat == "unexpected_error" or cat == "error_different":
        return "FAIL: other error"
    if cat == "missing_expected_error":
        return "FAIL: ProbLog's expected error not raised"
    if cat == "result_missing":
        return "FAIL: non-ground answers differ in shape/content"
    return f"FAIL: {cat}"

for system in ("dpl_exact", "dpl_approx_ucs"):
    c = collections.Counter(classify(r, system) for r in rows)
    adoptable = sum(n for k, n in c.items() if not k.startswith("inconclusive"))
    print(f"\n=== {system}: {len(rows)} ProbLog test programs; {len(rows) - adoptable} inconclusive; {adoptable} adoptable")
    for k, n in c.most_common():
        print(f"   {n:3d}  {k}")
    print(f"   -> passes {c['pass']} of {adoptable} adoptable ({100 * c['pass'] / adoptable:.0f}%)")
ex = [(r["program"], classify(r, "dpl_exact")) for r in rows if classify(r, "dpl_exact").startswith("FAIL")]
print("\nExactEngine failures:"); [print(f"   {p:34s} {k}") for p, k in ex]
