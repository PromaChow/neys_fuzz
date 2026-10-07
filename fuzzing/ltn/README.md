

## What failed, in which test, and why

No operator returned a wrong number, but the library's own asserts did fail, and it is worth being exact about which ones. All failures are an `AssertionError` from a `torch.equal(...)` check (exact equality, not "close") in one of the two operator tests. The line is the first assert that failed in that run (a test stops at its first failure, so anything after it was never checked). The counts are over seeds 1 to 10.

| Fuzzer | Test method | Failing assert | What that line compares | Seeds failed |
|---|---|---|---|---|
| values | `test_Connective` | [tests.py:1189](../../frameworks/LTNtorch/tests/tests.py) | `and_min(op1, op2)` against `torch.minimum(...)` | 10 of 10 |
| values | `test_Quantifier` | [tests.py:1588](../../frameworks/LTNtorch/tests/tests.py) (9), [1599](../../frameworks/LTNtorch/tests/tests.py) (1) | `forall(...)` against `AggregPMeanError(p=2)(..., dim=0)` or `dim=1` | 10 of 10 |
| permute | `test_Connective` | none | – | 0 of 10 |
| permute | `test_Quantifier` | [tests.py:1599](../../frameworks/LTNtorch/tests/tests.py) (8), [1940](../../frameworks/LTNtorch/tests/tests.py) (2) | `forall(y, p(x, y))` against `AggregPMeanError(p=2)(..., dim=1)`; `mean_agg(...)` against `torch.mean(...)` | 10 of 10 |
| swap | both | none | – | 0 of 10 |
| stable | `test_Connective` | [tests.py:1306](../../frameworks/LTNtorch/tests/tests.py) | `and_prod_not_stable(op1, op2)` against `torch.mul(op1, op2)` | 10 of 10 |
| stable | `test_Quantifier` | [tests.py:1982](../../frameworks/LTNtorch/tests/tests.py) | `p_mean_agg(truth_values_2, dim=0)` against `(mean(pi_0(x)^2))^(1/2)` | 10 of 10 |
| float64 | `test_Connective` | [tests.py:1319](../../frameworks/LTNtorch/tests/tests.py) | `and_prod(op1, op2)` against `torch.mul(pi_0(op1), pi_0(op2))` | 10 of 10 |
| float64 | `test_Quantifier` | [tests.py:1940](../../frameworks/LTNtorch/tests/tests.py) | `mean_agg(truth_values_2, dim=0)` against `torch.mean(truth_values_2, dim=0)` | 10 of 10 |

Why each one failed:

- **values (1189, 1588, 1599).** Expected. The fuzzer changed the truth values (for example `AndMin` inputs of `0.4869` became `0.5131` under "complement"), so the test's hand-computed answer no longer matches. This says nothing about the library.
- **permute (1599, 1940).** The fuzzer shuffled the elements an aggregator receives. A mean or power-mean adds the same numbers in a different order, and float32 addition is not associative, so the last bit changes and `torch.equal` fails. The two outputs agree within the 1e-5 tolerance in every case, so the operator is fine. `test_Connective` passes untouched because those operators work element by element and the shuffle is undone on the way out.
- **stable (1306, 1982).** The fuzzer flipped the operator's `stable` flag. The stable version first projects its inputs with `pi_0(x) = (1 - 1e-4)x + 1e-4`, which moves the result by design. In the runs I printed the gap was about 5e-5 for `AndProd` (`0.128963` against `0.129011`) and about 7e-5 for `AggregPMeanError` (`0.810575` against `0.810646`), both well inside the documented 3e-4 bound. Any exact comparison against the unflipped formula must fail.
- **float64 (1319, 1940).** The fuzzer ran the call in float64 and cast the result back to float32. The test's expected value is computed in float32, with a rounding at each step, so the bits differ in the last place. The outputs agree within 1e-5. Worth noting that the calls before line 1319 (`AndMin`, `NotStandard`, and others in `test_Connective`) matched exactly and did not trip anything.

