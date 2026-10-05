

All findings were located with a reproducible program; standalone repro scripts are linked where they exist.

### A. Wrong answers with no error 

| ID | Library | What goes wrong | Status |
|---|---|---|---|
| **F3** | Scallop | Mutually exclusive facts are treated as independent: the example above with probabilities 0.0313, 0.392 and 0.4039 gives **0.6489 instead of 0.8272**. With the `wmc_with_disjunctions` flag it returns **1.0**, which is impossible. | repro: ([fuzz/repro_disjunction.py](fuzz/repro_disjunction.py)) |
| **F22** | Scallop (Python) | Two categorical inputs, such as two digit classifiers, through `forward_function` give **[0, 0, 0]** where the exact sum distribution is [0.28, 0.54, 0.18]. Each relation gets disjunction id 0, so every join looks mutually exclusive. No setting gives the exact answer. | repro: ([fuzz/repro_scallopy_disjunction_ids.py](fuzz/repro_scallopy_disjunction_ids.py)); root cause located |
| **F4** | DeepProbLog (approximate engine) | `0.0::z. 0.6::a. q :- a. q :- z.` : the exact engine gives 0.6, the approximate engine returns **no answer at all**. Happens with the `geometric_mean` heuristic and not with `ucs`. | repro: ([fuzz/repro_dpl_zero.py](fuzz/repro_dpl_zero.py)) |
| **F10** | DeepProbLog | `evidence(...)` from ProbLog programs is silently ignored: 9 of 11 evidence tests return unconditional probabilities (burglary 0.7 instead of 0.9897). | from adopted ProbLog tests |
| **F14, F15** | DeepProbLog | The same distribution gives different answers via a neural predicate or literal facts. A saturated network output (exact 0.0) makes the query vanish in the approximate engine. | from the neural-saturation experiment |

### B. Crashes and process-killers

| ID | Library | What goes wrong | Status |
|---|---|---|---|
| **F12** | NeurASP | Valid ASP choice rules such as `1 { a; b } 1.` crash the parser (`IndexError`), where clingo answers correctly. A valid program ending in a line comment makes NeurASP **terminate the whole process**. | repro: ([fuzz/repro_neurasp_parse.py](fuzz/repro_neurasp_parse.py)) |
| **F23** | DeepProbLog (approximate engine) | `0.5::a. 0.3::b. q :- a, \+b.` gives 0.35 on the exact engine and a `PrologError` on the approximate one. I found no statement that negation is unsupported. | repro: ([probfuzz-nesy/v1-inspired/repro_dpl_approx_negation.py](probfuzz-nesy/v1-inspired/repro_dpl_approx_negation.py)); may be an undocumented limit |
| **F18** | DeepProbLog (approximate engine) | After one failing run, the next valid run kills the interpreter (22 of 109 programs). | from adopted tests |
| **F19, F20, F9** | Scallop | The `proofs` provenance panics on negation and every aggregate; a division by zero panics even with a guard in the same rule; 12 original Python tests panic at the current commit. | sweep results |

### C. Accepting invalid input
- **F1, F2:** DeepProbLog accepts probabilities above 1 (76 of 109 invalid mutants) and returns answers like 4.0; Scallop accepts tags outside [0,1] (94 of 94). ProbLog rejects them.

### D. Smaller or probably expected
Tiny-probability cutoffs (F13), float32 limits (F17), inconsistent integer overflow (F21), a Scallop slowdown at larger
k (F8), different over-sum tolerance (F16), a zero-probability gradient and omitted underivable queries (F5, F6), a dead
NeurASP function (F7), aggregate crashes (F11).

### E. Results

| Check | Result |
|---|---|
| Reordering, renaming, duplicating a rule must not change the answer | 0 violations in 351 (DeepProbLog) and 2,220 (Scallop) mutants |
| Probability boundary and perturbation | 0 real mismatches in 310 and 311 |
| Raising a probability must not lower a query (Scallop) | 0 in 125 |
| DeepProbLog exact engine vs ProbLog | agrees on long chains down to 1e-100 |
| Scallop vs clingo, 1,000 random deterministic programs | identical |
| Gradients vs numerical derivatives (4 provenances) | match on 80 of 80 |
| DeepProbLog invariance to batching, order, duplicates, cache | no violation in 65 programs |

### Results of LTNTorch and LNN

