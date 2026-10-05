"""Minimise the Scallop performance cliff: keep removing rules/facts/atoms while topkproofs k=30 stays slow (>2s)."""
import pickle, subprocess, sys, time
from dataclasses import replace
from nesy_prog import Rule, shrink
prog = pickle.load(open("/tmp/case26.pkl", "rb"))
child = r'''
import pickle, sys, time
sys.path.insert(0, ".")
from scallop_fuzz import scallop_probs
prog = pickle.loads(sys.stdin.buffer.read())
t = time.time(); scallop_probs(prog, provenance="topkproofs", k=30); print("%.3f" % (time.time() - t))
'''
def runtime(p, limit=25):
    try:
        out = subprocess.run([sys.executable, "-c", child], input=pickle.dumps(p), capture_output=True, timeout=limit)
        return float(out.stdout.decode().strip().splitlines()[-1])
    except Exception:
        return limit
def slow(p):
    return bool(p.rules) and runtime(p) > 2.0
print("start runtime k=30: %.2fs" % runtime(prog))
small = shrink(prog, slow)
print("minimised program (still >2s at k=30):")
print(small.to_text())
for k in (3, 10, 30):
    child_k = child.replace("k=30", f"k={k}")
    t = time.time()
    out = subprocess.run([sys.executable, "-c", child_k], input=pickle.dumps(small), capture_output=True, timeout=60)
    print(f"  k={k}: {out.stdout.decode().strip().splitlines()[-1]}s")
pickle.dump(small, open("/tmp/case26_min.pkl", "wb"))
