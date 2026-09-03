---
name: verify-run
description: Run JobScout's acceptance harness and report what it actually found. Use to verify the build, run the acceptance run, check the output before shipping, decide whether something is shippable, or confirm a change did not break the frozen definition of working.
---

# The acceptance run

`scripts/acceptance.py` is this project's frozen definition of "working". Its
verdict has been misread twice — once because the bar itself was mis-specified,
once because the harness was importing through Gemini while reporting `none`
(R83). Both times the wrong number was written down and survived.

This skill runs the real thing and reports what it found. It does not
re-adjudicate the verdict and it does not retry until green.

## Run it

```bash
python scripts/acceptance.py                    # every fixture, every rung
python scripts/acceptance.py --rung none        # the free-tier floor only
python scripts/acceptance.py --fixture priya    # one fixture
python scripts/acceptance.py --keep             # leave working dirs to inspect
```

`--fixture` takes `glued_runs | priya | two_degrees`; `--rung` takes
`none | gemini | ollama`. Exit 0 on pass, 1 on any gating failure
([acceptance.py:437-441](scripts/acceptance.py#L437-L441)).

No network, no discovery: it runs on the committed corpus
`tests/fixtures/acceptance_jobs.json`, 20 jobs, `use_cache=False`
([acceptance.py:251-268](scripts/acceptance.py#L251-L268)).

**Run the real command every time.** If it was not run, the report says
**"not run"** — never "passes".

## What is gated and what is not

`RUNGS = ("none", "gemini", "ollama")` ([acceptance.py:91](scripts/acceptance.py#L91)),
`ADVISORY = {"ollama"}` ([acceptance.py:105](scripts/acceptance.py#L105)).

A default invocation **executes three rungs and gates on two**. Ollama runs, is
printed with an `(advisory)` prefix on failure, and is excluded from both the
failure list and the gating count. Default gating total: 3 fixtures x 2 rungs =
**6 checks**.

`CLAUDE.md` describes this as "three stranger resumes x both supported rungs".
Neither half is exact: a third rung executes, and one of the three fixtures
(Priya) was written here rather than by a stranger. Neither is a bug. Do not
repeat the phrasing as though it were precise.

**`--fixture priya` only works on the author's machine.** Her profile and resume
are gitignored and `one()` refuses to build a profile it does not own
([acceptance.py:368](scripts/acceptance.py#L368)). Anywhere else that row fails
with *"profile 'priya_raghunathan' does not exist and this script does not own
it"*. Known, not on the frozen list, not being fixed. Report it as the
portability gap it is, not as a regression.

## The frozen list

Seven assertions per fixture per rung, in `assert_the_frozen_list`
([acceptance.py:271](scripts/acceptance.py#L271)):

1. something was scored
2. the best job scores above 40
3. resumes were generated
4. at least one is `valid`
5. every `valid` record has a `pdf_path` and `page_count == 1`
6. every `needs_review` record sits under a `needs_review` path
7. `state["backend"]["used"]` is non-empty and matches the ask — exactly
   `{"verbatim"}` for `none`, and `"verbatim"` absent for any model rung (R79,
   R83)

**The list is frozen.** Anything found while running it goes to
`known_questions.md` as backlog. It does not get added to the checklist.

## How to report

**Failures in full. Passes in one line each.** Do not paste the whole transcript.

**Always state the `needs_review` count**, including when it is zero.
`needs_review > 0` is *not* a failure — the first version of this bar demanded
zero and called a working fabrication guard a failed run
([acceptance.py:289-301](scripts/acceptance.py#L289-L301)). The promise is a
usable resume and no silent bad output, not a model that never misses. A gate
that passes while hiding how much it set aside is R62's silent subtraction
wearing test clothes.

**State which rung imported each resume.** The harness prints it. Its absence is
what let this script claim `none` for four months while Gemini did the importing.

The bar is: **at least one valid resume, and nothing bad escaping.** The
harness's own exit code is the verdict.

## Two annotations the harness cannot make itself

**A failing `gemini` row is run a second time, and both outcomes are recorded.**
Q27 documents that row flipping PASS/FAIL on identical code. R81 is the reason:
Ollama was recorded at 0 of 3, and re-scoring the same output against a corrected
bar made it 1 of 3 — no change to the model or the code. The first number was an
artifact of the measuring bar and would have entered the log as fact.

A disagreement between the two runs **is itself a finding** and is reported as
one. **Do not retry until green.** Two runs, both written down.

**An `ollama` row is reported, never gating.** It cannot be the hosted free tier
— that path is closed deliberately on cost, quality and latency at once. Whether
it is useful *locally* is a separate and undiagnosed claim. Report the row; do
not let it block, and do not read a failure there as a verdict on the rung.

## The invariants

[references/invariants.md](references/invariants.md) maps `CLAUDE.md`'s
never-render-unknown-as-a-value list to where each item is actually observable.

**Only one of them is visible in the acceptance run's own artifacts.** The rest
are pinned by tests, and one — the React "Not scored" beat — is pinned by
nothing at all. **Report which were actually checked.** Implying coverage that
does not exist is the R81 failure in a different costume.

## Encoding

Any harness that prints what it found needs the guard `say()` already carries
([acceptance.py:108](scripts/acceptance.py#L108)). When quoting a finding, write
non-ASCII as a code point — `U+2192`, not `→`. A measurement tool that fails on
some findings is worse than no tool: it reports success on exactly the cases it
cannot render, and those correlate with the interesting ones.

## The other two gates

These are separate from acceptance and gate every commit:

```bash
python -m unittest discover -s tests -q       # the suite
python scripts/baseline.py verify --all       # the three frozen baselines
```

`baseline.py verify` exits 0 clean, 2 on any problem, 1 if no manifests exist.
Three manifests live under `baselines/`.
