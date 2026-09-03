---
name: stranger-fixture
description: Walk a non-author user through JobScout's React UI end to end and log what breaks. Use for a stranger pass, running the stranger fixture, walking a new user through the product, testing as a synthetic or non-author user, or checking onboarding against someone who is not the author.
---

# The stranger pass

Everything this project has shipped broken, it shipped on a path the author does
not walk. Eight defects across R72, R74, R75, R77, R78 and R84 were found this
way and by nothing else. `test_tex_renderer.py` asserted the correct behaviour
the whole time — for its own module, on the path the author uses.

This skill is that method as a procedure. It produces **a defect list**. It fixes
nothing.

## What this pass does and does not cover

**Covered:** the React UI on `localhost:5173` against the FastAPI facade.

**Not covered: Streamlit.** `jobscout-ui` (`scripts/launch_ui.py`) launches
`app.py`, which is what a `pip install` user gets. R84's defect lived exactly
there — the React confirmation screen has an "Add an experience" control and
`app.py` had a permanently disabled button, so a stranger with no model could not
finish an import at all. **A green pass here says nothing about that path.**
Streamlit is intended to go away; there is no decision record for that yet, so
this is a stated gap, not a settled one.

**Also not covered:** nothing under [web/src/](web/src/) has automated tests.
`web/package.json` has `dev`, `build`, `lint`, `preview` — no `test`, and no
`*.test.*` files. R65's 23 filter tests belonged to the deleted `frontend/`.
Every finding here is an eyes-only finding by construction.

## Launch

Two processes, both from the repo root:

```bash
python -m uvicorn api.main:app --reload --port 8000
npm install --prefix web && npm run dev --prefix web        # 5173
```

Leave `JOBSCOUT_ACCESS_SECRET` unset — the Basic-auth middleware at
[api/main.py:109](api/main.py#L109) passes straight through when it is absent.

`python scripts/doctor.py` first if anything looks wrong. Most of what has gone
wrong in this project was setup rather than logic.

## The four rules

**1. One sitting. Fix nothing mid-pass.**
A fix changes the thing being measured. R71's calibration set could not see its
own failure because it globbed only output that had already passed. Finish the
walk, then hand over the list.

**2. Log the screen and the exact input.**
Write non-ASCII as a code point, never as a glyph — `U+2192`, not `→`. R81's
acceptance harness *crashed while printing the first real finding it had ever
produced*, because a validation error quoted a bullet containing `U+2192` on a
cp1252 console. A measurement tool that fails on some findings is worse than
none: it reports success on exactly the cases it cannot render, and those
correlate with the interesting ones. R77 recorded a data defect that did not
exist for the same reason — the code points were correct and the terminal could
not print them.

**3. The fixture must differ on every axis.**
See [references/axes.md](references/axes.md). A fixture you wrote agrees with you
(R77, R78) — Priya was invented here, so she can only contain problems somebody
thought of. **A pass that finds nothing means the fixture is too close to the
author, not that the product is clean.** Before concluding "no defects", check
the axis table and name which axes the fixture actually exercised.

**4. A defect list only.**
No triage, no severity ranking, no fixes, no "while I was in there". Findings go
to `known_questions.md` as backlog entries. **The acceptance list in
`scripts/acceptance.py` stays frozen** — anything found here does not get added
to it.

## The walk

Screen by screen, in this order. [references/walkthrough.md](references/walkthrough.md)
has what to try on each and the log format.

| # | Screen | Component |
|---|---|---|
| 1 | Resume upload | [ResumeStep.tsx](web/src/components/steps/ResumeStep.tsx) |
| 2 | Import confirmation | [ImportConfirm.tsx](web/src/components/ImportConfirm.tsx) |
| 3 | About you | [AboutYouStep.tsx](web/src/components/steps/AboutYouStep.tsx) |
| 4 | Preferences | [PreferencesStep.tsx](web/src/components/steps/PreferencesStep.tsx) |
| 5 | Tuning | [TuningStep.tsx](web/src/components/steps/TuningStep.tsx) |
| 6 | Run | [RunStep.tsx](web/src/components/steps/RunStep.tsx) |
| 7 | Board | [Board.tsx](web/src/components/Board.tsx), [BackendPanel.tsx](web/src/components/BackendPanel.tsx) |

Wizard order is `STEPS` in [Wizard.tsx:14](web/src/components/Wizard.tsx#L14).

## What to look for, specifically

Two failure families account for most of what this method has found.

**Unknown rendered as a value.** Nothing may display or score "not yet known" as
though it were known. Every field with a "not yet" state needs three cases —
known, absent, unknown — carried all the way to whatever displays or ranks it.
Watch every field that loads *after* the screen mounts: a loading state is not an
empty state, an empty state is not a zero, and a zero is not a "no". The React
board rendered every job as **"Not scored"** for the beat before score bands
arrived, which is a claim where a placeholder was wanted. The sharpest version
(R75): a Save button gated on levels derived from years, where an unanswered
years field derives none — so the fix for R72's dead button rebuilt the same dead
button one field over.

**A filter that removes things without saying how many.** R62. The board states
its count under the current filters. Any list that is shorter than what was
stored owes the reader a number.

## Finishing

Hand over the log from [references/walkthrough.md](references/walkthrough.md) and
nothing else. Say which axes the fixture exercised and which it did not. If the
pass found nothing, say that the fixture may be too close rather than that the
product is clean.
