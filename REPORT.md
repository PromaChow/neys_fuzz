# Fuzzing neurosymbolic frameworks by mutating the inputs of their own tests

> Round 1 (sections 1-8): mutating each framework's own tests. Round 2 (section 9): wrapper analysis, adopting the logical counterparts' tests, and differential fuzzing on new dimensions.

Everything here was produced in `nesy-fuzz/` on the local machine (macOS arm64, Python 3.11, nightly Rust).
Nothing has been reported upstream. Treat every finding as a candidate until a maintainer confirms it.

## 1. Process

1. **Run the original tests** of each framework and record the baseline.
2. **Extract the inputs** those tests use (programs, probabilities, queries, engine configuration).
3. **Mutate those inputs.** Expected values of the original tests stop applying after a mutation, so every
   mutation carries its own oracle (metamorphic relation, independent engine, invariant, or specification).
4. **Triage every anomaly** before counting it: harness defect, oracle limitation, or candidate bug.

## 2. Baseline (original tests, unmodified)

| Framework (shallow clone) | Result |
|---|---|
| DeepProbLog `f64181f` (2026-09-29) | 82 passed, 2 skipped |
| Scallop core, Rust `668bfb6` (2026-06-26) | 360 passed, 0 failed (+1 doctest, 3 ignored) |
| Scallop Python (`scallopy`) | 69 passed, 33 expected-fail, **12 failed** |
| NeurASP `b25598d` (2026-07-31) | **no unit tests exist** (only example scripts) |

The 12 `scallopy` failures are real at this commit: `PanicException: Cannot clone pointer into Python heap
without the thread being attached` (`etc/scallopy/src/foreign_predicate.rs:14`), in every batched forward test
that uses the default parallel dispatch; the `dispatch="single"`/`"serial"` variants pass. HEAD is the merge of
PR #59 "update-pyo3"; the clone is shallow, so I could not check whether that is the cause.
3 more `dbio` tests fail only when run from the wrong directory (they pass from the repo root).

## 3. Seeds extracted from the original tests

| Framework | Seeds | How |
|---|---|---|
| DeepProbLog | 50 records from 49 tests (29 without neural networks; 24 usable) | pytest plugin `fuzz/trace_dpl.py` records program text, engine, queries |
| Scallop | 277 programs from 62 Rust test files; 254 replay cleanly through `scli` (24 are probabilistic) | `fuzz/extract_scl_seeds.py` |
| NeurASP | none | no tests |

Coverage observation: Scallop's Rust tests use `UnitProvenance` 260 times but only 12 `minmaxprob`, 1 `topkproofs`,
1 `addmultprob`. None of the 9 differentiable provenance modules appears in `core/tests`; `scallopy` tests use 3 of them
and never check a gradient *value*. Its only disjunction tests give every alternative probability 1.0.

## 4. Mutation campaigns

| | DeepProbLog | Scallop |
|---|---|---|
| Seeds used | 24 | 254 |
| Mutants | 906 | 2,855 |
| Operators | probability (boundary/perturb/complement), reorder, duplicate rule, rename predicate, engine swap, invalid disjunction, invalid probability | reorder, duplicate rule, rename relation, probability, monotone raise, provenance swap, invalid probability |
| Oracles | metamorphic vs unmutated seed; ProbLog (independent exact engine); range invariant; Exact vs Approximate engine; spec (probabilities in [0,1]) | metamorphic vs unmutated seed; monotonicity; range invariant; crash/timeout; spec |

### Results

| Check | DeepProbLog | Scallop |
|---|---|---|
| reorder / duplicate non-probabilistic rule / rename | 0 violations in 351 | 0 violations in 2,220 |
| probability boundary / perturbation | 0 real mismatches in 310 (17 = ProbLog oracle limit, see 5) | 0 in 311 |
| exact vs approximate engine | 0 violations in 136 (1 zero-probability case, see F5) | n/a |
| monotonicity (raise one tag) | n/a | 0 violations in 125 |
| provenance swap | n/a | 0 failures in 103, 2 timeouts (F8) |
| **invalid probability / disjunction accepted** | **76 of 109 accepted while ProbLog rejects** | **94 of 94 accepted** |
| crash/compile error on a *valid* mutant | 0 | 0 |

## 5. Triage record (what was NOT a framework bug)

Each item below looked like a finding and was resolved as a harness or oracle problem. They are listed because the
same classes of mistake would be made again by anyone repeating this.

| Looked like | Actually | Fix |
|---|---|---|
| group probabilities summing to 1.0001 | my generator rounded up | floor instead of round; oracle asserts sum <= 1 |
| `UnknownClause` for relations with no clauses | Prolog rejects undefined predicates (my shrinker deleted all facts) | declare empty predicates; shrinker keeps exception type |
| `KeyError` / `MemoryError` in approximate engine | left-recursive programs loop in SLD proof search; also see F6 | approximate engine skipped on cyclic programs |
| `equal(dummy,dummy)` ProbLog=1.0 vs DeepProbLog=0.0 | my oracle matched results to queries by predicate name | compare by ground term |
| duplicate-rule changed `a(2)` 0.4 -> 0.64 | duplicating a *probabilistic* rule makes two independent choices | operator now duplicates only non-probabilistic rules |
| 16 `oracle_mismatch` at probabilities 1e-10..1e-12 | **ProbLog** returns 0.0 for tiny probabilities; DeepProbLog is right | reclassified as oracle limitation |
| non-ground query missing answers at `k=1` | approximate engine with k=1 keeps one proof | not a finding |
| 11 Scallop metamorphic violations | opaque entity handles (`0x1edb...`) depend on interned program text | handles masked before comparing |
| "disjunction above 1" operator produced valid input | my operator did not guarantee the sum | now forces the sum to 1.3 |
| minimized perf case "slow" | my timer ran while other jobs loaded the CPU | retracted; re-measured on a quiet machine |

