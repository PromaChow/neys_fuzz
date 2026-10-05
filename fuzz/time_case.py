import pickle, subprocess, sys, time
prog_path = sys.argv[1]
child = r'''
import pickle, sys, time
sys.path.insert(0, ".")
from scallop_fuzz import scallop_probs
prog = pickle.loads(sys.stdin.buffer.read()); k = int(sys.argv[1])
t = time.time(); scallop_probs(prog, provenance="topkproofs", k=k); print("%.3f" % (time.time() - t))
'''
data = open(prog_path, "rb").read()
for k in (3, 10, 20, 30, 40, 60):
    row = []
    for rep in range(3):
        try:
            out = subprocess.run([sys.executable, "-c", child, str(k)], input=data, capture_output=True, timeout=90)
            row.append(out.stdout.decode().strip().splitlines()[-1] + "s")
        except subprocess.TimeoutExpired:
            row.append(">90s")
    print(f"k={k:<3}", row, flush=True)