| ID | Library | What goes wrong | Repro |
|---|---|---|---|
| **F28** | LNN | `Model.infer()` **never returns** when a quantified formula is added with `add_knowledge()` (5 of 8 simple cases; all 8 return with `set_query()`). The documentation example adds its `Exists` query that way. | [fuzz/repro_lnn_exists_hang.py](fuzz/repro_lnn_exists_hang.py) |
| **F29** | LNN | Two **identical sub-formulas built as separate objects** are one graph node but the second object is never updated: `And(Or(a,b), Or(a,b))` with a=TRUE, b=FALSE gives UNKNOWN, one shared object gives TRUE. It can also happen implicitly through `Iff`, and `Implies(And(a,b), And(a,b))` can loop forever. | [fuzz/repro_lnn_duplicate_subformula.py](fuzz/repro_lnn_duplicate_subformula.py) |
| **F33** | LNN | **`infer()` never returns for `XOr` with three operands** when the formula is asserted true and one operand is 0.999 instead of 1 (with exactly 1 it returns in 2 steps). Found by changing the data of LNN's own `test_Xor_1.py`. | [fuzz/repro_lnn_xor_hang.py](fuzz/repro_lnn_xor_hang.py) |
| **F34** | LNN | **Slightly changed data makes LNN's own first-order tests loop forever.** In 5 of its tests (`test_american` x2, `test_nested_quantifiers` x3) the inference did not finish within 8 s for 13 of 35 changed test runs (5 tests x 7 changed runs), although the original data finishes in under a second. These tests use `set_query`. | `NESY_LNN_MUT=perturb:1 PYTHONPATH=frameworks/LNN:fuzz python -m pytest tests/reasoning/logic/fol/test_american.py -p mutate_lnn_tests` (from `frameworks/LNN`) |
| **F30** | LNN | `And(A)`, `Or(A)`, `XOr(A)` with a single operand are accepted, then crash in `infer()` with `IndexError`. | [fuzz/repro_lnn_unary_connective.py](fuzz/repro_lnn_unary_connective.py) |
| **F24** | LTNtorch | `ImpliesGoguen()` with its **default** setting scores "false implies false" as about **0**: 0.0 at (0,0), 0.0099 at (1e-6,1e-6), 0.5 at (1e-4,1e-4); the documented formula gives 1. The non-default `stable=False` is correct. | [fuzz/repro_ltn_goguen_stable.py](fuzz/repro_ltn_goguen_stable.py) |
| F25, F26 | LTNtorch | `Quantifier([])` is accepted and returns a scalar that claims free variables; guarded quantifiers return float64 while unguarded return float32. | [fuzz/repro_ltn_forall_empty.py](fuzz/repro_ltn_forall_empty.py) |
| F27 | LTNtorch | The unstable operator variants give **NaN** gradients at boundary values where the documentation says "vanishing". | `fuzz/ltn_fuzz.py` |
| F31, F32 | LNN | The documented square/rectangle example infers nothing as written; invalid bounds raise `IndexError`; `And()` and duplicate proposition names are accepted. | [fuzz/repro_lnn_docs_example.py](fuzz/repro_lnn_docs_example.py) |

---

## 3. Oracle

The libraries have no oracle, so each method pairs a **test input** with **a way to know the answer is wrong**.

1. **Mutate the libraries' own tests.** Take a real test program and change one thing: a probability (to 0, 1, tiny, or
   1-p), clause order, a duplicated or renamed rule, the inference engine, or an invalid input. The old expected value no
   longer applies, so each mutation carries a check: the answer must not change when only the order changes, a probability
   must stay in [0,1], ProbLog must agree. ([fuzz/mutate_dpl.py](fuzz/mutate_dpl.py), [fuzz/mutate_scl.py](fuzz/mutate_scl.py))
2. **Random programs against the exact answer.** Generate small random programs and compute the true answer by listing every
   possible world ([fuzz/nesy_prog.py](fuzz/nesy_prog.py)). The library must match, and its gradient must match the exact
   derivative. This found F3, F4 and F7.
3. **Libraries against their plain-logic counterparts.** Run ProbLog's 109 own tests through DeepProbLog and clingo's programs
   through NeurASP. This found F10, F11, F12 and F18.
4. **Internal consistency.** The same program under every Scallop provenance setting, gradients against finite differences, and
   the digit-sum pattern with an exact formula. This found F19 to F22.
