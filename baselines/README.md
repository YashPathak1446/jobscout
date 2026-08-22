# Measurement baselines

A baseline is a frozen set of enriched job descriptions plus the analysis
they produced. Scoring changes are judged by re-running against one and
diffing the component selection — that is what makes claims like R14's
"8/20 selections changed" mean anything.

## Why the contents are not in git

The files carry employer names, resume-derived reasoning strings, and whole
generated resumes. Keeping them out is the same decision as the rest of the
repo's privacy posture. What *is* committed is a manifest per baseline:
checksums, byte counts and record counts, no content.

That way a lost or altered baseline is **detectable** rather than silent —
which is the actual risk. A missing directory announces itself the first
time you try to measure something. A baseline that quietly changed does not,
and it would make two sets of numbers look comparable when they are not.

## Commands

```bash
python scripts/baseline.py write   2026-08-21-pre-step7   # record a manifest
python scripts/baseline.py verify  2026-08-21-pre-step7   # check against it
python scripts/baseline.py verify  --all
python scripts/baseline.py archive 2026-08-21-pre-step7   # pack for backup
```

`verify` exits non-zero when anything is missing or changed, so it can gate a
measurement run.

## Keeping a copy

`archive` writes a zip **outside** the repo. Move it somewhere durable — a
cloud drive or an external disk. It is the only copy that survives losing the
machine, and the manifest in git can tell you a baseline is wrong but cannot
give it back.

## If a baseline is lost

You cannot recreate it exactly. Discovery pulls live job boards, so the same
command a week later returns different postings. You can create a *new*
baseline and measure future changes against that, but previously recorded
numbers stop being comparable — say so in `known_questions.md` rather than
quietly re-measuring against a different instrument.

To create a fresh one:

```bash
python -m agents.orchestrator --profile <name> --max-jobs 20
cp -r outputs/<date> baselines/<new-name>
python scripts/baseline.py write <new-name>
python scripts/baseline.py archive <new-name>
```

## Current baselines

| name | recorded | contents | used by |
|---|---|---|---|
| `2026-08-21-pre-step7` | 2026-08-21 | 20 enriched JDs, 20 analysis records, 3 resumes | R14, R15, R16, Q7's null result, and every Step 7 measurement |
