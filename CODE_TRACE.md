# Code trace: where each finding happens, and why

Companion to [REPORT.md](REPORT.md). REPORT.md says *what* was observed; this file says *where in the code* it happens, *why*,
*which harness function found it*, and *how much of that was checked*. Written 2026-10-07.

## How to read this

**Evidence level** (stated per finding, not averaged):

| Mark | Meaning |
|---|---|
| **A** | Re-run today on this machine, and the cause was read in the framework source. |
| **B** | Cause read in the framework source today; the numbers were recomputed (brute force or arithmetic) but the original program was not re-run. |
| **C** | Found in the earlier campaigns; today I located the relevant code but did **not** trace the full cause. "Not traced" is written where that applies. |

All framework paths are relative to `nesy-fuzz/frameworks/`, all harness paths to `nesy-fuzz/fuzz/`. Clones are at the commits in
REPORT.md (checked today: NeurASP `b25598d`, DeepProbLog `f64181f`, Scallop `668bfb6`, ProbLog `a294fa2`, clingo `91f9045`, LNN `c88f513`,
LTNtorch `d1bd981`), with no local modifications.

Nothing here has been reported upstream. A "why" below is my reading of the code. A maintainer may say the behaviour is intended.

---

## 1. The harness, in the order the method runs

| Step | What happens | Code |
|---|---|---|
| 1. Baseline | Run each framework's own tests unmodified | pytest / `cargo test`, XML in `results/baseline/` |
| 2. Extract inputs | Record the programs, probabilities and queries the original tests use | DeepProbLog: pytest plugin [trace_dpl.py](fuzz/trace_dpl.py) wraps `Model.__init__` (l.18), `set_engine` (l.31), `solve` (l.40) and writes the seeds at session end (l.69). Scallop: [extract_scl_seeds.py](fuzz/extract_scl_seeds.py) `test_blocks` (l.19) pulls program text out of the Rust tests, `run_scli` (l.35) replays them. LTN: [trace_ltn.py](fuzz/trace_ltn.py). |
| 3. Mutate | Change probabilities (boundary / perturb / complement), reorder, duplicate or rename rules, swap engine or provenance, make a probability or disjunction invalid | [mutate_dpl.py](fuzz/mutate_dpl.py) `mutate_prob` (l.58), `make_mutants` (l.283); [mutate_scl.py](fuzz/mutate_scl.py) `mutate_tag` (l.118), `make_mutants` (l.160); [mutate_lnn_tests.py](fuzz/mutate_lnn_tests.py) `_mutate_value` (l.49); [ltn_mutate.py](fuzz/ltn_mutate.py) `mutate_tensor` (l.54) |
| 4. Judge | Each mutant has its own oracle, because the original expected value no longer applies | [mutate_dpl.py](fuzz/mutate_dpl.py) `judge` (l.218), [mutate_scl.py](fuzz/mutate_scl.py) `judge` (l.244) |
| 5. Exact oracle | For random programs, enumerate every possible world and add up the weights | [nesy_prog.py](fuzz/nesy_prog.py) `exact_probs` (l.102) using `_eval_world` (l.79); `gen_prog` (l.156); delta-debugging `shrink` (l.209) |
| 6. Counterpart tests | Run ProbLog's own `.pl` tests through DeepProbLog; clingo's `.lp` programs through NeurASP | [adopt_problog_tests.py](fuzz/adopt_problog_tests.py) `read_result` (l.27, copied from ProbLog's runner), `evaluate` (l.84), `classify` (l.125); [adopt_clingo_tests.py](fuzz/adopt_clingo_tests.py) `models_of` (l.46), `compare` (l.100) |
| 7. Differential dimensions | D1 thresholds, D2 disjunction shape, D3 chains, D4 evaluation mode, D5 neural vs literal | [diff_fuzz.py](fuzz/diff_fuzz.py) `case_d1` (l.39), `case_d2` (l.54), `case_d3` (l.74), `run_neural` (l.146), `grade` (l.224); D4 in [invariance_dpl.py](fuzz/invariance_dpl.py) `run_modes` (l.36) |
| 8. Triage | Every anomaly is reduced and classified as harness bug, oracle limit or candidate | REPORT.md sections 5, 9.5, 10.4, 12.4 |

Process safety: each task runs in a spawned worker with a timeout (`Runner`, [mutate_dpl.py](fuzz/mutate_dpl.py) l.179; `Pool`,
[adopt_problog_tests.py](fuzz/adopt_problog_tests.py) l.154). DeepProbLog's approximate engine can kill the interpreter (F18), so a crash is a
result, not a harness failure.

---

## 2. Findings, grouped by library

### Scallop (Rust core and `scallopy`)

#### F3. Mutually exclusive facts: the default ignores them, the flag counts them wrongly. Evidence **B**
*Where.* `core/src/runtime/provenance/probabilistic/top_k_proofs.rs:91-99` (`recover_fn`) picks one of two routines in
`core/src/runtime/provenance/common/as_boolean_formula.rs`:
* **Default** (`:10-20`, `wmc`): builds the formula and evaluates it. `Disjunctions` is never passed in. The group *is* recorded
  (`top_k_proofs.rs:83-85`, `add_disjunction`), but this routine does not use it, so exclusive facts are treated as independent.
* **`wmc_with_disjunctions`** (`:23-47`): ORs the query formula with a constraint term per group (`bf_disjunction(once(formula).chain(...))`, l.31).
  The per-group term is true on every world **except** "exactly one member holds" (I enumerated it, table below). Adding it to the query by OR
  therefore counts the impossible worlds as satisfying the query instead of removing them.

*Checked today.* Brute force over the 8 worlds of `{0.0313, 0.392, 0.4039}`, query = "some member holds"
([check_f3_wmc_formula.py](fuzz/check_f3_wmc_formula.py), plain Python, no framework needed):

| | result | matches Scallop's output |
|---|---|---|
| constraint true on worlds | `000 011 101 110 111` (false only on `001 010 100`) | |
| default, ignoring exclusivity | 0.6489 | 0.6489 |
| formula OR constraint (as coded) | 1.0000 | 1.0 |
| correct (members are exclusive) | 0.8272 | expected value |

Why 1.0 exactly: "query false" means no member holds, "constraint false" means exactly one holds. Both together are impossible, so the OR is true in every world.
*Found by.* [scallop_fuzz.py](fuzz/scallop_fuzz.py) `scallop_diff` (l.75) against `exact_probs`; minimal: [repro_disjunction.py](fuzz/repro_disjunction.py).
*Not established.* What the authors intended the flag to compute. I read the OR as wrong because the result exceeds what is possible.
Also consistent with upstream issue #64 (read before, not re-checked today).

#### F22. Two categorical inputs through `forward_function` give all zeros. Evidence **A**
*Where.* `etc/scallopy/scallopy/input_mapping.py:103-104`: `if self.supports_disjunctions and mutual_exclusion_counter is None: mutual_exclusion_counter = Counter()`.
Every call creates a fresh counter, and ids are drawn from it at `:162` and `:166`. `etc/scallopy/scallopy/forward.py:509` calls
`self.ctx._input_mappings[rela].process_tensor(rela_facts)` **without** passing a counter, although the context owns one
(`etc/scallopy/scallopy/context.py:101`, used at `:776`). Two categorical relations therefore both get disjunction id 0, and Scallop reads every join between them as "mutually exclusive" (probability 0).
*Re-run today* ([repro_scallopy_disjunction_ids.py](fuzz/repro_scallopy_disjunction_ids.py)): exact `[0.28, 0.54, 0.18]`; as shipped `[0, 0, 0]`;
with a shared counter `[0.28, 0.4896, 0.18]` (still wrong, because of F3's default routine). The report's fourth variant (shared counter plus
`wmc_with_disjunctions`, giving `[0.78, 0.89, 0.73]`) was **not** printed by today's run; I did not re-verify it.
*Found by.* [scallopy_mnist_sum.py](fuzz/scallopy_mnist_sum.py) (the digit-sum pattern with closed forms).

#### F19. `proofs` provenance panics on negation and every aggregate. Evidence **B** (the code is explicit; not re-run today)
`core/src/runtime/provenance/discrete/proofs.rs:209-211`: `fn negate(&self, _) -> Option<Tag> { panic!("Not implemented") }`. `not`, `count`, `sum`, `min`, `exists`,
`string_join` all need `negate`. This is a run-time panic, not a compile-time "unsupported". *Found by.* [prov_consistency.py](fuzz/prov_consistency.py) `main` (l.18): 254 programs x 9 provenance settings.

#### F20. A guard in the same rule does not protect a division or modulo. Evidence **B**
`core/src/runtime/env/environment.rs:391-396` (`Div`) and `:423-428` (`Mod`) use the plain Rust `/` and `%` on integers, so `y == 0` panics. REPORT.md records that
`rel dv(x / y) = a(x), a(y), y != 0` panics but the guard moved into a helper relation does not, and that clingo accepts the guarded rule.
That matches an expression evaluated without waiting for the guard, but **I did not trace the evaluation order** to prove it.
*Found by.* [scallop_vs_clingo.py](fuzz/scallop_vs_clingo.py) `compare` (l.64), `shrink` (l.86): 39 of 300 random programs.

#### F21. Integer overflow policy is inconsistent. Evidence **B**
Same file: `+` and `-` use `saturating_add` / `saturating_sub` (`:302-309`, `:334`), `*` uses plain `i1 * i2` (`:364`), `/` and `%` plain (`:393`, `:425`). In a release build `*` wraps, in a debug build it panics.
A policy mismatch, not a wrong answer by any written spec. The probes were run by hand against the release `scli`; there is no script for them in `fuzz/`.

#### F2. Tags outside [0,1] accepted. Evidence **B**
`core/src/runtime/provenance/probabilistic/min_max_prob.rs:44-46` (`tagging_fn(p) = p.into()`) and `top_k_proofs.rs:77-80` (`push(input_tag.prob)`): no range check at the point a tag enters.
*Found by.* [mutate_scl.py](fuzz/mutate_scl.py) `mutate_tag` (l.118) + the spec oracle in `judge` (l.244): 94 of 94 accepted.

#### F9. 12 original `scallopy` tests panic at HEAD. Evidence **B**
Panic text: "Cannot clone pointer into Python heap without the thread being attached". `etc/scallopy/src/foreign_predicate.rs:14-16` is `#[derive(Clone)] struct PythonForeignPredicate { fp: Py<PyAny>, ... }`, a derived `Clone` over a `Py` handle. In the PyO3 version in use, cloning a `Py` without the GIL panics.
*I did not confirm* that this derive is the clone that panics (shallow clone, no history). *Found by.* the baseline run, `results/baseline/scallopy.xml`.

#### F8. `topkproofs` slowdown at k=30. Evidence **C**
Original test `test_min_max_with_recursion`: 0.01 s at k=3, 0.10 s at k=10, over 15 s at k=30. Not traced; may be inherent to top-k proofs. [perf_shrink.py](fuzz/perf_shrink.py), [time_case.py](fuzz/time_case.py).

---

### DeepProbLog (on ProbLog)

#### F4, F15. Approximate engine loses the whole query when a probability-0.0 fact is on a proof path. Evidence **A**
*Where.* `src/deepproblog/engines/prolog_engine/prolog_files/heuristics_heap.pl:11`:
`add_probability_to_heuristic(Probability,gm(H1,D1),gm(H2,D2)) :- !, D2 is D1 + 1, H2 is (H1*D1-log(Probability))/D2.`
`log(0.0)` raises in SWI-Prolog. The `geometric_mean` heuristic takes this branch for every fact on a proof path, and the `ucs` heuristic (line 12) only multiplies and has no `log`. F15 is the same line reached through a neural fact (`engine_heap.pl:47-63` passes the network's probability into it).
*Checked today.*
* Calling the predicate directly in `swipl`: `0.6 -> ok`, `0.001 -> ok`, `1e-300 -> ok`, `0.0 -> error(evaluation_error(float_overflow))`; the `pp` heuristic with 0.0 -> `pp(-0.0)` (no error).
* Re-ran [repro_dpl_zero.py](fuzz/repro_dpl_zero.py): `0.0::z. 0.6::a. q :- a. q :- z.` exact 0.6, approx **absent** (k = 1, 2, 5 and 50 all tried); a zero fact *not on a proof path* works (0.6); `0.001` works; `ucs` gives 0.6.
*Not established.* Why the *whole* query disappears, including the derivable `q :- a`. A plausible route is `prolog_engine/engine.py:105-106`, where `get_proofs` turns an `OverflowError` into an empty proof list, but I did not confirm that the Prolog error arrives as that exception.
*Found by.* [mutate_dpl.py](fuzz/mutate_dpl.py) engine-swap + boundary mutants; confirmed with [nesy_prog.py](fuzz/nesy_prog.py)'s exact oracle.

#### F10. `evidence(...)` is silently ignored. Evidence **B**
*Where.* ProbLog applies evidence in `problog/problog/engine.py:534-560` (`ground_all`, which loads the program's evidence) and `:461-516` (`ground_evidence`). DeepProbLog never calls `ground_all`: `src/deepproblog/solver.py:71` (`build_ac`) calls `engine.ground(q, ...)`, and `engines/exact_engine.py:143-148` forwards that to `DefaultEngine.ground(db, query.query, ...)`, which grounds one query term. The approximate engine's own `ground_all` (`engines/prolog_engine/engine.py:66-88`) accepts an `evidence=None` parameter and never uses it.
*Found by.* [adopt_problog_tests.py](fuzz/adopt_problog_tests.py): 9 of 11 programs tagged `evidence` by `features` (l.71) return unconditional values (burglary 0.7 instead of 0.9897).

#### F1. No validation of probabilities or disjunction sums. Evidence **B**
*Where.* ProbLog rejects in `problog/problog/evaluator.py:225-232` (`SemiringProbability.value`: only `0-1e-9 <= v <= 1+1e-9`), `:238-239` (`in_domain`) and the annotated-disjunction check `problog/problog/constraint.py:214-225`. DeepProbLog's `GraphSemiring.value` (`src/deepproblog/semiring/graph_semiring.py:63-89`) returns `float(a)` without a range check, and it does not override `in_domain`, whose base version is `return True` (`evaluator.py:134-136`).
*Found by.* [mutate_dpl.py](fuzz/mutate_dpl.py) invalid-probability / invalid-group operators, spec oracle in `judge` (l.218), ProbLog as the reference (`run_problog`, l.145): 76 of 109 invalid mutants accepted.

#### F13. Silent cutoffs for tiny probabilities (ProbLog and DeepProbLog differ). Evidence **B**
`problog/problog/evaluator.py:286-288`: in the log-space semiring `value` returns `zero()` when `-1e-9 <= v < 1e-9`. `problog/problog/logic.py:897-901`: `Constant.FLOAT_PRECISION = 15`, so every float literal is rounded to 15 decimals (DeepProbLog turns `5e-16` into `1e-15` and `<5e-16` into `0.0`).
*Found by.* [sweep_tiny.py](fuzz/sweep_tiny.py) and D1 (`case_d1`, [diff_fuzz.py](fuzz/diff_fuzz.py) l.39).

#### F14. Neural and literal paths disagree for the same distribution. Evidence **C**
Neural values come from float32 tensors (`graph_semiring.py:69-76`), literal ones pass through the rounding above. That explains the *kind* of disagreement; I did not re-derive the specific gap values in REPORT.md. [diff_fuzz.py](fuzz/diff_fuzz.py) `run_neural` (l.146).

#### F23. Approximate engine fails on negation. Evidence **C**
`src/deepproblog/engines/prolog_engine/swi_program.py:171-179` (`add_clause`) accepts only bodies whose type is exactly `Term` or `And`; anything else raises `SWIProgramException("Unhandled body type")` (the 13 adopted-test failures). For `q :- a, \+b.` the body is an `And`, so it passes the check and the `PrologError` appears later at run time; that later step I did not trace. Found by the negation template of the ProbFuzz port (`probfuzz-nesy/`). May be an undocumented limit; I found no statement either way.

#### F18. A Prolog error poisons the process. Evidence **C**
Behaviour only: after one failing model, the next valid run ends the interpreter (exit 4 with closed stdin, hang with open stdin). It sits in the embedded SWI-Prolog (`pyswip`); I found no initialisation flag in `engines/prolog_engine/swip.py`. [repro_swi_state.py](fuzz/repro_swi_state.py) `after_failure`; 22 of 109 adopted programs.

#### F5, F6, F11, F16. Evidence **C**
* F5 (zero fact has gradient 0, expected 1): same area as F4, gradient code not read.
* F6 (approximate engine omits underivable queries; exact returns 0.0): result assembly in `src/deepproblog/arithmetic_circuit.py` `evaluate` (l.38), not traced.
* F11 (aggregate builtins give `TypeError: expected Tensor ... got float`): not traced.
* F16 (ProbLog's over-sum tolerance varies with group shape): the check is `constraint.py:214-225` with `in_domain` at `evaluator.py:239` (probability space) and `:310` (log space, `a <= 1e-12`). The shape dependence is plausibly float rounding of the summed logs; **not isolated**. DeepProbLog and NeurASP never reject (F1).

---

### NeurASP (on clingo)

#### F12. Valid ASP crashes the parser; valid text can end the process. Evidence **B**
`mvpp.py`, class `MVPP.parse`:
* **Line 53**: `re.match(r"@?[0-9]\.?[0-9]*(?:e-[0-9]+)?\s.*;.*", line)` treats any line that starts with a digit, a space and contains `;` as a *probabilistic rule*. A clingo choice rule such as `1 { a; b } 1.` matches.
* **Lines 57-59, 70-72**: the line is split on `;` and each piece is parsed as `<prob> <atom>(...)`. `atom.split('(')[1]` raises `IndexError` for a piece with no `(`.
* **Lines 46-50**: for string input, `re.sub(r'\n%[^\n]*', '\n', program)` removes only whole-line comments. A program that ends with a line comment (`a. % note`) no longer ends with `.`, falls into the `else`, prints "not valid" and calls **`sys.exit()`**, which terminates the caller. (Line 259 does the same on a clingo syntax error.)
*Found by.* [adopt_clingo_tests.py](fuzz/adopt_clingo_tests.py) (`evaluate` l.63 catches `SystemExit`; file vs string path), then [neurasp_syntax_fuzz.py](fuzz/neurasp_syntax_fuzz.py) `run_one` (l.44), `shrink` (l.65); minimal [repro_neurasp_parse.py](fuzz/repro_neurasp_parse.py). 799 grammar-sweep programs found only this.

#### F7. `inference_obs_exact` and `gradient` are broken and unused. Evidence **B**
`mvpp.py:266-271` passes each model (a list of atom *strings* from `find_all_SM_under_obs`) to `prob_of_interpretation` (`:118-122`), which indexes the parameter tensor with them and so expects integer indices. `:273-282` (`gradient`) is separate code. A grep over the repo finds no caller of either. The training path (`mvppLearn`, `neurasp.py`) is what the tests matched. [neurasp_fuzz.py](fuzz/neurasp_fuzz.py) `api_exact` (l.144).

#### F17. float32 limits. Evidence **C**
Expected from dtype (`1 - 1e-9` is 1.0 in float32). [diff_fuzz.py](fuzz/diff_fuzz.py) `run_mvpp` (l.100). Not a defect by itself.

---

### LTNtorch

#### F24. `ImpliesGoguen()` with default `stable=True` scores "false implies false" as about 0. Evidence **B**
`ltn/fuzzy_ops.py:970-973`:
```
if stable: x = pi_0(x)
return torch.where(torch.le(x, y), torch.ones_like(x), torch.div(y, x))
```
`pi_0(x) = (1-eps)*x + eps` (`:41`, `eps = 1e-4` at `:21`) is applied to **x only**. For x = y = 0, x becomes 1e-4 which is larger than y = 0, so the result is `y/x = 0` instead of 1.
Recomputed today with the same formula: x=y=0 -> **0.0000**; 1e-6 -> **0.0099**; 1e-4 -> **0.5000**; 1e-3 -> **0.9092** (REPORT.md: 0.0, 0.0099, 0.5, 0.909). The docstring's own formula says 1 whenever x <= y.
*Found by.* [ltn_fuzz.py](fuzz/ltn_fuzz.py) formula check against [ltn_oracle.py](fuzz/ltn_oracle.py); minimal [repro_ltn_goguen_stable.py](fuzz/repro_ltn_goguen_stable.py).
*Not run today:* the script itself (the virtual environment was removed during this session, see section 4).

#### F25, F26, F27. Evidence **C**
* F26 dtype: `ltn/core.py:1512-1516` wraps the guarded result in `output.double()`; `ltn/fuzzy_ops.py:1219` does `xs.double()` in the masked min. Unguarded results stay float32.
* F25 (`Quantifier([], f)` accepted, result still lists free variables): the code at `core.py:1480-1522` builds `aggregation_vars` from the argument without a visible emptiness check; not traced further.
* F27 (NaN gradients in the unstable operators): likely the usual `torch.where` pitfall, where the untaken branch (here `y/x` with x=0) still contributes a NaN gradient. **A guess, not verified.**

---

### LNN (IBM)

#### F28. `infer()` never returns when a quantified formula is added with `add_knowledge()`. Evidence **A**
*Where.* `lnn/model.py:489-508`, the inference loop: it stops when `bounds_diff <= 1e-7` (l.507), or earlier when a *query* is set and resolved (l.490-496). In `lnn/symbolic/logic/unary_operator.py:235-252`, `_fully_quantified_upward` runs on every pass and executes `self.neuron = self._create_neuron(...)` (l.248): a **new neuron**, whose bounds start unknown, so `aggregate_bounds` reports a full-size change each pass although the answer is already [1,1].
*Re-run today* ([repro_lnn_exists_hang.py](fuzz/repro_lnn_exists_hang.py)): with `set_query()` returns in 3 steps; with `add_knowledge()` no return in 20 s; reported updates grow by exactly 1.0 per step (1, 2, 5, 10 steps -> 1.0, 2.0, 5.0, 10.0).
This also explains why `set_query` works: the loop leaves through l.490 and never needs the convergence test.
*Found by.* [lnn_fuzz.py](fuzz/lnn_fuzz.py) first-order group; table in [lnn_termination_table.py](fuzz/lnn_termination_table.py).

#### F29. Two identical sub-formulas built as separate objects: the second is never updated. Evidence **A** (behaviour), cause only partly traced
*Re-run today* ([repro_lnn_duplicate_subformula.py](fuzz/repro_lnn_duplicate_subformula.py)): `And(o, o)` with one shared object -> `[1.0, 1.0]` TRUE; `And(Or(a,b), Or(a,b))` as two objects -> `[0.0, 1.0]` UNKNOWN; also through `Iff`; `Implies(And(a,b), And(a,b))` with 0.9/0.8 does not return in 20 s.
*Where.* `lnn/symbolic/logic/formula.py:704-711`: `__eq__` compares `structure` and `neuron`, `__hash__` is `hash(self.structure)`. `lnn/model.py:263-280` (`_add_knowledge`) adds formulas to a networkx graph and indexes them by `structure` (`node_structures`).
*Not established.* Exactly which object ends up un-updated. The structure-based hash is the likely cause; I did not trace the graph edges.
*Found by.* [lnn_fuzz.py](fuzz/lnn_fuzz.py) classical-completeness check (14 failures, every one has a repeat) and [ltn_vs_lnn.py](fuzz/ltn_vs_lnn.py) (13 of 38 formulas with a repeat differ from LTN, 0 of 1,304 without).

#### F30. `And(A)`, `Or(A)`, `XOr(A)` accepted, then `infer()` raises `IndexError`. Evidence **A**
*Re-run today* ([repro_lnn_unary_connective.py](fuzz/repro_lnn_unary_connective.py)): all three raise `IndexError: index 1 is out of bounds for dimension 1 with size 1` at `lnn/symbolic/logic/formula.py:290` (`bounds[..., 1]` in `contradicting_bounds`). Why a one-operand connective has only one column there I did not trace.

#### F33. `XOr` with three operands never returns for operand 0.999. Evidence **A** (behaviour only)
*Re-run today* ([repro_lnn_xor_hang.py](fuzz/repro_lnn_xor_hang.py)): `XOr(Q,R,S)` TRUE with Q=TRUE and R=0.999 -> no return in 12 s; with R=0.9 or R=TRUE it returns after 2 steps; two operands with 0.999 returns after 2 steps. Cause **not isolated**. Found by changing the data of LNN's own `test_Xor_1.py` ([mutate_lnn_tests.py](fuzz/mutate_lnn_tests.py)).

#### F31. The documented square/rectangle example infers nothing. Evidence **A**
*Re-run today* ([repro_lnn_docs_example.py](fuzz/repro_lnn_docs_example.py)): 1 step, 0 facts, query UNKNOWN. The axioms are added without `world=World.AXIOM`; LNN's own test passes that argument and uses `set_query`. A documentation gap, medium at best.

#### F34, F32. Evidence **C**
F34: slightly changed data makes first-order inference in 5 of LNN's own tests not finish in 8 s (13 of 35 changed runs); not minimised, not traced, and those tests use `set_query`, so F28's mechanism does not apply to them. [mutate_lnn_tests.py](fuzz/mutate_lnn_tests.py) `run_guard` (l.131), [run_lnn_test_mutation.py](fuzz/run_lnn_test_mutation.py). F32: input validation (invalid bounds -> `IndexError`, `And()` and duplicate names accepted); low value.

---

## 3. Negative results and where they come from

| Claim | Script |
|---|---|
| Reorder / duplicate / rename change nothing (0 of 351 DPL, 0 of 2,220 Scallop) | [mutate_dpl.py](fuzz/mutate_dpl.py), [mutate_scl.py](fuzz/mutate_scl.py) |
| Scallop equals clingo on 1,000 random deterministic programs | [scallop_vs_clingo.py](fuzz/scallop_vs_clingo.py) |
| Four differentiable provenances match finite differences (80 of 80) | [diff_prov_grad.py](fuzz/diff_prov_grad.py) |
| DeepProbLog exact engine invariant to batching, order, cache (65 programs) | [invariance_dpl.py](fuzz/invariance_dpl.py) |
| DeepProbLog = ProbLog down to 1e-100 on chains | [diff_fuzz.py](fuzz/diff_fuzz.py) `case_d3` |
| LTN operators equal their documented formulas | [ltn_fuzz.py](fuzz/ltn_fuzz.py), [ltn_quant.py](fuzz/ltn_quant.py) |

The exact oracle itself was cross-checked against ProbLog on 132 programs (maximum difference 5.6e-16): [validate_oracle.py](fuzz/validate_oracle.py).

## 4. State of the repository and things that need care

* **Branches.** The harness and report live on `fuzz-ltn-lnn-probfuzz-adaptation` (`d900a6e6`). `main` contains different content: a commit that added about 27,700 files under `.venv/` plus the Rust build directories, and (at the time I first looked) no `fuzz/` scripts. During this session the working tree was switched from `main` to the harness branch. As a side effect, the `.venv` and `.cargo-target*` directories (tracked only on `main`) disappeared from disk, which is why several repros could not be re-run at the end. They can be restored from `main`'s commit `ea860419`. I did not change any git state.
* **Do not push `main` as is**: it contains the virtual environment and build output.
* The framework clones are untracked and unmodified (477 MB).
* `fuzz/repro_scallopy_disjunction_ids.py` was a 0-byte untracked file in the `main` working tree; the branch has the real 29-line script.

## 5. What was checked today and what was not

| | |
|---|---|
| Re-run live | F4/F15 (DeepProbLog zero-probability), F22 (first three lines), F28, F29, F30, F31, F33 |
| Cause read in source and numbers recomputed | F3 (brute force), F24 (arithmetic), F10, F1, F12, F13 |
| Code located, behaviour taken from earlier runs | F2, F7, F9, F19, F20, F21, F23, F26 |
| Not traced | F5, F6, F8, F11, F14 (values), F16 (mechanism), F17, F18, F25, F27, F32, F34, and the *why* for F29, F30, F33 |