5. **ProbFuzz-style generation** (section 4).

### Scale (lower bound, program runs only)
| Campaign | Size |
|---|---|
| Mutation: DeepProbLog, Scallop | 906 + 2,855 mutants from 24 + 254 real test inputs |
| ProbLog tests through DeepProbLog | 104 programs on 2 engines |
| clingo programs through NeurASP | 150 programs |
| Scallop vs clingo | 1,000 random programs |
| Scallop provenance consistency | 2,286 runs |
| NeurASP grammar sweep | 799 programs |
| Differential fuzzing on 5 dimensions | 162 cases x 4 systems, plus 65 programs |
| ProbFuzz port | 192 programs x 7 configurations |
| LTNtorch (3 seeds) | 31,077 operator, aggregator, gradient and quantifier checks; 3,810 mutants of its own test inputs; 620 saturation and invariance checks |
| LNN (3 seeds) | 8,243 checks on interval semantics, classical and partial knowledge, first order, learning, termination |
| LNN's own tests, inputs changed | 132 tests x 9 runs (7 changed, 2 unchanged) |
| LTNtorch against LNN | 1,342 random Lukasiewicz formulas |
| Random campaigns against the exact oracle | hundreds of programs per library |

That is **more than 50,000 program evaluations and checks**, plus a validated exact oracle (132 programs, largest difference 5.6e-16
against ProbLog) and a triage record of about a dozen false alarms that were ruled out and are not counted.

---

## 4. ProbFuzz

**ProbFuzz** tests *probabilistic programming systems* (Stan, Pyro, Edward), tools that estimate hidden numbers from data,
for example "what is the price per item, given these receipts?". Their bugs are silent too. Its method:

1. **Template with holes.** A developer writes a model skeleton with blanks (`??`) for a distribution, parameter or data.
2. **Generator** fills the blanks at random, using knowledge of what each distribution accepts (for example a standard
   deviation must be positive). It can also pick edge values. Using that knowledge made 84% or more of generated programs
   useful, against under 21% for blind fuzzing.
3. **Translator** writes the same program in each system's own language.
4. **Program checker** runs them and flags crashes, NaN or infinity, slow runs, and results far from an exact answer, from
   other tools, or from the known true parameters (SMAPE metric).

It reported **67 new bugs**, 51 accepted by developers.

### The dimensions ProbFuzz fuzzes
ProbFuzz varies the following dimensions of a test program. Each sentence names one dimension and what is changed in it.

1. **Program structure.** The model comes from one of four templates: a simple posterior, a linear regression, a multiple linear regression and a conditional model.
2. **Distribution of the model.** The distribution that connects the parameters to the observed data is chosen at random among the distributions that fit the template.
3. **Distributions of the priors.** Each unknown variable receives a prior distribution whose range of values fits the model's parameters.
4. **Parameter values.** Each parameter is set either to a random value inside its legal range or to a value at or beyond the edge of that range, legal or illegal, with a probability the developer sets.
5. **Data.** The input vectors, their sizes and the expected outputs are generated for every program.
6. **System and inference algorithm.** The same program is run on Edward, Pyro and Stan, each with one of its inference algorithms.
7. **Checks.** Each run is checked for crashes, NaN or overflow values, slow convergence, and accuracy against an exact result, the true parameters or the other systems, using the SMAPE metric.
8. **Amount of domain knowledge.** An informed generator that respects each distribution's valid ranges is compared with an uninformed one.

### How we adopted it
We took ProbFuzz's source code (commit 2914413, MIT licence), ported it to Python 3 and replaced its targets and its checker
([probfuzz-nesy/probfuzz/](probfuzz-nesy/probfuzz/)). The table shows what each ProbFuzz dimension became in our case.

| ProbFuzz dimension | In our adapted version |
|---|---|
| Program structure (4 regression templates) | 8 templates of small logic programs: recursion, chain, noisy-or, join, negation, one and two groups of exclusive options, diamond |
| Distribution of the model and of the priors | Two distributions: `bernoulli` (an independent probabilistic fact) and `categorical` (a group of mutually exclusive alternatives); `DISTX` picks one |
| Parameter values: random or at the edge | Random probabilities by default; with `--special` they are sometimes 0, 1, 1e-12, 1e-9, 1e-6, 1e-5, 1-1e-5 or 1-1e-9 |
| Data and sizes | The domain size `n` (2 or 3 constants) and the dimensions of each relation decide how many facts a program has |
| System and algorithm | Scallop (`topkproofs`, and with `wmc_with_disjunctions`), DeepProbLog (exact and approximate engine), ProbLog and NeurASP |
| Checks and metric | Crash (including timeouts of 40 s), NaN or out-of-range value, and accuracy as SMAPE against an exact possible-worlds answer |
| Domain knowledge | A completed template is rejected and drawn again if a probability is outside [0,1], a group sums above 1, or a rule is unsafe |