## 6. Candidate findings

Tags: **[M]** found by mutating the tests' inputs; **[R]** found earlier by random program generation with an
exact possible-worlds oracle (`fuzz/nesy_prog.py`, cross-validated against ProbLog: 132 programs, max difference 5.6e-16).

| # | Framework | Finding | Evidence | Strength |
|---|---|---|---|---|
| F1 | DeepProbLog | **Missing input validation.** Probabilities outside [0,1] and disjunctions summing above 1 are accepted; answers up to 4.0 and -0.5 are returned. ProbLog raises `InvalidValue` for the same programs. | [M] 76 of 109 invalid mutants; standalone check in this session | strong, low severity |
| F2 | Scallop | **Tags outside [0,1] accepted** by `minmaxprob`, `addmultprob`, `topkproofs` and propagated to outputs (e.g. tag 2.0). | [M] 94 of 94 | strong; I found no validation and no documented requirement in the docs pages I read |
| F3 | Scallop | **Mutually exclusive facts are mishandled.** Default `topkproofs` treats `{0.0313::a(1); 0.392::a(0); 0.4039::a(2)}` as independent (0.6489, expected 0.8272). `--wmc-with-disjunctions` returns **1.0**, impossible since "none holds" has probability 0.1728. Of 150 random programs with disjunction groups, 16 mismatch the oracle without the flag and 46 with it (47 programs had at least one mismatch). | [R] `repro/disjunction_exists.scl` with native `scli`, `fuzz/repro_disjunction.py`; also consistent with issue #64 | strong |
| F4 | DeepProbLog | **Approximate engine loses a query when a probability-0.0 fact is on a proof path** with the `geometric_mean` heuristic (used by all 3 shipped examples). `0.0::z. 0.6::a. q :- a. q :- z.` gives exact 0.6, approximate: result absent. Works with `ucs`; works with 0.001. | [M] 1 case + [R] + `fuzz/repro_dpl_zero.py` | strong, standalone |
| F5 | DeepProbLog | Same zero-probability situation: gradient of the zero fact is 0 instead of 1 in the approximate engine. | [R] | medium |
| F6 | DeepProbLog | Approximate engine omits underivable queries from the result; exact engine returns 0.0. | [R] 3-line repro | strong, low severity |
| F7 | NeurASP | `MVPP.inference_obs_exact` raises `TypeError` on any program; `MVPP.gradient()` returns wrong values (e.g. -2 vs +2) and has no callers. The training path matches the oracle on 100 independent-fact programs (values and `gradients_one_obs`) and on 100 disjunction programs (values only). | [R] | strong, likely dead code |
| F8 | Scallop | **Scalability cliff** in `topkproofs`: original test `test_min_max_with_recursion` takes 0.01s at k=3, 0.10s at k=10, >15s at k=30. A random 8-fact recursive program showed the same jump between k=10 and k=30. | single runs, opt-level-1 build | medium; may be inherent to top-k proofs |
| F9 | Scallop | 12 original `scallopy` tests panic at HEAD (PyO3 GIL), see section 2. | baseline | strong |

Not found: any correctness bug in DeepProbLog's `ExactEngine` values/gradients, any metamorphic violation in either
framework, any crash on a valid mutant, any monotonicity violation, any gradient-value or gradient-sign error in
Scallop's `difftopkproofs` (random campaign: 300 programs, half with negation, 30-50% boundary probabilities).

## 7. Limitations

* NeurASP has no tests, so it is outside the mutate-the-tests method; its results are the supplementary [R] ones.
* Only 24 of Scallop's 277 test programs are probabilistic, so probability mutations touch a small base.
* Scallop was built from a shallow clone with nightly Rust and `opt-level=1` (debug assertions on); timings are indicative.
* Scallop mutants are judged by invariants and metamorphic relations, not by an exact oracle, except in the [R] runs.
* The disjunction operator for Scallop rarely applied (no AD-sum mutants were produced in the final run).
* DeepProbLog mutants without a ProbLog-compatible program (tensor builtins, foreign predicates) have no exact oracle.
* Nothing has been checked against upstream issue trackers beyond Scallop #64 and DeepProbLog #17.

## 8. Layout and reproduction

```
frameworks/           shallow clones (scallop, deepproblog, NeurASP)
fuzz/trace_dpl.py     records DeepProbLog test inputs        fuzz/extract_scl_seeds.py   Scallop seeds
fuzz/mutate_dpl.py    DeepProbLog mutation + oracles          fuzz/mutate_scl.py          Scallop mutation + oracles
fuzz/nesy_prog.py     random programs + exact oracle ([R])    fuzz/scallop_fuzz.py, deepproblog_fuzz.py, neurasp_fuzz.py
fuzz/repro_*.py repro/*.scl                                   standalone reproductions
results/baseline/ results/seeds/ results/*.jsonl              raw outputs;  logs/  build and run logs
```

```bash
source .venv/bin/activate
# baseline
(cd frameworks/deepproblog && python -m pytest src/deepproblog/tests -q)
(cd frameworks/scallop && RUSTUP_TOOLCHAIN=nightly CARGO_TARGET_DIR=$PWD/../../.cargo-target cargo test -p scallop-core)
# seeds
(cd frameworks/deepproblog && PYTHONPATH=../../fuzz python -m pytest src/deepproblog/tests -q -p trace_dpl)
python fuzz/extract_scl_seeds.py
# mutation
python fuzz/mutate_dpl.py --per-seed 50 --rng 1 --out results/dpl_mutation_results_v2.jsonl
python fuzz/mutate_scl.py --unit-mutants 12 --prob-mutants 80 --rng 7
```


