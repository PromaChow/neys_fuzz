import random, sys, time, subprocess, pickle, json
from nesy_prog import gen_prog
rng = random.Random(0)
for i in range(27):
    prog = gen_prog(rng, allow_neg=False, allow_groups=False, boundary_rate=0.3)
open("/tmp/case26.pkl","wb").write(pickle.dumps(prog))
print(prog.to_text())
child = '''
import pickle, sys, time
sys.path.insert(0, ".")
from scallop_fuzz import scallop_probs
prog = pickle.load(open("/tmp/case26.pkl","rb"))
k = int(sys.argv[1]); prov = sys.argv[2]
t=time.time(); r = scallop_probs(prog, provenance=prov, k=k); print("OK", prov, "k=",k, "%.2fs"%(time.time()-t), {rel: len(v) for rel,v in r.items()})
'''
open("/tmp/child26.py","w").write(child)
for prov, k in [("topkproofs",1),("topkproofs",3),("topkproofs",10),("topkproofs",30),("topkproofs",100),("topkproofs",300),("minmaxprob",1),("addmultprob",1)]:
    t=time.time()
    try:
        out = subprocess.run([sys.executable,"/tmp/child26.py",str(k),prov],capture_output=True,text=True,timeout=40)
        line = [l for l in out.stdout.splitlines() if l.startswith("OK")]
        print(line[0] if line else f"FAIL {prov} k={k}: {out.stderr[-200:]}")
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT(>40s) {prov} k={k}")
