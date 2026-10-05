# probfuzz-nesy

- `probfuzz/`      ProbFuzz (uiuc-arc/probfuzz, commit 2914413, MIT) ported to Python 3 and adapted to Scallop, DeepProbLog,
                   ProbLog and NeurASP; see `../REPORT.md` section 11. Run from this folder inside `../.venv`:
                   `python probfuzz.py 12 --template all --seed 11` (add `--special` for special constants).
                   Parser: `language/antlr/run.sh` regenerates it (ANTLR 4.7.2 jar from `~/.m2`, runtime `antlr4-python3-runtime==4.7.2`).
- `v1-inspired/`   first version, written from scratch with ProbFuzz as the idea only (has a neural template).
- Unused upstream leftovers in `probfuzz/`: `backends/{stan,edward,pyro}.py`, `driver.py`, `install*.sh`, the original templates.
