"""Sanity: replay the UNMUTATED seeds through the runner + ProbLog oracle. Any finding here is a harness defect."""
from mutate_dpl import *

if __name__ == "__main__":
    seeds = load_seeds()
    runner = Runner(30)
    bad = 0
    print(f"{len(seeds)} usable seeds")
    for s in seeds:
        got = runner.run("dpl", s["program"], s["engine"], s["queries"])
        orc = runner.run("problog", s["program"], s["engine"], s["queries"])
        m = {"engine": s["engine"], "input_valid": True, "expect": "oracle", "op": "seed"}
        f = judge(m, None, got, orc if orc["ok"] else None)
        if f:
            bad += 1
        print(f"[{s['id']:>2}] {s['test'].split('::')[-1][:44]:44s} dpl={'ok' if got['ok'] else got['error'][:30]:6s} "
              f"problog={'ok' if orc['ok'] else 'n/a: ' + orc['error'][:28]:6s} {'ok' if not f else 'FINDINGS ' + str(f[:2])}")
    print("unmutated seeds with findings:", bad)
