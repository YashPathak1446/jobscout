# JobScout — build plan and progress

**From working engine to paying users.** Six phases, ~28 working days, at
6 h/day and 6 days/week.

This is the tracking document. `known_questions.md` remains the decision log —
every `R<n>` and `Q<n>` referenced here lives there, and this file never
duplicates a decision, only points at one.

### Where this came from

The plan was written on 2026-08-27 and existed only inside that session. R82
recorded the consequence — *"Phase 1 is a container image and a worker surviving
multi-minute runs. Neither exists, neither is written down anywhere in this
repo."* This file is that gap closed. The estimates below are the original ones
and are **not** edited as work happens; only the actual columns are filled in.

---

## Status at a glance

| Phase | Planned | Planned finish | Actual | Actual finish | Variance | State |
|---|---|---|---|---|---|---|
| **0** · Freeze, prove, publish, watch | 5 d | ~Sep 2 | 1 d | 2026-08-27 | **−4 d** | **reopened** — see below |
| **1** · Containerised + deployed, one user | 6 d | ~Sep 9 | — | — | — | not started |
| **2** · Multi-user data model | 6 d | ~Sep 16 | — | — | — | not started |
| **3** · Auth and accounts | 5 d | ~Sep 22 | — | — | — | not started |
| **4** · Waitlist + manual invoicing | 1 d | ~Sep 23 | — | — | — | not started |
| **5** · Presentation and launch prep | 5 d | ~Sep 29 | — | — | — | not started |
| | **28 d** | | | | | |

**Optimistic 5 weeks. Realistic 6–7, so early-to-mid October.** The buffer is
not padding: Phase 1 holds the one genuine unknown.

> **On the variance column.** Phase 0 came in at a fifth of its estimate, and
> the plan predicted that — *"Phase 0 compressed because it was documentation of
> things already true."* R82's reading is that this is **luck rather than the
> rate**, because two items that were real work (the wheel rendering nothing,
> and publishing turning out to be four separate problems) were absent from the
> estimate entirely. This table takes no position. It records both numbers so
> the second data point settles it.

---

## The calendar, week by week

Six working days per week. Planned dates assume Phase 0 began 2026-08-27.

| Week | Dates | Planned | Actual |
|---|---|---|---|
| 1 | Aug 27 – Sep 2 | Phase 0 (5 d) | Phase 0 done in 1 d, then reopened |
| 2 | Sep 3 – Sep 9 | Phase 1 (6 d) | — |
| 3 | Sep 10 – Sep 16 | Phase 2 (6 d) | — |
| 4 | Sep 17 – Sep 22 | Phase 3 (5 d) | — |
| 5 | Sep 23 – Sep 29 | Phase 4 (1 d), Phase 5 begins | — |
| 6 | Sep 30 – Oct 6 | Phase 5 completes; buffer | — |
| 7 | Oct 7 – Oct 13 | buffer | — |

---

## Phase 0 — Freeze, prove, publish, watch

**The phase that ends the bug hunting.** Nothing after it is discovery.

- [x] **Day 1** — write `scripts/acceptance.py` and freeze the list
- [x] **Days 2–3** — fix only what it catches *(it caught three: a valid resume
      reporting 0 pages, the report crashing on its own first failure, and the
      bar itself demanding zero `needs_review`)*
- [x] **Day 4** — the Ollama measurement (R81)
- [x] **Day 5 am** — publish the local version *(exceeded: `v0.2.0` on PyPI, not
      just tagged)*
- [ ] **Day 5 pm** — watch one real person use it — **skipped by decision
      (2026-08-27)**, deferred to Phase 5's verification, which is the same test
      against the hosted flow

Unplanned, pulled forward because publishing exposed it:

- [x] Packaging and path resolution — ten modules resolved paths from `__file__`,
      so an installed wheel had no LaTeX preamble and would have written user
      data into `site-packages` (R80)

### Exit criteria

> `python scripts/acceptance.py` passes, `v0.1-engine` is tagged and released,
> and one person who is not you has produced a resume with it.

| Condition | State |
|---|---|
| `scripts/acceptance.py` exits 0 | **unmet — reopened**, see R83 |
| Tagged and released | **met** — `v0.2.0` on the remote and on PyPI |
| One real person has used it | **skipped by decision**, deferred to Phase 5 |

**Why it reopened.** The acceptance run pinned the rung for the pipeline but not
for the resume import, so all three rows imported through whatever backend was
detected — the `none` row included, while claiming to be *"the rung a stranger
with no key lands on"*. Fixed 2026-08-27 (R83). With the pin honest, two of the
three fixtures now fail on `none`, because the no-model floor cannot produce a
resume the pipeline will run (Q26). **That red is the gate telling the truth for
the first time**, and closing it is a real piece of work, not a formality.

---

## Phase 1 — Containerised and deployed, one user (6 d)

It runs somewhere that isn't your laptop. **Deliberately before accounts exist**
— containerised TeX Live and a worker surviving a multi-minute run are the two
things most likely to go wrong, and finding that out in week 2 with one user is
far cheaper than in week 5 with an auth system on top.

