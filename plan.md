# JobScout — ship in a week

**Revised 2026-08-28.** The six-phase plan below the line was optimised for
correctness before contact. This one is optimised for contact.

`known_questions.md` remains the decision log. This file is the tracker.

---

## The arithmetic that changed the plan

Ten days of work. 1035 tests, three frozen baselines, 84 decision records, two
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

**Day numbers were dropped on 2026-09-02.** The plan was written on 2026-08-28
as five consecutive days. What happened was one working day (08-28), four
calendar days with no commits, and one day spent on tooling that was not on
this plan (09-02). A unit that has stopped measuring anything is worse than no
unit — "Day 3" now names neither a date nor an amount of work. The gates below
are ordered and they are not dated, because the ordering is the real content
and the dates were the fiction.

| # | Gate | State |
|---|---|---|
| **1** | React + FastAPI in a container, TeX Live, on Fly, your profile as the only user | **built, not deployed** — see below |
| **2** | Managed auth (Clerk or Supabase) + `user_id` threaded through the stores | not started |
| **3** | Landing page — what it does, who it is for, a screenshot, a signup | not started |
| **4** | Post it. r/cscareerquestions, Hacker News, new-grad Discords, LinkedIn | not started |

Gate 1 is the only one whose *state* has ever been wrong in this file. It read
"not started" until 2026-09-02, four days after the commit that built it
(`20ef0fb`). Check the tree before writing a state into this table.

**No payments.** Free while you find out whether anyone wants it. Billing is
Phase 4's content and Phase 4 does not start until people are using this.

### Gate 1 — the genuine unknown

This is the only part that can fail for technical reasons, which is why it is
first. **Five of six items are done and the sixth is the whole point of the
gate.** Verified against the tree on 2026-09-02, not from memory.

- [x] `fastapi` + `uvicorn` declared; `api` added to `packages` in `pyproject.toml`
      *(`pyproject.toml:49-50`, `:76`)*
- [x] FastAPI serves the built React (`StaticFiles`) *(`api/main.py:598`, mounted
      last, which is load-bearing)*
- [x] Dockerfile: node build stage for `web/`, python stage, `texlive-latex-extra`
      *(claimed three stages and had two until R86; the third is `verify`,
      which adds `tests/` and `baselines/` and is never deployed)*
- [x] Fly volume for `data/` — `runs.db`, `jobs.db`, caches, master resumes
      *(`fly.toml`, `jobscout_data` → `/data`, with `JOBSCOUT_HOME` anchored there)*
- [x] Shared secret in front of everything, so the instance is testable without
      being open *(`api/main.py:109`, `tests/test_hosted_boundary.py`)* — this
      was the sequencing fix below, and it landed with the container
- [x] **The image builds and passes its own gates locally** — `--target verify`
      runs the baselines and `acceptance.py --rung none` inside the container,
      3 of 3, and a smoke run against `--target runtime` confirms `/healthz` is
      open, `/api/board` is 401 without the secret and 200 with it, and the
      React build serves (R86). The suite does **not** fully pass in-image; see
      Q29, and it does not block acceptance
- [~] Secrets: Gemini key via `fly secrets`, never in the image — **decided and
      written down** (`fly.toml:67`), executes at deploy
- [ ] **Deploy, then run `scripts/acceptance.py` against the instance** —
      **all three fixtures, and PDF import does get tested on Fly.** Priya's
      `.tex`, `.pdf` and profile are committed as of 2026-09-07 (`git add -f`,
      an exception; the ignore patterns stand), so nothing has to be published
      to run the full gate.
      One mechanical step remains and it is not a blocker: `.dockerignore`
      keeps `data/` and `user_profiles/` out of the image by design and a Fly
      volume starts empty, so the deploy **seeds the volume from the committed
      fixture** — safe now precisely because those files are synthetic and in
      the repo. Without that seed the run is two fixtures and silently loses
      the only PDF-import test.
      This item read "two fixtures, not three" for part of one day, on the
      premise that Priya was a real person and could not be published. She is
      not; see R88.

**Everything except the deploy is done.** The remaining item is not the small
one: it is the only step that produces information nobody here has. A container
that builds is not a container that runs, and the acceptance run against a
deployed instance is what Phase 0 was frozen in order to make possible.

Note what the last item costs on a model rung: Q27 says a gemini row flips
PASS/FAIL on identical code, so gate on the `none` row against the instance and
read the rest as a measurement with a date.

**Worker: keep the thread.** `start_run` backgrounds against `data/runs.db`, so
the change is where that store lives, not how it works. A restart loses an
in-flight run; for one user that costs one re-run. An always-on machine (no
scale-to-zero) is what makes that acceptable — and it is the reason for Fly
over Render's spin-down.

### Gate 2 — auth

An afternoon, not five days. Managed provider; rolling your own is a security
liability on a system holding other people's resumes. The account-readiness
audit already found every store takes a path, so this is threading a `user_id`,
not a redesign.