In addition to the table:
- **Language.** We extended ProbFuzz's grammar with `rule ... :- ..., not ...`. A line such as `d := categorical(CONST,CONST,CONST)` declares a group of three mutually exclusive alternatives, and `a := DISTX[n]` declares `n` independent facts.
- **Translators.** One translator per system walks the template's parse tree and writes a standalone program that prints `RESULT <relation> <tuple> <probability>`.
- **Reference answer.** The exact possible-worlds answer replaces the comparison between tools, because our programs are small and discrete.
- **Summary.** `summary.csv` gives, per program and per system, the three flags Crash, Num and Acc, and the largest SMAPE.

### Results of the adapted ProbFuzz
We ran two campaigns of 96 programs each (8 templates x 12 programs, 7 configurations per program, one random seed per campaign).
One campaign used ordinary random values and one used `--special`.

| System | Ordinary values | Special values |
|---|---|---|
| ProbLog | no problem | no problem |
| DeepProbLog, exact engine | no problem | no problem |
| Scallop, default `topkproofs` | 9 timeouts | 6 timeouts |
| Scallop, `wmc_with_disjunctions` | **24 wrong answers**, 9 timeouts | **24 wrong answers**, 6 timeouts |
| DeepProbLog, approximate engine | 12 crashes | 11 crashes, **4 wrong answers** |
| NeurASP | 10 timeouts | 11 timeouts |

Per template:

| Template | What happened |
|---|---|
| disjunction, disjunction_join | Scallop with `wmc_with_disjunctions` was wrong in 12 of 12 programs in both campaigns (F3) |
| negation | DeepProbLog's approximate engine crashed in 12 of 12 programs with ordinary values and 11 of 12 with special values (F23) |
| noisy_or, diamond | DeepProbLog's approximate engine was wrong in 3 and 1 programs, only with special values, always when a fact had probability exactly 0 (F4) |
| reach (recursion) | Scallop timed out in 9 of 12 and 6 of 12 programs |
| join, diamond | NeurASP timed out in 5 to 6 of 12 programs once a program had about 18 facts or more |
| chain, noisy_or (ordinary values) | no system deviated from the exact answer |

In words: the adapted ProbFuzz found three of the known defects (F3, F4, F23) without any hand-written test case. Special values
mattered for F4 only, which appears when a probability is exactly 0. ProbLog, DeepProbLog's exact engine and Scallop's default
mode agreed with the exact answer on every program they finished. The timeouts are limits of the algorithms and are not wrong answers.
The adapted ProbFuzz found no defect that the other methods had not already found, so its contribution is the template-based generation method.

<!-- **Not adopted from ProbFuzz:** continuous distributions, conditioning on data (`observe`), regression templates, comparison
with true parameters, the Stan, Edward and Pyro translators, the paper's pairwise tool comparison, its exact solver (PSI),
and its experiments (bug study, informed vs uninformed, old-bug rediscovery).  -->
---

## 5. diff

| | ProbFuzz | This project |
|---|---|---|
| Targets | Stan, Pyro, Edward: estimate unknown numbers from data (continuous, approximate) | DeepProbLog, Scallop, NeurASP: probability of logic queries, with neural inputs (discrete, exact answers possible) |
| Test inputs | **Generated** from templates | Mostly **mutated** from the libraries' own tests, plus random programs, counterpart tests and templates |
| What is "wrong" | Disagreement with other tools, an exact solver, or known truth | An exact possible-worlds answer **and** rules that must hold: order-independence, range [0,1], monotonicity, gradients |
| Extra checks | crashes, NaN, slowness | also gradients (used for training), input validation, invariance to batching |
| Where bugs were looked for | from a study of 118 historical bugs | from thresholds in the libraries' code and from mathematical specifications |

---

## 6. DeepProbLog tests: which we used and which we discarded

