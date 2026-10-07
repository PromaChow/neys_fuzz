# DeepProbLog: errors found by fuzzing its own tests

The idea is simple. Take DeepProbLog's own test suite, let the tests run as they are, but quietly change what they feed in (or which component runs underneath), and see what breaks. The code is in [deepproblog/](deepproblog), with a longer write-up in [deepproblog/README.md](deepproblog/README.md).

DeepProbLog can answer a query with an exact engine or with an approximate one. On small programs they should agree. Swapping one for the other under each test turned up four places where they don't. Reordering clauses, duplicating a rule, and renaming a predicate never changed an answer (roughly 1,300 mutated runs), and changing a probability produced no crashes, hangs or probabilities outside 0 to 1.

## The four errors


| #   | Test                                     | What happens                                                                                                                                              | Where it comes from                                                                                                     |
| --- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 1   | [`test_tensor_index`](../frameworks/deepproblog/src/deepproblog/tests/test_builtin.py) (line 17) | the approximate engine crashes with a `PrologError` on a rule whose probability is a variable (`P :: a(I) :- ...`)                                        | [`SWIProgram.assert_all`](../frameworks/deepproblog/src/deepproblog/engines/prolog_engine/swi_program.py), swi_program.py line 206: SWI-Prolog can't parse `P::a(I)`                                      |
| 2   | [`test_less_than`](../frameworks/deepproblog/src/deepproblog/tests/test_builtin.py) (line 30) | for a false query the exact engine returns `{a: 0.0}`, the approximate engine returns nothing, so the test's `result[a]` raises `KeyError`                | grounding: the exact engine registers the query even with no proof, the approximate one doesn't ([engine.py](../frameworks/deepproblog/src/deepproblog/engines/prolog_engine/engine.py) lines 62-63; the exact side is [exact_engine.py](../frameworks/deepproblog/src/deepproblog/engines/exact_engine.py) line 143) |
| 3   | [`test_foreign`](../frameworks/deepproblog/src/deepproblog/tests/test_engine.py) (line 104) | the same difference the other way round: a test written for the approximate engine expects an empty result and gets `{a(2,5): 0.0}` from the exact engine | same cause as 2                                                                                                         |
| 4   | [`test_exhaustive_ad_stays_a_probability`](../frameworks/deepproblog/src/deepproblog/tests/test_semiring.py) (line 137) | the approximate engine refuses a program containing negation (`r :- \+ q.`) with `SWIProgramException: Unhandled body type`                               | [`SWIProgram.add_clause`](../frameworks/deepproblog/src/deepproblog/engines/prolog_engine/swi_program.py), swi_program.py line 179                                                                        |


My reading is that 1 and 4 are features the approximate engine doesn't support (a variable probability, and negation) and 2 and 3 are one inconsistency between the engines in how a false query is reported. That is my reading of the code, not something I've confirmed with the authors, and none of these has been triaged yet. They might all be known limits.

## Things to be honest about

- The engine swap has no randomness, so the 40 raw findings are really these four repeated over 10 seeds.
- 34 of the 83 test items (cache, dataset and the numeric tests) have no program or engine to change at all, so they were never fuzzed.
- The probability mutation helper had a bug at first: it never actually changed the chosen number (an object-identity comparison that could never be true). The probability results here are from after the fix. The same bug is still in the older `fuzz/mutate_dpl.py`.