- [ ] Dockerfile with a trimmed TeX Live (`texlive-latex-extra`, ~1 GB — Q8b)
- [ ] A worker that survives runs taking minutes — `orchestrator.start_run`
      already backgrounds them against `data/runs.db`, so the change is **where
      that store lives**, not how it works
- [ ] A host (Fly / Railway / Render)
- [ ] Object storage for resumes
- [ ] Secrets, domain, TLS
- [ ] Deploy with your own profile as the only user

### Exit criteria

> The acceptance run passes **against the deployed instance**, not against
> localhost. A resume compiles in the container.

---

## Phase 2 — Multi-user data model (6 d)

Two people cannot overwrite each other. Q15 lists the blockers and calls them
*"cheap now, expensive later"*. Every store already takes a path, so this is
threading a `user_id`, not a redesign.

- [ ] `EmbeddingCache` — one global file keyed on resume hash
- [ ] `job_cache.json` — likewise
- [ ] Outputs keyed on date alone, so two users on one day overwrite each
      other's `state.json`
- [ ] The shared LLM cache — a **privacy** boundary here, not a correctness one

### Exit criteria

> Two profiles run on the same day and neither overwrites the other's
> `state.json`, embeddings or outputs.

---

## Phase 3 — Auth and accounts (5 d)

Strangers can sign up.

- [ ] A managed provider (Clerk / Supabase Auth / Auth0). Rolling your own is
      10+ days and a security liability on a system holding other people's
      resumes
- [ ] Bind sessions to the `user_id` from Phase 2

### Exit criteria

> Sign up as a stranger in a private window; reach a resume without touching a
> config file.

---

## Phase 4 — Waitlist and manual invoicing (1 d)

It can take money, without billing infrastructure. **Not Stripe** — checkout
plus a webhook is two days, but what kills the estimate is everything around it:
a business entity or sole-proprietor tax handling, terms of service, a refund
policy, and the metering that stops a paid user costing more than they pay. A
resume runs 2–3¢, so 200 a month on a $10 plan is fine and 2,000 is not. That is
a quota system, and quota systems are where "4 days" goes to die.

- [ ] A waitlist
- [ ] An email
- [ ] An invoice sent by hand

**Build real billing when manual invoicing becomes annoying** — that annoyance
is the signal it is worth building, and it arrives with the usage numbers that
tell you what the quota should be.

### Exit criteria

> One invoice sent by hand is paid, and the account it belongs to gets the paid
> path. Ten of those before any billing code is written.

---

## Phase 5 — Presentation and launch prep (5 d)

It can be shown to someone.

- [ ] Landing page
- [ ] Onboarding copy
- [ ] Empty and error states
- [ ] Privacy policy
- [ ] A data-deletion path — **mandatory**, you are storing strangers' resumes

### Exit criteria

> Someone who has never seen it reaches a PDF unaided — the same test as Phase
> 0's afternoon, repeated against the hosted flow rather than the local one, now
> that there is an onboarding path to test.

**This now carries Phase 0's skipped item.** It is the only check in the plan
that asks whether anyone *wants* this, as opposed to whether it works.

---

## The rules that keep this finite

1. **The acceptance list is frozen before Phase 0 starts.** Nothing is added
   mid-flight.
2. **No new stranger-resume passes until after launch.** That method finds bugs
   forever. Turning it off is a decision, not an oversight.
3. **The acceptance run is re-run at every phase exit, and a failure there is
   always in scope.** Phase 1 puts LaTeX in a container and Phase 2 moves every
   store — both can break the engine, and catching that is exactly what the run
   is for. **Regression is in scope; discovery is not.**
4. **Every bug found outside the acceptance run is logged and not fixed** —
   `known_questions.md` is the backlog.
5. **One phase at a time.** The next does not start until the current phase's
   exit check passes.
6. **At 150% of a phase estimate, cut scope rather than extend time.** If Phase 3
   overruns, create the first accounts by hand — the same move Phase 4 already
   makes for billing, applied one phase earlier.
7. **`python -m unittest discover -s tests -q` and
   `python scripts/baseline.py verify --all` still gate every commit.**

---

## Explicitly not in this MVP

Deferring these is the plan, not an omission.

- **Q26** — the no-model floor cannot produce a runnable resume *(new, and it is
  what currently holds Phase 0 open)*
- **Q27** — the acceptance run is not reproducible on any rung that uses a
  model *(new, and it bears on rule 3 at every phase exit below)*
- The place vocabulary for non-US locations and school-name leakage (R78)
- PDF kerning splits on the free tier — the model already repairs them (R77)
- `_chat_tailor`'s missing repair loop (R76)
- Q3's page-fill headroom; Q23's job-posting dates; Q9's embedding migration
- A public job board — tried and dropped 2026-08-26 (R66)
- Fields beyond tech roles — three named blockers in `CLAUDE.md`

---

## How to update this document

At each phase exit: tick the boxes, fill **Actual**, **Actual finish** and
**Variance** in the status table and the week row, and set the state. **Never
edit the Planned columns** — a baseline you revise is a baseline that always
agreed with you, which is the whole failure R82 was written about. If a phase's
scope changes, say so in its section and leave the estimate standing.