### Gates 3–4 — the part that has never been done

Landing page, then post it. **Tech roles only** — see the hold below.

- [ ] **Error reporting before posting.** A free Sentry tier, ~20 minutes.
      Without it, a run that fails for a stranger on the deployed instance is
      something you find out about never — and the failure criteria above
      cannot tell *"product not wanted"* from *"product broken"*, which is the
      one distinction the week exists to make.

---

## Before it is public

Eight weak points were raised against this plan. **Seven hold, one does not**,
and the checking mattered — the wrong one had a real bug hiding inside it.

| # | Claim | Verdict |
|---|---|---|
| 1 | 19 endpoints, no auth | **holds** — the only `session` matches in `api/main.py` are comments |
| 2 | `/api/file` path traversal | **wrong** — already resolves and containment-checks against `outputs/` |
| 3 | No rate limiting | **holds** — every `limit` match is pagination |
| 4 | No deletion path | **holds** — zero `@app.delete` routes |
| 5 | Datacenter IP scraping | **unknown, and correctly flagged** — not answerable from here |
| 6 | Shared LLM cache | **holds, smaller than stated** — see below |
| 7 | Q17 becomes user-facing | **holds** |
| 8 | No error reporting | **holds** — zero Sentry/Rollbar references |

**The correction that matters most.** `/api/file` is not traversable —
`?path=../../etc/passwd` resolves outside `outputs/` and gets a 404, and the
docstring explains why. But the *second half* of that claim is real and is a
**different bug**: there is no user check, so once accounts exist, anyone who
knows a path can fetch anyone's generated resume. That is finding 1, not
traversal, and fixing traversal would not have touched it.

**Finding 6, precisely.** `llm_cache` stores `{model, cached_at, prompt_chars,
response}` — the prompt is hashed, never written, so **raw resumes are not on
disk in the cache**. What is stored is `response`: the rewritten bullets,
which are resume-derived. One global `.cache/llm` directory holding fragments
of everyone's work history. Still a privacy boundary, smaller blast radius
than "everyone's resume".

### The sequencing problem nobody listed

`api/main.py` pinned CORS to `http://localhost:5173`, and **that line was the
only thing between 19 unauthenticated endpoints and the internet** — which is
what made authorization a precondition of deploying rather than a gate 2 task.

**Resolved by `20ef0fb` (2026-08-28), and the reasoning was corrected on the
way.** The CORS list did not need replacing: deployed, it is simply *unused*,
because the API serves the React build from its own origin, so the browser
never makes a cross-origin request (`api/main.py:88-94`). What needed replacing
was the protection it had been providing by accident, and that is the shared
secret. Do not "fix" CORS for the deploy; there is nothing there to change.

So authorization is not a gate 2 task that happens to come after the deploy —
it is a **precondition of the deploy being reachable**. The cheap resolution
keeps the week intact:

- [x] Gate 1 ships behind a **single shared secret** (HTTP basic or a header
      check, ~20 min) so the instance is testable without being open — **done**,
      `api/main.py:109`, landed with the container on 2026-08-28
- [ ] Gate 2's managed auth replaces it, and every endpoint gets an
      authorization check — not just a sign-in — because *"people can log in"*
      and *"people can only see their own data"* are different properties and
      the second is the one a stranger notices

### Carried, with dates rather than vibes

- [ ] **Deletion and retention** — a legal obligation the moment the first
      stranger uploads, not the Phase 5 polish item the old plan had it as.
      Needed before gate 4, before posting.
- [ ] **Rate limiting on `/api/run`** — it triggers a multi-minute job that
      spends quota. One run per user is an existing guard; a request-level
      limit is not. Needed before gate 4. Pairs with Q24's spend ceiling.
- [ ] **Scraping from Fly's egress** — verify discovery still works from a
      datacenter IP on day one of the deploy. Cloudflare in front of an ATS
      behaves differently for cloud ranges than for a residential connection.
      This can break discovery outright and there is no fallback.
- [ ] **The LLM cache** — per-user or disabled hosted, before strangers share
      an instance.

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
  part of gate 1 rather than before it: the exit check is this run against
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
| **The week** · deployed, auth, posted | 5 d | 2 d over 6 calendar days | **gate 1 built, not deployed**; gates 2–4 not started |
| *After validation* | — | — | gated on users existing |

### Phase 0 — what closed it

- [x] Write `scripts/acceptance.py` and freeze the list
- [x] Fix only what it catches *(three: a valid resume reporting 0 pages, the
      report crashing on its own first failure, the bar itself demanding zero
      `needs_review`)*
- [x] The Ollama measurement (R81)
- [x] Publish — `v0.2.0` on PyPI, not just tagged
- [x] Packaging and path resolution, pulled forward (R80)
- [ ] Watch one real person — **skipped**, now after gate 4 against the URL

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
boundary. Gate 2 does the minimum of this; the rest waits.

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
