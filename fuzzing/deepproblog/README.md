# DeepProbLog: findings from the engine-swap fuzzer

## 1. test_tensor_index: PrologError (exact swapped to approximate)

Test: [test_builtin.py](../../frameworks/deepproblog/src/deepproblog/tests/test_builtin.py), `test_tensor_index`, starting at line 17.

```python
program = """
P :: a(I) :-  list_to_tensor([0.25,0.1,0.4,0.15], Tensor), between(0,3,I), tensor_index(Tensor,[I],P).
"""
model = _create_model(program)
r = model.solve([Query(Term("a", Var("X")))])[0].result    # line 23, this is where it fails
```

The head of the rule has a variable probability (`P :: a(I)`), which the exact engine handles. With the approximate engine the call goes `Model.solve`, `Solver.solve`, `build_ac`, `ApproximateEngine.ground`, `PrologEngine.get_proofs`, `SWIProgram.query` and finally `assert_all` in [swi_program.py](../../frameworks/deepproblog/src/deepproblog/engines/prolog_engine/swi_program.py), line 206:

```python
for line in self.get_lines():
    self.prolog.assertz(line)
```

SWI-Prolog is handed the clause text `cl(1,P::a(I),[...])` and rejects it with a syntax error ("operator expected"), which pyswip raises as `PrologError`. So the approximate engine doesn't seem to support a variable in the probability position. I'd guess that's a known limitation rather than something unintended, but it fails late and with a fairly unhelpful message.

## 2. test_less_than: KeyError (exact swapped to approximate)

Test: [test_builtin.py](../../frameworks/deepproblog/src/deepproblog/tests/test_builtin.py), `test_less_than`, line 30, failing at line 38.

```python
assert pytest.approx(0.0) == model.solve([q1])[0].result[Term("a")]
```

Query `a` is false (the program asks whether 0.8 < 0.2). The test expects the answer to be present with probability 0.0. With the approximate engine there is no `a` entry in the result at all, so the dictionary lookup raises `KeyError`.

I traced where the two engines split. Grounding the query `a` on the same program gives:

```
exact  | ground formula: queries = [('a', None)]  | result = {a: 0.0}
approx | ground formula: queries = []              | result = {}
```

`ExactEngine.ground` ([exact_engine.py](../../frameworks/deepproblog/src/deepproblog/engines/exact_engine.py), line 143) hands the query to ProbLog's `engine.ground(db, query, label=...)`, which puts the query into the formula even when it has no proof, so it later evaluates to 0.0. The approximate path in [prolog_engine/engine.py](../../frameworks/deepproblog/src/deepproblog/engines/prolog_engine/engine.py), lines 62-63, does `proofs = self.get_proofs(term, sp)` and then `sp.add_proof_trees(proofs, ...)`. For a false query `proofs` is empty, nothing is added, and the query never appears in the result. So it happens at grounding, before any probability is computed.

## 3. test_foreign: assert 1 == 0 (approximate swapped to exact)

Test: [test_engine.py](../../frameworks/deepproblog/src/deepproblog/tests/test_engine.py), `test_foreign`, line 104, failing at line 123.

```python
q = Query(Term("a", Constant(2), Constant(5)))    # evaluate(2) is 4, so a(2,5) is false
r = model.solve([q])[0]
assert len(r.result) == 0
```

 Here the test was written for the approximate engine, and it expects an empty result for a false query. With the exact engine the result is `{a(2,5): 0.0}`, so the length is 1. So the two engines disagree on whether a false query is reported as 0.0 or left out. `test_model.py` accepts either form for the same situation, which suggests the authors know about it, but I didn't find anything written down saying which is intended. The cause is the same grounding difference as number 2: the exact engine always registers the query, the approximate one only registers queries that have at least one proof.

## 4. test_exhaustive_ad_stays_a_probability: SWIProgramException (exact swapped to approximate)

Test: [test_semiring.py](../../frameworks/deepproblog/src/deepproblog/tests/test_semiring.py), `test_exhaustive_ad_stays_a_probability`, line 137. The model is built by the helper `_saturated_model` (line 113), which calls `set_engine(ExactEngine(model))`.

```python
program = """
nn(sat,[X],Y,[c0,c1,c2,c3,c4,c5,c6,c7,c8,c9]) :: c(X,Y).
q :- c(i,_).
r :- \\+ q.
"""
```

The error is raised in `add_clause` in [swi_program.py](../../frameworks/deepproblog/src/deepproblog/engines/prolog_engine/swi_program.py), line 179:

```python
if type(node.body) is Term:
    body = [node.body]
elif type(node.body) is And:
    body = node.body.to_list()
else:
    raise SWIProgramException("Unhandled body type")
```

The rule `r :- \+ q.` has a negation as its body, which is neither a plain term nor a conjunction, so the approximate engine's program loader gives up. It fails inside `set_engine`, before any query is asked. So negation looks unsupported in the approximate engine, though at least this one gives a readable error message.



