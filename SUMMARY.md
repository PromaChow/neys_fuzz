# One-page summary: testing neurosymbolic AI libraries

## 1. The problem
Libraries that combine neural networks with logic rules compute **probabilities** (DeepProbLog, Scallop, NeurASP) or
**truth degrees between 0 and 1** (LTNtorch, LNN). When they have a bug they often do not crash. They print a plausible but
wrong number, or quietly never finish, so ordinary tests miss it.

## 2. A bug anyone can follow
It will be sunny with probability 0.5 or cloudy with probability 0.3, never both.
How likely is "sunny or cloudy"? The correct answer is 0.5 + 0.3 = **0.8**.
Scallop answers **0.65**, and **1.0** with its fix-flag turned on. No error is printed.

## 3. What we did
We tested five libraries with four methods:
1. change real tests slightly and check the answers still make sense (mutation);
2. generate random programs and compare with the exact answer;
3. run each library's sister tool's tests through it (ProbLog for DeepProbLog, clingo for NeurASP);
4. check internal consistency (same program under every setting, gradients against numerical derivatives).

We also took the published fuzzer **ProbFuzz** (ESEC/FSE 2018, 67 bugs found in Stan, Pyro and Edward) and adapted its
code to these libraries. Because our programs are small and discrete, we can compute the exact right answer, so a wrong
answer is provable.

## 4. What we found (candidates, none reported yet)
Five defects with standalone repro scripts:
- Scallop mixes up mutually exclusive facts: 0.6489 instead of 0.8272 (`fuzz/repro_disjunction.py`).
- Scallop's Python interface returns all zeros for two categorical inputs, the digit-sum case it is advertised for
  (`fuzz/repro_scallopy_disjunction_ids.py`).
- DeepProbLog's approximate engine loses the answer when a fact has probability exactly 0 (`fuzz/repro_dpl_zero.py`).
- NeurASP crashes on valid logic programs (`fuzz/repro_neurasp_parse.py`).
- DeepProbLog's approximate engine crashes on negation. This may be an undocumented limit.

Four more in the two fuzzy-logic frameworks:
- LNN: `infer()` never returns when a quantified formula is added with `add_knowledge()` (5 of 8 cases), as in its own
  documentation (`fuzz/repro_lnn_exists_hang.py`).
- LNN: `infer()` can also run forever on a three-operand `XOr` with an input of 0.999, and on its own first-order tests when
  their data is changed slightly (`fuzz/repro_lnn_xor_hang.py`, `fuzz/run_lnn_test_mutation.py`).
- LNN: two identical sub-formulas built as separate objects are left UNKNOWN even when every input is known
  (`fuzz/repro_lnn_duplicate_subformula.py`); a single-operand `And(A)` crashes (`fuzz/repro_lnn_unary_connective.py`).
- LTNtorch: the default `ImpliesGoguen()` scores "false implies false" as about 0 instead of 1
  (`fuzz/repro_ltn_goguen_stable.py`).

Plus about twenty-five smaller defects (full list in `README.md` and `REPORT.md`), and many checks that **held up**:
reordering and renaming never changed results, Scallop agreed with clingo on 1,000 random programs, and DeepProbLog's
exact engine agreed with ProbLog. For the fuzzy-logic frameworks, all 15 LTN connectives and 6 aggregators match their
documented formulas, and LTN and LNN agree on 1,304 of 1,304 random Lukasiewicz formulas without repeated sub-formulas.

## 5. How big the work is, in plain words
- **More than 50,000 program runs and checks.** Each is one library evaluated on one program or operator input, with its answer checked.
- **A trustworthy answer key.** Our checker computes the true probability by listing every possible world. To be sure
  the checker itself is right, we compared it with ProbLog on 132 programs. The biggest disagreement was
  0.00000000000000056, which is just rounding. So when it says a library is wrong, the checker is not the problem.
- **A log of false alarms.** More than ten results looked like bugs and turned out to be our own mistakes or limits of the
  reference tool. We ruled them out and did not count them. Example: ProbLog returns 0.0 for very tiny probabilities, so a
  "difference" there is ProbLog's limit, not DeepProbLog's bug.

## 6. Next
Check the strongest findings against the newest releases, report them to the maintainers, and test the neural parts more.

## Honest limits
None of the findings is confirmed by maintainers yet. The ProbFuzz adaptation re-found known bugs and added no new ones,
so its value is the method. Coverage is thin for the neural tests (21 of 50 DeepProbLog test inputs were not mutated).
