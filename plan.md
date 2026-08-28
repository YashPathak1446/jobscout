# JobScout — ship in a week

**Revised 2026-08-28.** The six-phase plan below the line was optimised for
correctness before contact. This one is optimised for contact.

`known_questions.md` remains the decision log. This file is the tracker.

---

## The arithmetic that changed the plan

Ten days of work. 1019 tests, three frozen baselines, 84 decision records, two
PyPI releases. **Zero people have used it.** Not one.

The single item capable of producing failure — *watch one real person use it* —
has been on the list since it was written and has never moved. It keeps losing
because every other item is reachable from a terminal and it is not.

**You cannot fail fast while deferring the only thing that can produce
failure.** The old plan had five to six more weeks of infrastructure before a
stranger touched it. That is fail-slow with extra steps.

So: one week to a URL. Everything else is what you build *after* people show
up, not in case they do.

---

## The week

| Day | Work | Done |
|---|---|---|
| **1–2** | React + FastAPI in a container, TeX Live, deployed on Fly, your profile as the only user | [ ] |
| **3** | Managed auth (Clerk or Supabase) + `user_id` threaded through the stores | [ ] |
| **4** | Landing page — what it does, who it is for, a screenshot, a signup | [ ] |
| **5** | Post it. r/cscareerquestions, Hacker News, new-grad Discords, LinkedIn | [ ] |

**No payments.** Free while you find out whether anyone wants it. Billing is
Phase 4's content and Phase 4 does not start until people are using this.

### Days 1–2 — the genuine unknown

This is the only part of the week that can fail for technical reasons, which
is why it is first.

- [ ] `fastapi` + `uvicorn` declared; `api` added to `packages` in `pyproject.toml`
- [ ] FastAPI serves the built React (`StaticFiles`) — nothing does today
- [ ] Dockerfile: node build stage for `web/`, python stage, `texlive-latex-extra`
- [ ] Fly volume for `data/` — `runs.db`, `jobs.db`, caches, master resumes
- [ ] Secrets: Gemini key via `fly secrets`, never in the image
- [ ] Deploy, then run `scripts/acceptance.py` **against the instance**

**Worker: keep the thread.** `start_run` backgrounds against `data/runs.db`, so
the change is where that store lives, not how it works. A restart loses an
in-flight run; for one user that costs one re-run. An always-on machine (no
scale-to-zero) is what makes that acceptable — and it is the reason for Fly
over Render's spin-down.

### Day 3 — auth

An afternoon, not five days. Managed provider; rolling your own is a security
liability on a system holding other people's resumes. The account-readiness
audit already found every store takes a path, so this is threading a `user_id`,
not a redesign.

### Days 4–5 — the part that has never been done

Landing page, then post it. **Tech roles only** — see the hold below.

---

## What counts as failing

Stated in advance so it cannot be renegotiated afterwards.

- **Nobody signs up** → the idea is not wanted in this form. One week spent,
  not six. Go build the finance app.
- **People sign up and do not finish onboarding** → the product is wanted and
  the funnel is broken. Q25 and Q26 become the work, with real evidence.
- **People finish and do not come back** → the output is not good enough.
  Q17, Q3 and the tailoring quality work become the roadmap.

All three are useful. Only the current state — nobody has tried — is not.

---

## The hold I am not moving on

**All roles is not a week-one thing.** You said you want to expand from tech
while building, and `CLAUDE.md` names three real blockers:

1. Greenhouse/Ashby/Lever skew heavily to tech — discovery would return
   little for a nurse or an accountant
2. The LaTeX template is a one-page tech resume with a projects section
3. Q17's vocabulary-over-role-type problem gets worse where "analyst" means
   five different jobs

A non-tech user who signs up and gets six software postings churns immediately
and tells people it does not work. **Launch to tech, which is millions of
people. Expand when tech users are retained** — that is evidence you can act
on rather than a guess you have doubled.

## Two more things being carried, not fixed

- **Q24 — spend ceiling.** Its own text names this deploy as the date it goes
  live. A Cloud budget alert plus a hard quota on the key before the URL is
  reachable. This is a settings page in your Google Cloud console, so it is
  yours to do, not something in this repo.
- **Q27 — the acceptance run is not reproducible on model rungs.** Taken as
  part of Days 1–2 rather than before them: the exit check is this run against
  the deployed instance, and a gate that flips on identical code cannot say
  whether the container broke anything. If extraction caching runs past an
  hour, gate on the `none` row alone and move.

## And the user session

Do it **after** deploy, on the URL, with someone who found it rather than
someone you asked. That is the version that tells you something.

---

## Status

| | Planned | Actual | State |
|---|---|---|---|
| **Phase 0** · Freeze, prove, publish | 5 d | 1 d | **done**, 1 item skipped |
| **The week** · deployed, auth, posted | 5 d | — | not started |
| *After validation* | — | — | gated on users existing |

### Phase 0 — what closed it

- [x] Write `scripts/acceptance.py` and freeze the list
- [x] Fix only what it catches *(three: a valid resume reporting 0 pages, the
      report crashing on its own first failure, the bar itself demanding zero
      `needs_review`)*
- [x] The Ollama measurement (R81)
- [x] Publish — `v0.2.0` on PyPI, not just tagged
- [x] Packaging and path resolution, pulled forward (R80)
- [ ] Watch one real person — **skipped**, now Day 5+ against the URL

| Exit condition | State |
|---|---|
| `acceptance.py` exits 0 | **met, on a narrower row than it first read as.** 3 of 3 on `none` from `.txt` inputs through the floor, no model (`imported by: none`). The row includes a committed human correction (R84), so it covers *floor + a person*, **not unattended import** — which the design never promised. Not reproducible on model rungs (Q27). |
| Tagged and released | **met** — `v0.2.0` on the remote and on PyPI |
| One real person has used it | **skipped by decision**, moved to after deploy |

---

# After validation — the original phases

**Do not start any of these until people are using it.** Kept because the
content is right; only the timing was wrong.

**Multi-user data model (6 d).** Q15's blockers: `EmbeddingCache` is one global
file keyed on resume hash, `job_cache.json` likewise, outputs keyed on date
alone so two users on one day collide, and the shared LLM cache is a privacy
boundary. Day 3 does the minimum of this; the rest waits.

**Waitlist and manual invoicing (1 d).** *Not* Stripe. What kills the estimate
is the entity, the ToS, the refund policy, and the metering that stops a paid
user costing more than they pay. Build real billing when manual invoicing
becomes annoying — that annoyance is the signal, and it arrives with the usage
numbers that tell you what the quota should be.

**Presentation (5 d).** Onboarding copy, empty and error states, privacy policy
and a data-deletion path — **mandatory**, you are storing strangers' resumes.

## The rules that still apply

1. **No new stranger-resume passes.** That method finds bugs forever; turning
   it off is a decision, not an oversight.
2. **The acceptance run is re-run at every deploy, and a failure there is in
   scope.** Regression is in scope; discovery is not.
3. **Every bug found outside the acceptance run is logged and not fixed.**
4. **At 150% of an estimate, cut scope rather than extend time.**
5. **`python -m unittest discover -s tests -q` and
   `python scripts/baseline.py verify --all` gate every commit.**

## Explicitly not in the week

Q26 (how much typing the floor asks of a stranger) · Q25 (the installed-to-
looking gap — a URL dissolves it) · Q23 posting dates · Q9 embedding migration
· Q3 page-fill headroom · non-tech roles · a public job board (R66) · mobile
apps · payments.