---

## 9. Round 2: libraries versus their logical counterparts

Pairs: **DeepProbLog <-> ProbLog** and **NeurASP <-> clingo**. ProbLog and clingo were cloned at repo HEAD
(`a294fa2`, `91f9045`); ProbLog is installed from that clone, so DeepProbLog runs on exactly the engine whose tests are adopted.
Version strings of the clones equal the pip releases (ProbLog 2.3.0, clingo 5.8.2), but the ProbLog code differs from the pip release in 3 engine files.

### 9.1 Is the neurosymbolic part just a wrapper?

| Evidence | DeepProbLog over ProbLog | NeurASP over clingo |
|---|---|---|
| Static | 18 of 32 files (73% of code lines) import ProbLog; `Semiring` and `GraphSemiring` extend ProbLog's semiring; it reuses ProbLog's `Term`, `LogicFormula` and `Clause` classes | `mvpp.py` 435 lines, only 9 of 30 functions call clingo; `neurasp.py` 500 lines, 2 of 11 |
| Dynamic (cProfile, network-free programs, 3 workloads) | **88% of CPU time in ProbLog**, 3.5-5.7% in DeepProbLog's own code | not profiled |
| Behavioural (adopted tests, 9.2) | 85% pass on the exact engine, 26% on the approximate one | 96% identical on plain ASP |
| Where it is NOT a transparent wrapper | ignores `evidence`, no `query/1` statements, aggregate builtins crash, own numerics, own approximate engine on SWI-Prolog | ASP choice rules crash its parser (6 of 150 programs); `sys.exit()` on valid string input (6 more) |

Verdict: for network-free logic, **DeepProbLog's exact engine is mostly ProbLog**, and NeurASP is a thin layer over clingo for model enumeration but owns the probability and gradient code. The neural part and the approximate engine are the parts that are not a wrapper.

### 9.2 The counterparts' tests, adopted

**ProbLog's 109 system-test programs** (`test/*.pl`, expected values read exactly as ProbLog's runner reads them). Baseline: ProbLog on its own tests with the `sdd` evaluatable passes **109/109**. (Its pytest suite fails 127 of 324 items here, 119 from the missing external compilers `dsharp`/`c2d`, and 8 MPE/explain/web/CLI items, not investigated; the `ddnnf` route is not used.)

| Engine | Pass | Fail | Inconclusive |
|---|---|---|---|
| DeepProbLog ExactEngine | **88 of 104 adoptable (85%)** | 16 | 5 |
| DeepProbLog ApproximateEngine (k=100, ucs) | 27 of 104 (26%) | 77 | 5 |