DeepProbLog's own test suite has about 44 test functions. A recorder ([fuzz/trace_dpl.py](fuzz/trace_dpl.py)) watches the
suite while it runs and saves each program, engine setting and set of queries as a **seed**. Parametrized tests give several
seeds each, so the suite yields **50 seeds**. Of these, **24 were mutated** and **26 were not**.

**The funnel**

| Stage | Seeds left |
|---|---|
| Recorded from the suite | 50 |
| Without a neural network | 29 |
| With queries and a supported engine | 25 |
| Unmutated replay succeeds (checked before mutating) | **24** |

**Why each filter exists.** Mutation changes the program text and then needs a check that does not rely on the old
expected answer. That check needs (a) a plain logic program that ProbLog can also run, so tests with a neural network are
excluded; (b) queries to compare, so tests with none are excluded; and (c) a trustworthy baseline, so a seed whose
*unchanged* replay already fails is excluded.

### Discarded seeds (26), with links to the test source

#### 1. Tests that use a neural network: 21

| # | Test (link) | Engine | Why it was not mutated |
|---|---|---|---|
| 17 | [`test_neural_predicate.py::test_model_basics[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L70) | Approximate k=10 | uses a neural network (and records no queries) |
| 18 | [`test_neural_predicate.py::test_model_basics[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L70) | Exact | uses a neural network (and records no queries) |
| 19 | [`test_neural_predicate.py::test_model_basics[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L70) | Exact | uses a neural network (and records no queries) |
| 20 | [`test_neural_predicate.py::test_ad_network[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L76) | Approximate k=10 | uses a neural network |
| 21 | [`test_neural_predicate.py::test_ad_network[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L76) | Exact | uses a neural network |
| 22 | [`test_neural_predicate.py::test_ad_network[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L76) | Exact | uses a neural network |
| 23 | [`test_neural_predicate.py::test_fact_network[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L89) | Approximate k=10 | uses a neural network |
| 24 | [`test_neural_predicate.py::test_fact_network[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L89) | Exact | uses a neural network |
| 25 | [`test_neural_predicate.py::test_fact_network[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L89) | Exact | uses a neural network |
| 26 | [`test_neural_predicate.py::test_det_network[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L99) | Approximate k=10 | uses a neural network |
| 27 | [`test_neural_predicate.py::test_det_network[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L99) | Exact | uses a neural network |
| 28 | [`test_neural_predicate.py::test_det_network[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L99) | Exact | uses a neural network |
| 29 | [`test_neural_predicate.py::test_det_network_substitution[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L109) | Approximate k=10 | uses a neural network |
| 30 | [`test_neural_predicate.py::test_det_network_substitution[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L109) | Exact | uses a neural network |
| 31 | [`test_neural_predicate.py::test_det_network_substitution[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L109) | Exact | uses a neural network (and records no queries) |
| 32 | [`test_neural_predicate.py::test_multi_input_network[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L121) | Approximate k=10 | uses a neural network |
| 33 | [`test_neural_predicate.py::test_multi_input_network[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L121) | Exact | uses a neural network |
| 34 | [`test_neural_predicate.py::test_multi_input_network[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_neural_predicate.py#L121) | Exact | uses a neural network |
| 47 | [`test_semiring.py::test_saturated_network_keeps_gradient_and_finite_loss`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L120) | Exact | uses a neural network |
| 48 | [`test_semiring.py::test_exhaustive_ad_stays_a_probability`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L137) | Exact | uses a neural network |
| 49 | [`test_semiring.py::test_training_through_the_circuit_is_stable`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L154) | Exact | uses a neural network |

#### 2. Tests with no recorded query: 4

| # | Test (link) | Engine | Why it was not mutated |
|---|---|---|---|
| 2 | [`test_engine.py::test_cache_error`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L22) | Approximate k=10 | never calls `solve`; it only checks that creating a model with an empty program raises `SolverException` |
| 11 | [`test_model.py::test_model_basics[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_model.py#L38) | Approximate k=2 | never calls `solve`; it only asserts that `model.solver` and `model.program` exist |
| 12 | [`test_model.py::test_model_basics[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_model.py#L38) | Exact | never calls `solve`; it only asserts that `model.solver` and `model.program` exist |
| 13 | [`test_model.py::test_model_basics[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_model.py#L38) | Exact | never calls `solve`; it only asserts that `model.solver` and `model.program` exist |

#### 3. Skipped when the mutation ran: 1

| # | Test (link) | Engine | Why it was not mutated |
|---|---|---|---|
| 9 | [`test_engine.py::test_foreign_text`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L126) | Approximate k=10 | its recorded query text (`a(one two three,0,X)`) no longer parses and the foreign predicate `ith_word` is not registered in the replay harness, so the unmutated seed fails with `ParseError` |

**Observation.** 21 of the 26 are the tests that use a neural network, so **the neural part of DeepProbLog is the least
mutated**. That is a limitation, and it is why neural saturation was tested separately (findings F14 and F15).

### Seeds that were mutated (24)

<details><summary>Show the 24 mutated seeds</summary>

| # | Test | Engine | Queries |
|---|---|---|---|
| 0 | [`test_builtin.py::test_tensor_index`](frameworks/deepproblog/src/deepproblog/tests/test_builtin.py#L17) | Exact | 1 |
| 1 | [`test_builtin.py::test_less_than`](frameworks/deepproblog/src/deepproblog/tests/test_builtin.py#L30) | Exact | 2 |
| 3 | [`test_engine.py::test_ad`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L27) | Approximate k=10 | 2 |
| 4 | [`test_engine.py::test_ad2`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L42) | Approximate k=10 | 2 |
| 5 | [`test_engine.py::test_ad3`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L58) | Approximate k=10 | 2 |
| 6 | [`test_engine.py::test_fact`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L73) | Approximate k=10 | 2 |
| 7 | [`test_engine.py::test_fact2`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L88) | Approximate k=10 | 2 |
| 8 | [`test_engine.py::test_foreign`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L104) | Approximate k=10 | 3 |
| 10 | [`test_engine.py::test_assignment`](frameworks/deepproblog/src/deepproblog/tests/test_engine.py#L163) | Approximate k=10 | 1 |
| 14 | [`test_model.py::test_solve[model0]`](frameworks/deepproblog/src/deepproblog/tests/test_model.py#L44) | Approximate k=2 | 4 |
| 15 | [`test_model.py::test_solve[model1]`](frameworks/deepproblog/src/deepproblog/tests/test_model.py#L44) | Exact | 4 |
| 16 | [`test_model.py::test_solve[model2]`](frameworks/deepproblog/src/deepproblog/tests/test_model.py#L44) | Exact | 4 |
| 35 | [`test_semiring.py::test_small_probabilities_are_summed[1e-08]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L43) | Exact | 1 |
| 36 | [`test_semiring.py::test_small_probabilities_are_summed[1e-06]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L43) | Exact | 1 |
| 37 | [`test_semiring.py::test_small_probabilities_are_summed[5e-06]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L43) | Exact | 1 |
| 38 | [`test_semiring.py::test_small_probabilities_are_summed[1e-05]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L43) | Exact | 1 |
| 39 | [`test_semiring.py::test_small_probabilities_are_summed[1.0001e-05]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L43) | Exact | 1 |
| 40 | [`test_semiring.py::test_small_probabilities_are_summed[0.1]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L43) | Exact | 1 |
| 41 | [`test_semiring.py::test_small_probabilities_are_summed[0.3]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L43) | Exact | 1 |
| 42 | [`test_semiring.py::test_probabilities_near_one_are_multiplied[0.99999999]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L54) | Exact | 1 |
| 43 | [`test_semiring.py::test_probabilities_near_one_are_multiplied[0.999999]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L54) | Exact | 1 |
| 44 | [`test_semiring.py::test_probabilities_near_one_are_multiplied[0.99999]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L54) | Exact | 1 |
| 45 | [`test_semiring.py::test_probabilities_near_one_are_multiplied[0.9]`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L54) | Exact | 1 |
| 46 | [`test_semiring.py::test_small_probabilities_keep_their_gradient`](frameworks/deepproblog/src/deepproblog/tests/test_semiring.py#L64) | Exact | 1 |

</details>

**Recorder correction (found while writing this README).** The first version of the recorder labelled models built by a test
*fixture* with the previous test's name, so 24 of the 50 labels in `results/seeds/deepproblog_seeds.json` are shifted by one.
The programs, engines and queries are correct. The names above come from the corrected recorder
([results/seeds/deepproblog_seeds_relabelled.json](results/seeds/deepproblog_seeds_relabelled.json)); the original file is
unchanged.

---
# neys_fuzz
