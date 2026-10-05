# ProbFuzz-NeSy

ProbFuzz (Dutta et al., ISSTA 2018, uiuc-arc/probfuzz) tests probabilistic programming systems by completing the
holes of a template, translating the program to each system and comparing the results. This folder adapts that
design to the neurosymbolic libraries fuzzed in `../` (Scallop, DeepProbLog, NeurASP, plus ProbLog as a logical
counterpart), and replaces ProbFuzz's "systems agree" oracle with an exact possible-worlds oracle.

| ProbFuzz | here |
|---|---|
| template with holes (distribution, parameter, data) | `templates/*.tmpl`: holes for domain size, fact count, fact probability, disjunction group size and slack, network output distribution |
| per-system translator (Stan, Edward, Pyro) | `backends.py`: Scallop (topkproofs, +`wmc_with_disjunctions`), DeepProbLog (exact, approximate), ProbLog, NeurASP MVPP; neural: `forward_function` vs DeepProbLog `nn(...)` |
| oracle: SMAPE between systems | exact enumeration oracle (`../fuzz/nesy_prog.py`) and SMAPE; pairwise disagreement is tallied separately |
| special values defined but never generated | `--special RATE` turns them on; `--special 0` is the ordinary-values baseline |
| none | greedy shrinking of every untagged mismatch; `known:` tags for deviations already triaged in `../REPORT.md` |

Run (from this folder, inside `../.venv`):

    python run.py --n 40 --special 0.0 --seed 1      # baseline
    python run.py --n 40 --special 0.4 --seed 2      # special values on

Output: `results/*.jsonl` (one line per non-ok system run), `results/*.summary.json`, stdout tally.
`repro_dpl_approx_negation.py` is the minimal repro of the one new candidate (see REPORT section 11).