Why the exact engine fails (16): **9 programs use `evidence(...)`, which is silently ignored** (answers equal ProbLog's with the evidence lines deleted: e.g. burglary 0.7 instead of 0.9897); 3 aggregate-builtin programs crash with `TypeError: expected Tensor ... got float`; 3 non-ground-query programs return differently shaped answers; 1 expected error (`NonGroundQuery`) is not raised. The 5 inconclusive programs give queries as rules (`query(p(X)) :- a(X).`) or in consulted files, which my harness cannot ask.
The approximate engine fails mostly through its embedded SWI-Prolog: 22 programs kill the worker (F18), 13 raise `SWIProgramException: Unhandled body type`, 10 raise `PrologError`.

**clingo's tests.** Only **10 of clingo's 114 test programs are plain ASP**; the other 104 use `#script` to test clingo's Python/Lua API (propagators, observers) and cannot be adopted. I therefore also used the plain programs in `examples/` (155 in total, 150 usable): NeurASP's `MVPP` returns **identical answer sets for 144 (96%)**. Failures: 6 programs with ordinary ASP choice rules (`1 { p(X); q(X) } 1 :- ...`) crash with `IndexError` (its probabilistic-rule regex matches them; minimal repro `1 { a; b } 1.`, `fuzz/repro_neurasp_parse.py`); in the string-input path 6 more valid programs end the process with `sys.exit()` (e.g. one ending in a line comment).

### 9.3 Differential fuzzing on fixed dimensions

I chose five dimensions that, to the best of my searches (not exhaustive), no paper varies for neurosymbolic libraries against their counterparts. They come from thresholds and tests found in the libraries' own code: ProbFuzz defined special values (0, 1, epsilon, tiny) and its paper describes boundary-value generation, but the released generator leaves the flags off, and DeepProbLog's hand-written regression tests cover only 1e-8..0.3 on one engine.

| Dim | What varies | Oracle |
|---|---|---|
| D1 | probabilities at, below and above each internal threshold (1e-5, 1e-6, 1e-9, 1e-12, float32 limits) | exact rational arithmetic on the same decimal text |
| D2 | disjunction group: size 2-100 x sum slack (valid and above 1) x zero-probability member | closed form; validity |
| D3 | conjunction and disjunction chains of 1-100 facts | closed form |
| D4 | batching, order, duplicates, repeated call, cache | the same engine in batch mode |
| D5 | the same distribution via a neural predicate or via literal facts, logit gap 0-200 | float64 softmax |

Run: 162 generated cases x 4 systems (ProbLog sdd, DeepProbLog exact, DeepProbLog approximate, NeurASP) + D5 + 65 programs for D4.

### 9.4 New candidate findings (round 2)

| # | Where | Finding | Strength |
|---|---|---|---|
| F10 | DeepProbLog | `evidence(...)` in a ProbLog program is silently ignored (9 of 11 evidence tests; unconditional probabilities returned) | strong |
| F11 | DeepProbLog | ProbLog aggregate builtins crash with `TypeError: expected Tensor ... got float` (3 tests) | strong |
| F12 | NeurASP | Valid ASP choice rules crash the parser (`IndexError`); valid string programs can trigger `sys.exit()` | strong, minimal repros |
| F13 | ProbLog and DeepProbLog | **Different silent cutoffs for tiny probabilities.** ProbLog's SDD route returns 0.0 below 1e-9 (`SemiringLogProbability.value`, `evaluator.py:288`). `Constant.FLOAT_PRECISION = 15` (`logic.py:897-901`) rounds every float literal to 15 decimals, so DeepProbLog returns `5e-16 -> 1e-15`, `1.4e-15 -> 1e-15` and `<5e-16 -> 0.0`. Sweep: `fuzz/sweep_tiny.py` | strong, code located |
| F14 | DeepProbLog | **Neural and literal paths disagree for the same distribution.** gap 20: neural 1.0 vs exact 1-2e-9 (float32), literal correct; gaps 40-80: literal loses the value (rounding), neural keeps it; gap 100: neural wrong (subnormal) | strong |
| F15 | DeepProbLog approx | With the `geometric_mean` heuristic a saturated network (exact 0.0 output, gap >= 104) makes the query vanish: F4 reached through a realistic neural scenario | strong |
| F16 | all three | Over-sum disjunction groups: ProbLog rejects with a tolerance that **varies with the group's shape** (1e-12 over-sum: rejected at n=2, rejected at n=5 only when a member has probability 0, accepted at n>=20); DeepProbLog and NeurASP never reject | medium |
| F17 | NeurASP | float32: `1 - 1e-9` rounds to 1.0, long chains underflow (n>=60 at p=0.1), subnormals lose precision | medium, expected from dtype |
| F18 | DeepProbLog approx | **A Prolog error poisons the process:** after one failing model, the *next valid* run kills the whole interpreter with exit status 4 when stdin is closed (SWI-Prolog's toplevel reads EOF) and hangs when stdin is open. 22 of 109 adopted programs crashed the worker this way. `fuzz/repro_swi_state.py after_failure` | strong |

Negative results: D3 (DeepProbLog = ProbLog down to 1e-100), D4 (**no** violation in 65 programs: exact engine is invariant to batching, order, duplicates, repeated calls and cache).

### 9.5 Triage record for round 2 (not framework bugs)
Missing external compilers (dsharp) made 119 ProbLog pytest items fail; empty query list for error-expected programs; relative paths in `consult`/`extern` programs; asking for a ground instance of a query written non-ground; regex extraction of `query(...)` broke some programs (fixed by using ProbLog's parser); `WorkerCrash` was first attributed to the program shown, but each program alone only raises `PrologError`; a `stdin` hypothesis for the crash was half right (exit 4 on closed stdin, hang on open stdin).

### 9.6 Limits of round 2
* Adopted-test counts depend on my query extraction; 5 programs are inconclusive and 3 "shape" failures are not fully characterised.
* ProbLog's pytest baseline is incomplete here (external compilers and a MaxSAT binary missing).
* D5 uses one two-valued stub network; D1-D3 use small closed-form programs, not mutated test programs.
* Dimension novelty claims rest on my searches only.
* NeurASP was tested through its `MVPP` class, not through full neural training.

### 9.7 New files
`fuzz/adopt_problog_tests.py`, `adopt_clingo_tests.py`, `diff_fuzz.py`, `invariance_dpl.py`, `summarize_adoption.py`, `wrapper_profile.py`,
`sweep_tiny.py`, `repro_neurasp_parse.py`, `repro_swi_state.py`; results in `results/adopt_*.jsonl`, `diff_fuzz.jsonl`, `invariance_dpl.jsonl`, `baseline/problog_full.xml`.


---

## 10. Round 3: a second search for bugs

New dimensions and oracles: provenance consistency across Scallop's evaluation modes, a grammar sweep of NeurASP's front end against clingo, Scallop versus clingo on deterministic programs with aggregates, negation and arithmetic, gradient self-consistency of every differentiable provenance, and the PyTorch MNIST-sum pattern with exact closed forms.

### 10.1 New candidate bugs (Scallop)

| # | Finding | Evidence | Strength |
|---|---|---|---|
| F19 | **`proofs` provenance panics on negation and every aggregate.** `ProofsProvenance::negate` is `panic!("Not implemented")` (`discrete/proofs.rs:210`); `not`, `count`, `sum`, `min`, `exists`, `string_join` all panic at run time instead of a compile-time "unsupported" error. 40 of the 254 test programs hit it. | provenance-consistency sweep, 2,286 runs; minimal programs listed | strong |
| F20 | **A guard in the same rule body does not protect a division or modulo.** With `a = {0, 3}`, `rel dv(x / y) = a(x), a(y), y != 0` panics (`attempt to divide by zero`, `environment.rs:393`; `%` at `:425`), in **release** builds too. Moving the guard into a helper relation works; clingo handles the guarded rule. `i32::MIN / -1` and unguarded division also panic. | Scallop-vs-clingo fuzz (39 of 300 programs), minimal repro, release build | strong |
| F21 | **Inconsistent integer-overflow policy, undocumented and untested.** `+` and `-` saturate for all 12 integer types; `*`, `/`, `%` use the plain operator (release: `100000 * 100000 = 1410065408` wraps; debug: panics). `2147483647 + 1` stays `2147483647`; clingo wraps. The changelog says overflow behaviour was "unified". | code count per operator plus release-build probes; no docs or tests mention it | medium (policy inconsistency, not a wrong answer by spec) |
| F22 | **Two categorical (disjunctive) inputs through `forward_function` give all zeros.** `InputMapping.process_tensor(..., mutual_exclusion_counter=None)` makes a fresh `Counter()` per relation (`input_mapping.py:103-104`) and `forward.py` never passes the context's counter, so both relations get disjunction id 0 and every join between them looks mutually exclusive. Minimal case, exact `[0.28, 0.54, 0.18]`: shipped `[0,0,0]`; with a shared counter `[0.28, 0.4896, 0.18]`; with the counter fix and `wmc_with_disjunctions=True` `[0.78, 0.89, 0.73]` (impossible). **No configuration gives the exact answer.** `fuzz/repro_scallopy_disjunction_ids.py` | root cause located in code, fix verified | strong |

F22 combines with F3: the default weighted model count ignores exclusivity and the flag that should fix it overcounts.

### 10.2 Observations that are not bugs
* `diffaddmultprob` gradients differ from the numerical gradient of the same forward function in 83 mismatching (output, input) pairs. 77 are saturated outputs and 4 more are saturated *intermediate* sums; the Scallop paper defines `clamp` as keeping the unclamped gradient, so this is the documented straight-through gradient.
* The Python-implemented `*2` provenances return output tensors with no gradient graph for underivable tuples (19 of 80 programs raise on `autograd.grad`).
* `diffminmaxprob`, `diffmaxmultprob` and `diffnandminprob` do not compute the categorical sum, by design.

### 10.3 Negative results (these bugs were looked for and not found)
* **Provenance consistency:** 2,286 runs (254 programs x 9 settings): no tuple-set difference from `unit` on monotone programs, no out-of-range tag.
* **Scallop vs clingo:** 1,000 random deterministic programs (joins, recursion, negation, comparisons, +, -, *, aggregates `count/sum/min/max/exists/forall`, group-by): identical. 15 edge probes (empty aggregates, duplicates, negative division and modulo) identical.
* **Gradients:** `diffmaxmultprob`, `diffnandmultprob`, `difftopkproofs`, `difftopbottomkclauses` match finite differences on 80/80 random programs.
* **PyTorch interface:** batched results equal one-sample-at-a-time results (diff 0.0) for six provenances in `serial` and `single` dispatch; one-hot (saturated) input rows are exact.
* **NeurASP grammar sweep:** 799 valid random ASP programs (23 constructs, 7 formatting styles): only the known leading-digit choice-rule defect (F12) appeared.

### 10.4 Triage record for round 3
`neg_agg` template named a predicate differently in the two languages (my error); my first panic grouping recorded the trailing backtrace hint instead of the message; an unsafe ASP template produced noise; two min/max "mismatches" were finite-difference steps crossing a kink (probabilities 0.001 apart); the `diffaddmultprob` mismatches were first suspected as bugs and then traced to the documented clamp rule.

### 10.5 Limits
Scallop was built from a shallow clone; a release `scli` build (`.cargo-target-release`) was used only to confirm the overflow and division probes. Random generators use small domains. F22 was tested on `difftopkproofs` and a two-valued/ten-valued case only.

### 10.6 New files
`fuzz/prov_consistency.py`, `neurasp_syntax_fuzz.py`, `scallop_vs_clingo.py`, `diff_prov_grad.py`, `scallopy_mnist_sum.py`, `repro_scallopy_disjunction_ids.py`; results in `results/prov_consistency.jsonl`, `neurasp_syntax_fuzz.json`, `scallop_vs_clingo.json`.

## 11. Round 4: ProbFuzz adapted to neurosymbolic libraries (`probfuzz-nesy/`)

`probfuzz-nesy/probfuzz/` is the source of ProbFuzz (uiuc-arc/probfuzz, commit `2914413`, MIT) ported to Python 3 and
adapted. Kept from upstream: the ANTLR grammar `Template.g4` (extended), the populator/listener/checker/visitor
architecture, template holes (`CONST`, `DISTX`, `DIST`, data), `models.json` with the filter that keeps only
distributions every enabled tool supports, the `structured` validity check with regeneration, `config.json` with one
entry per tool and algorithm, per-program output files, and a `summary.csv` with Crash/Num/Acc flags and SMAPE. Changed:
the grammar gains `rule ... :- ..., not ...` and the distributions `bernoulli` and `categorical` (a prior
`e := bernoulli(CONST)[n,n]` is a relation with n*n independent probabilistic facts, `d := categorical(CONST,CONST,CONST)`
one mutually exclusive group); the backends are Scallop (`topkproofs`, and with `wmc_with_disjunctions`), DeepProbLog
(exact, approximate), ProbLog and NeurASP, and the reference is an exact possible-worlds oracle (`fuzz/nesy_prog.py`)
instead of agreement between systems; special constants (`--special`: 0, 1, 1e-12, 1e-9, 1e-6, float32 epsilon, 1e-5,
1-1e-5, 1-1e-9) are wired in, while the released upstream code defines the flag (`generate_special_params`) but leaves it off and never reads it (the paper, sec. 4.2, describes boundary-value generation as a strategy with a developer-set probability). The paper also has an exact-result checker (programs translated to PSI, sec. 4.4), so an exact oracle is not new to ProbFuzz; what is new here is applying it to discrete neurosymbolic programs, where it scales to all generated programs. Not
adapted: the continuous distributions, `observe`/`if`, the data-generating metrics and the Stan/Edward/Pyro backends
(left in the folder, unused). The first version of this round, written from scratch with ProbFuzz only as the idea, is
kept in `probfuzz-nesy/v1-inspired/` (same findings, plus a neural template that the port does not have yet).

Eight templates (`language/templates/`): reach (recursive), chain, noisy-or, join, negation, one and two disjunction
groups, diamond. Two campaigns, 12 programs per template (96 each), all 6 configurations plus the oracle:

| Run | Scallop topk | Scallop wmcdisj | DPL exact | DPL approx | ProbLog | NeurASP |
|---|---|---|---|---|---|---|
| baseline (seed 11) | 9 timeouts | 9 timeouts, **24 wrong** | 0 | 12 crash | 0 | 10 timeouts |
| `--special` (seed 12) | 6 timeouts | 6 timeouts, **24 wrong** | 0 | 11 crash, **4 wrong** | 0 | 11 timeouts |

Triage. *Wrong*: Scallop `wmc_with_disjunctions` on both disjunction templates, 12 of 12 each time (F3); DeepProbLog
approximate with an exact-zero fact in all 4 cases (F4), which appears only with `--special`, as in the earlier run.
*Crash*: DeepProbLog approximate on every negation program, the `PrologError` of F23 (11 of 12 with special values; the
12th produced a result that matches). *Timeouts* are not wrong answers: Scallop `topkproofs` (k=300) on the dense
recursive graph (`reach`, 3 constants, 9 facts) and NeurASP's exhaustive stable-model enumeration on `join` and `diamond`
once the program has about 18 facts or more; both limits are expected from the algorithm and were not seen in the
earlier round only because its programs had at most 8 facts. ProbLog, DeepProbLog exact and Scallop `topkproofs`
(where it finishes) agreed with the oracle on every program.

No new defect beyond F3, F4 and F23. The Acc flag ignores absolute differences below 1e-9, so tiny-probability behaviour
(F13) is not visible here. All facts of one relation share a probability, which is how upstream's vector priors work and
covers less than the per-fact values of the earlier round. 96 programs per run, one seed each. Nothing reported upstream.

Reproduce (from `probfuzz-nesy/probfuzz`, inside `../../.venv`, ANTLR runtime 4.7.2): `python probfuzz.py 12 --template all
--seed 11` and `... --special --seed 12`. A bug found while writing this: the runner numbered output files with a global
counter while the summary looked for the per-template index, which made every tool look crashed on the first run; fixed.

## 12. Round 5: LTNtorch and LNN (fuzzy-logic frameworks)

`frameworks/LTNtorch` (`d1bd981`, 2024-10-02) and `frameworks/LNN` (IBM, `c88f513`, 2026-09-09) were cloned (shallow) for this
round. Both compute **truth degrees in [0,1]** with fuzzy-logic formulas, not probabilities, so the oracle of the earlier rounds
(possible worlds) does not apply. The references used instead are the closed formulas printed in the libraries' own docstrings
(LTN: `fuzz/ltn_oracle.py`), interval Lukasiewicz arithmetic and classical truth tables (LNN), brute-force evaluation of
quantified formulas, and the two libraries against each other. Environment note: LNN's `pyproject.toml` asks for numpy >= 2.4.3
and torch >= 2.13; it was run on the project's numpy 1.26.4 / torch 2.2.2 (its 117 tests pass there), so findings that depend on
those pins are not excluded.

### 12.1 Baseline and dimensions

| Dimension (as in earlier rounds) | LTNtorch | LNN |
|---|---|---|
| Baseline, original tests | 11 passed (`tests/tests.py`) | 117 passed, plus 15 `def test()` functions that its pytest config (`python_functions = "test_*"`) never collects (all 15 pass when called) |
| Mutate the inputs of the library's own tests | `fuzz/trace_ltn.py` records the operator calls made by the original tests (105 unique calls from `test_Connective`, `test_Quantifier`); `fuzz/ltn_mutate.py` makes 3,810 mutants (boundary, perturb, complement, permute, swap, stable flag, float64) | `fuzz/mutate_lnn_tests.py` (pytest plugin) re-runs all 132 tests with the data they give to `Model.add_data` changed (boundary, perturb, complement, reorder); see 12.7 |
| Random programs against an exact oracle | `fuzz/ltn_fuzz.py`: 15 connective variants, 6 aggregator variants, 3 seeds x 10,359 checks, 341 properties; `fuzz/ltn_quant.py`: random quantified formulas (1-3 variables, guarded or not) against a loop evaluation | `fuzz/lnn_fuzz.py`: interval semantics, classical completeness, soundness with partial knowledge, first-order, learning; 3 seeds, 8,243 checks |
| Counterpart | LTN against LNN on random Lukasiewicz formulas (`fuzz/ltn_vs_lnn.py`, 1,342 formulas, 3 seeds) | same |
| Special values and thresholds | the library's own eps = 1e-4 projection, values around it, float32 vs float64, bool/int/half inputs | 0, 1e-12..1-1e-9, 1 as truth values |
| Neural saturation | sigmoid predicate, logit scale 0..200: value and gradient finite and equal to float64 (`fuzz/ltn_nn.py`, 80 checks, 0 failures) | not applicable |
| Evaluation-mode invariance | individual order, repeated calls, batch against one-at-a-time (540 checks, 0 failures) | order of added data, repeated `infer()`, `flush()` and reload (0 failures) |
| Termination | not applicable | `infer()` run under an alarm |

### 12.1b LNN's own tests with changed inputs
All 132 tests (117 collected + the 15 uncollected, run with `-o python_functions="test test_*"`) were run under `NESY_LNN_MUT`
settings: boundary (seeds 1-3), perturb (seeds 1-3), complement (seed 1), reorder (seed 1), plus two unchanged runs. The
tests' assertions encode the original expected values, so an `AssertionError` after a change is expected and not a finding.
Findings are: an exception that is not an `AssertionError`, an inference that does not finish in 8 s, a bound that is not finite
or outside [0,1], a lower bound above the upper bound (beyond 1e-4) that is not reported as a contradiction, and, for `reorder`,
bounds that differ from the unchanged run (compared only for the 77 tests whose two unchanged runs agree).

| Run | assertion (expected) | pass | non-assertion exception | hang |
|---|---|---|---|---|
| boundary 1 / 2 / 3 | 68 / 60 / 59 | 62 / 68 / 69 | 2 / 2 / 2 | 0 / 2 / 2 |
| perturb 1 / 2 / 3 | 46 / 43 / 45 | 83 / 84 / 85 | 1 / 2 / 1 | 2 / 3 / 1 |
| complement 1 | 80 | 47 | 2 | 3 |
| reorder 1 | 0 | 132 | 0 | 0 |

(The "non-assertion exception" column is made up entirely of the broken failure message described below; hang counts are test hangs, plus one more at import time in `perturb 2`.)

* **14 hangs** (13 in 5 tests plus 1 at import): `test_american::test_1`, `::test_2` and `test_nested_quantifiers` (3 tests) all use
  quantified first-order formulas; the stack is in `Model._infer` (`model.py:501`) and the grounding manager (`_gm.py`). The same
  tests finish in under a second with the original data. `test_Xor_1.py` runs inference at import time; with perturbed data it hangs,
  which led to the minimal XOr repro (F33). Reproducible: from `frameworks/LNN`,
  `NESY_LNN_MUT=perturb:1 PYTHONPATH=.:../../fuzz python -m pytest tests/reasoning/logic/fol/test_american.py -p mutate_lnn_tests -o addopts=` hangs (seeds perturb 1-4, 6 and boundary 2 do; 3 and 5 do not).
* **12 exceptions are not library defects**: `TypeError: list indices must be integers or slices, not tuple` in `gm/test_bool_and_2.py`
  and `gm/test_bool_and_3.py` comes from the failure message `{TT[:,row]}` in the tests' own `assert`, which cannot be built; the tests raise
  `TypeError` instead of reporting the failed check (they are reclassified as assertion failures).
* **0 order dependence** among the 77 tests with repeatable results. (A first aggregation showed 457 order differences; they were
  artefacts of comparing grounding rows by position and of two tests that draw random numbers, and were removed by comparing sorted rows
  and requiring two identical unchanged runs.)
* **No invariant violations** (non-finite or out-of-range bounds). One float32 case in the unchanged run, `learning/propositional/test_bool_and_1.py::test_multiple`
  (a 100-operand conjunction), has lower 1.0 > upper 0.9999978 (2e-6) without a contradiction flag; the threshold was raised to 1e-4 for such accumulation.
* Test-suite observations: 15 files define `def test()` which pytest never collects; `test_Xor_1.py` has no assertion; three Lukasiewicz grid tests check only one side.

### 12.2 Candidate findings

| # | Library | Finding | Evidence | Strength |
|---|---|---|---|---|
| F24 | LTNtorch | **`ImpliesGoguen()` with its default `stable=True` scores a satisfied implication as about 0.** Documented formula: 1 if x <= y. With the documented input projection pi_0, false -> false evaluates to 0.0 at (0,0), 0.0099 at (1e-6,1e-6), 0.5 at (1e-4,1e-4), 0.909 at (1e-3,1e-3); reflexivity, ex falso and the Boolean truth table fail by up to 1.0. `stable=False` and every other implication are correct. The same cause breaks `Equiv(AndProd, ImpliesGoguen)` reflexivity. | `fuzz/repro_ltn_goguen_stable.py`; 60 of 60 trials in each of 3 seeds | strong (documented projection, undocumented size of the deviation) |
| F25 | LTNtorch | `Quantifier([] , formula)` is accepted and returns a scalar that still claims the free variables `['x','y']`. | `fuzz/repro_ltn_forall_empty.py` | medium |
| F26 | LTNtorch | dtype inconsistencies: a guarded quantifier returns float64 while an unguarded one returns float32 (`output.double()` in `Quantifier.__call__`); masked `AggregMin` returns float64; `NotGodel` returns float32 for float64 input. | same script; 85-94 of 180 quantifier checks per seed | low |
| F27 | LTNtorch | the *unstable* operators give **NaN** gradients at boundary points (`ImpliesGoguen(stable=False)` at (0,0) and (0,1); `AggregPMean(stable=False)` on all zeros; `AggregPMeanError(stable=False)` on all ones). The documentation says "vanishing gradients". The stable versions are finite everywhere. | `ltn_fuzz.py` grad group | low (documented unstable) |
| F28 | LNN | **`Model.infer()` never returns** when a quantified formula is added with `add_knowledge()`: 5 of 8 single-quantifier cases (Exists with TRUE, one FALSE or bounds; Forall with one FALSE, all FALSE or bounds), all 8 return with `set_query()`. The documentation example uses `add_knowledge` for the query. Cause: the quantifier neuron is rebuilt on every pass and reports its full bound as a new update each step (the reported updates grow by 1.0 per step), so `bounds_diff <= 1e-7` is never reached. | `fuzz/repro_lnn_exists_hang.py`, `results/lnn_termination_table.txt` | strong |
| F29 | LNN | **Two structurally identical sub-formulas built as separate objects are one graph node (`Formula.__eq__`/`__hash__` compare `structure`) but the second object is never updated.** `And(Or(a,b), Or(a,b))` with a=TRUE, b=FALSE gives [0,1] UNKNOWN (one shared object gives [1,1]); the duplicate can arise implicitly through `Iff`/`XOr` (`And(Iff(a,b), Implies(b,a))`); `Implies(And(a,b), And(a,b))` with a=0.9, b=0.8 never returns. With every leaf given as TRUE/FALSE, all 14 classical-completeness failures in the 3 seeds contain such a repeat (11 an explicit repeated sub-formula, 3 a repeat introduced by `Iff`'s expansion, e.g. `Implies(Iff(b,a), Implies(b,a))`); none of the other 677 random formulas fails. Against LTN: 0 of 1,304 formulas without a repeated sub-formula differ, 13 of 38 with one. | `fuzz/repro_lnn_duplicate_subformula.py`, `ltn_vs_lnn.py` | strong |
| F30 | LNN | `And(A)`, `Or(A)`, `XOr(A)` (one operand; the signature accepts "any number") pass `add_knowledge` and `add_data` and raise `IndexError` in `infer()`. | `fuzz/repro_lnn_unary_connective.py` | strong, minimal |
| F31 | LNN | The documented square/rectangle example (`docsrc/.../reasoning.md`) infers nothing: 1 step, 0 facts, query UNKNOWN. The library's own test needs `world=World.AXIOM` and `set_query`. | `fuzz/repro_lnn_docs_example.py` | medium (documentation) |
| F33 | LNN | **`XOr` with three operands: `infer()` never returns** when the formula is asserted TRUE, one operand is TRUE and another is 0.999 (with 1.0, with 0.9, or with two operands it returns in 2 steps). Found by changing the data of `test_Xor_1.py`. | `fuzz/repro_lnn_xor_hang.py` | strong, minimal |
| F34 | LNN | **Data-dependent non-termination of first-order inference in the library's own tests** (5 tests, 13 of 35 changed test runs (5 tests x 7 changed runs); see 12.1b). | `mutate_lnn_tests.py`, `run_lnn_test_mutation.py` | medium (not minimised) |
| F32 | LNN | Input validation: invalid bounds raise `IndexError` (a value error), `And()` with no operand and two propositions with the same name are accepted silently. | `ltn_fuzz`/`lnn_fuzz` input group | low |

Design observations that are **not** counted as defects: LNN's `XOr(a,b)` is (a or b) and not (a and b), i.e. min(a+b, 2-a-b), not |a-b|;
a CLOSED-world predicate is not propagated to the enclosing quantifier or connective (their own OPEN world decides); LNN's
contradiction detection and inference are incomplete (3-4 of about 15-24 inconsistent random knowledge bases are not flagged; 21-50 entailed values
per seed are left UNKNOWN); learned weights are clamped to [0, w_max], not [0,1]; `NotGodel` and `ImpliesGodel` have no gradient path
(step functions).

### 12.3 Negative results (looked for, not found)
* LTNtorch: all 15 connective variants equal their documented formulas (conn_formula, 3 seeds x 60 cases each, tolerance 3e-6); range,
  commutativity, monotonicity, De Morgan duals, implication-as-disjunction, modus-ponens soundness all hold (the stable variants within
  the documented 3e-4 projection); all 6 aggregators equal their formulas, with masks, dims and keepdim; permutation invariance and
  monotonicity hold; 540 random quantified formulas (plain and guarded) equal the loop evaluation (the first run showed 2 mismatches, both
  float32/float64 branch flips at a tie of a discontinuous Godel operator, fixed in the oracle); stable operators have finite gradients
  at every boundary tried; autograd equals finite differences at interior points; saturation and invariance 0 failures; the 3,810 test-input mutants
  gave no formula mismatch (only the `NotGodel` dtype of F26).
* LNN: upward And/Or/Not/Implies equal interval Lukasiewicz (point and interval inputs, 2-5 operands); with all leaves classical every
  node is classical when no sub-formula is repeated; derived bounds are sound (contain every consistent classical world); open-world first-order
  semantics match brute force; the order of data, repeated inference and flush/reload do not change results; learning keeps parameters finite
  and within [0, w_max].
* LTN against LNN on Lukasiewicz formulas without repeated sub-formulas: identical in 1,304 of 1,304.

### 12.4 Triage record (not defects)
Float32/float64 branch flip of Godel operators in my quantifier oracle (2 early mismatches, now excluded when operands are within 1e-6);
the Goguen reflexivity law is false for S-implications (Kleene-Dienes, Reichenbach), so it is only checked for residuated ones;
`NotGodel`/`ImpliesGodel` are not differentiable by design; my first LNN XOr oracle (|a-b|) and first weight bound ([0,1]) were wrong;
single-run LNN hangs reproduced only after confirming the same program returns under `set_query`.

### 12.5 Limits
One library version each; LNN on a numpy/torch older than its pins; LNN's CLOSED-world and learning behaviour were only probed lightly; no
`ltn.diag` or `SatAgg` training loops beyond the saturation experiment; the LNN seed mutation of its own tests was approximated by two-sided
special-value grids; nothing has been reported upstream.

### 12.6 New files
`fuzz/ltn_oracle.py`, `ltn_fuzz.py`, `ltn_quant.py`, `ltn_mutate.py`, `trace_ltn.py`, `ltn_nn.py`, `lnn_fuzz.py`, `ltn_vs_lnn.py`,
`lnn_termination_table.py`, `repro_ltn_goguen_stable.py`, `repro_ltn_forall_empty.py`, `repro_lnn_exists_hang.py`,
`repro_lnn_duplicate_subformula.py`, `repro_lnn_unary_connective.py`, `repro_lnn_docs_example.py`; results in `results/ltn_fuzz_s{0,1,2}.jsonl`,
`ltn_mutation_results.jsonl`, `ltn_nn_fuzz.jsonl`, `lnn_fuzz_s{0,1,2}.jsonl`, `lnn_termination_table.*`, `results/seeds/ltn_seeds.json`, `baseline/ltntorch.log`, `baseline/lnn.log`.