So the failures are about the tests being strict, not about the operators being wrong. A comparison with `torch.allclose` would let the same tests check the same operators without this sensitivity. That is the one real remark I would make about the library's test suite.

## What is fuzzed

LTNtorch's tests live in [tests/tests.py](../../frameworks/LTNtorch/tests/tests.py): 11 tests, all passing unmodified (`result/ltn_tests.json`). Nine of them check types, shapes and error messages of LTN objects (`LTNObject`, `Constant`, `Variable`, `Predicate`, ...) and never call a fuzzy operator. Only `test_Connective` (line 1106) and `test_Quantifier` (line 1515) call the operators in `ltn/fuzzy_ops.py` (the `And*`, `Or*`, `Implies*`, `Not*` connectives and the `AggregMin`, `AggregMean`, `AggregPMean`, `AggregPMeanError` aggregators). Those two tests are the only ones any of the fuzzers can touch, and the other nine are recorded as `not_applicable` in every run.

The plugin ([ltn_mutation_plugin.py](ltn_mutation_plugin.py)) wraps every operator's `__call`__, changes what the test hands to it, lets the test's own asserts run, and records the outcome. It plays the role that `dpl_mutation_plugin.py` plays for DeepProbLog. Unlike that one, which changes a single program per test, this one changes every operator call the test makes (between 1 and 40 calls per test run).


| Script                             | What it changes                                                                                                             | What must happen                                                                                                                                |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| [fuzz_values.py](fuzz_values.py)   | the truth values: boundary (0, 1, 1e-9, 1-1e-9, values around the library's eps = 1e-4), small perturbation, complement     | the tests' hard-coded expected values no longer apply, so a failed assert is expected. Findings would be crashes, hangs, results outside [0, 1] |
| [fuzz_permute.py](fuzz_permute.py) | shuffles the elements given to the operator, then shuffles the result back (aggregators: shuffles along an aggregated axis) | the result must equal an unmutated call within 1e-5                                                                                             |
| [fuzz_swap.py](fuzz_swap.py)       | swaps the two operands of a commutative binary connective                                                                   | within 3e-6                                                                                                                                     |
| [fuzz_stable.py](fuzz_stable.py)   | flips the operator's `stable` flag for the call                                                                             | within 3e-4, the projection bound the library documents                                                                                         |
| [fuzz_float64.py](fuzz_float64.py) | runs the call in float64 and casts the result back                                                                          | within 1e-5                                                                                                                                     |


For the four answer-preserving kinds the plugin calls the operator a second time without the mutation and compares the two outputs numerically. That is the oracle. The tests' own asserts cannot serve as one here, because they compare with `torch.equal` (exact), so any change in the last bit of a float32 trips them. A failed assert with no numeric difference is recorded as `assert_exact_only` and is not a finding.




| Kind    | not applicable | unchanged / still passes | assert failed (expected) | assert failed, outputs within tolerance | findings |
| ------- | -------------- | ------------------------ | ------------------------ | --------------------------------------- | -------- |
| values  | 90             | 0                        | 20                       | n/a                                     | 0        |
| permute | 90             | 10                       | n/a                      | 10                                      | 0        |
| swap    | 100            | 10                       | n/a                      | 0                                       | 0        |
| stable  | 90             | 0                        | n/a                      | 20                                      | 0        |
| float64 | 90             | 0                        | n/a                      | 20                                      | 0        |


- `values`: both operator tests fail their asserts in all 10 seeds, as they should when the inputs are different. Nothing crashed or hung, and no operator returned a value outside [0, 1] that the unmutated run didn't already return.
- `permute`: `test_Connective` is unchanged in all seeds. `test_Quantifier` fails its exact `torch.equal` asserts, but the aggregates agree with an unmutated call within 1e-5, so only the summation order moved a few bits.
- `swap`: only the commutative connectives are swapped (9 of 19 calls in `test_Connective`); `test_Quantifier` has none. Nothing changed.
- `stable` and `float64`: same story as permute. The tests' exact asserts fail, the outputs stay within the tolerance.

I cannot say from this that the operators are correct in general. They survived these mutations on the inputs that these two tests happen to use, which are small random tensors.