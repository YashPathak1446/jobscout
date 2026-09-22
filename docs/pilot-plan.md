# JobScout — from one user to a friends pilot

## Context

JobScout works and got its author hired, but **zero other people have used it**.
`plan.md`'s gate 1 has been "built, not deployed" since 2026-08-28; the last
commit was 2026-09-08. The destination is a hosted, paid product, and the next
step is **4–5 friends (CS students through 10-year engineers) on a hosted
instance giving feedback**, while the author applies with it himself.

**Decided:** one multi-tenant Fly app, not five single-tenant ones. The hard
constraint is **$10/month maximum**, and five always-on machines is $20–40.
Fly's auto-stop does not rescue that — it stops on idle HTTP and a background
run thread is not HTTP traffic, so it would kill runs mid-flight. The
consequence is accepted deliberately: the invite slips by weeks, and in exchange
every hour spent goes into the paid product rather than into five deploys that
get thrown away.

**No fixed date, and no feature compromises.** Work runs in the background
alongside other projects. Estimates below are focused-work days, not calendar.

---

## Load-bearing decisions

### 1. Partition the data home. Do not rebuild the `jobs` table.

Hosted layout becomes `data_home()/users/<uid>/` holding that user's `jobs.db`,
`runs.db`, `user_profiles/`, `master_resumes/`, `outputs/` and all four caches.
`tools/paths.py:19-23` says in its own docstring that it was built as this seam.

**Chosen over** a `postings` + `user_jobs(user_id, url)` split. That is the
textbook answer and it is wrong at this size: a table rebuild (the
`_ADDED_COLUMNS`/`_migrate` mechanism at `job_store.py:166-178` only does
additive nullable columns), a `user_id` predicate on ~20 `JobStore` methods, and
a deletion path that must reason about shared rows.

What the partition fixes *without editing the code that has the bug*:

- `url TEXT PRIMARY KEY` becomes correct again — a posting is a singleton
  within one person's board, which is what the schema always meant.
- `job_store.refresh_gate` (`:217-219`) stops overwriting the other user's
  `gate_reason` on every board render (an O(n) write storm plus wrong
  eligibility for both).
- `job_store.score_bands` (`:438-449`) stops computing quartiles over everyone's
  scores; its docstring's per-person claim becomes true again.
- `run_registry.recent()`/`active()` stop leaking every user's `output_dir` and
  `error` text through `GET /api/run` and `/api/runs`.
- `available_profiles()`, `/api/profile/{name}` and the shared `RESUME_DIR` in
  `_resolve_upload` (`api/main.py:361-365`) become correct by construction.

**Authorization by partition beats authorization by predicate — there are fewer
places to forget.**

**Breaks if wrong:** at ~100+ users, disk and re-scrape volume bind and you move
to a shared postings table on Postgres. That migration is a *union* of N SQLite
stores, which is easier than splitting one — so the rebuild skipped here was
never the migration you'd actually run. You pay later, with revenue.

**Hard constraint:** `python scripts/baseline.py verify --all` measures against
`outputs/` and `user_profiles/` at the checkout root. The unscoped layout must
stay byte-identical. `data_home()` is unchanged; the scoped layout is entered
only when a user id is supplied. The checkout supplies none, the container does
— so both forks are walked by harnesses that already exist (the R70 rule
satisfied rather than asserted).

### 2. Self-hosted cookie session, not Clerk

`tools/accounts.py` → `data/accounts.db` (`user_id`, `email`, `hashlib.scrypt`
passphrase hash, `invite_code`, `created_at`, `deleted_at`). `POST /api/session`
sets an **HttpOnly, Secure, SameSite=Strict** cookie carrying
`HMAC-SHA256(user_id|expiry)` under `JOBSCOUT_SESSION_SECRET`, compared with
`secrets.compare_digest` — the primitive already at `api/main.py:143`.
Invite-only, no public signup, no password reset. ~60 lines, zero new deps.

**Rejected Clerk:**

1. `api.fileUrl()` (`web/src/lib/api.ts:186`) returns a bare URL used as an
   `<a href>`. A bearer token cannot ride an href without rewriting downloads
   into fetch-and-blob. A cookie is sent automatically; Clerk's SDK is
   token-shaped.
2. It makes the deletion test unwritable — walking the data home says nothing
   about Clerk's servers, and deletion is a hard requirement.
3. `requirements.txt` is deliberately the install list for people running the
   app, not a dev manifest.

Revisit at the paid boundary, where public signup and billing identity exist.

**Breaks if wrong:** a signing mistake means forged identity and a friend's
resume read. Mitigations ship in the same commit: hard expiry inside the signed
payload, `compare_digest`, tests for tampered / expired / absent cookie → 401.

### 3. Fail closed

`api/main.py:127-129` passes through when `JOBSCOUT_ACCESS_SECRET` is unset —
correct for localhost, catastrophic if the variable is dropped from `fly.toml`.
That is R89's shape: a deploy instruction naming a variable nothing reads. Add
`JOBSCOUT_MODE=local|hosted`; **hosted with no session secret refuses to boot**,
with a test asserting the refusal.

### 4. No Gemini key of the author's is ever set on the hosted app

**Decided.** `GOOGLE_API_KEY` is *not* a Fly secret. Each friend brings their
own free-tier key. Rationale: one shared free key across five users hits the
daily cap and makes runs fail for reasons nobody can see, and a paid key does
not fit the $10 ceiling.

This also means `fly.toml` must **not** carry `GOOGLE_API_KEY` — R89 corrected
the variable *name* there; this changes the decision to omitting it. With no
env key, `config.resolve_api_key` returns `""` and the instance defaults to the
`none` rung, which is a complete product (see below). That is consistent with
gating the deployed acceptance run on the `none` row (Q27).

**The key is never stored server-side, at 5 users or at 50.** Verified today:
never persisted, never logged, `POST /api/backend` takes it in the body not the
query string (`api/main.py:198-201`), `config.resolve_api_key(explicit)` is the
single resolution point, `start_run(profile_name, api_key="", ...)` already
threads it to every agent. It lives in the user's browser `localStorage`, rides
the POST body, lives in process memory for the run, and dies with it. At the
paid tier the question disappears — we run it on our key and the user never has
one. No user key is ever stored server-side in either tier.

**Breaks if wrong:** `localStorage` is XSS-readable. Acceptable while the app
renders no user-submitted HTML. Re-evaluate at public signup.

---

## Stage A — the pilot (~11–14 focused days)

### A0. Fly egress probe — before anything else (½ day)

If Greenhouse, Lever or Ashby block datacenter IPs, hosting on Fly is in
question and everything built before finding out was built on sand.

Deploy a throwaway machine, hit a sample of the 113 slugs in
`tools/assets/ats_companies.json`, and **compare status codes against the same
run from a home connection as a control**. Q32 is why this needs status codes
rather than counts: `ats_search._fetch` returns `None` for 403, 429, 404 and a
Cloudflare HTML-200 alike, every reader turns that into `[]`, and Sentry sees no
exception — so from a datacenter IP a block is indistinguishable from an empty
board.

Ships regardless of the result: carry per-status-code counts into the run result
so "0 discovered" can say why.

### A1. Fix the facade parity test — first, because everything leans on it (1 hr)

`tests/test_ui_contract.py:173-175` is `assertTrue((api_names & facade) <=
facade)`. An intersection with `facade` is a subset of `facade` for **every
possible input** — the assertion is a tautology, and `only_api` is computed for
the failure message and never asserted on. The one test standing between
Streamlit and React diverging asserts nothing, and `user_id` is about to enter
every facade signature. Five lines.

### A2. Reproduce the two-user bugs (½ day, nothing ships)

Add a second fixture user built from one of the anonymized stranger resumes in
`tests/fixtures/` — **not** derived from Priya, because a fixture derived from
one you have is a fixture that agrees with you. The two profiles must differ in
the fields `gate_fingerprint` hashes (`job_filter.py:775-800`) or the storm test
cannot fire.

1. `refresh_board_gate(A)`, `(B)`, `(A)` → the third call re-judges **zero**
   rows. Today it re-judges all of them.
2. A scores 8 jobs ~40, B scores 8 ~90 → A's `score_bands()` does not move.
3. Two runs on the same date → `previous_runs()` returns two entries and A's
   `state.json` is intact.
4. `GET /api/runs` as B → A's `output_dir` and `error` strings are absent.

### A3. The scope seam and the threading — one commit (3–4 days)

`tools/paths.py` gains `user_home(user_id)` / `user_path(user_id, *parts)` with
**no default user**. An omitted id is a `TypeError`, never an ambient fallback —
an ambient default is unknown rendered as a value.

**Explicit parameter, not a `ContextVar`.** `start_run` spawns a
`threading.Thread`, and context vars do not propagate into new threads; the
worker would resolve to the wrong user and write a resume into a stranger's
outputs with no error anywhere.

Every facade function in `agents/orchestrator.py` that touches user data takes
`user_id` first: `board_jobs`, `board_total`, `board_stats`, `board_filters`,
`board_job`, `job_selection`, `job_history`, `ghosted_jobs`, `score_bands`,
`set_job_status`, `refresh_board_gate`, `start_run`, `run_status`,
`active_runs`, `recent_runs`, `previous_runs`, `load_run`,
`available_profiles`, plus a new `user_outputs_root(user_id)` exported the way
`outputs_root` already is at `api/main.py:69` — `tests/test_ui_contract.py:23`
leaves no alternative.

**Pairs that must land together — there is no correct intermediate:**

| Pair | Why |
|---|---|
| `outputs_root(user)` + `/api/file` containment (`api/main.py:579-582`) | Partition first and the guard still permits cross-user download; tighten first and every download 404s |
| `JobStore` path + `refresh_gate` + `score_bands` | One correctness unit; any gap is a window where one user's render overwrites another's `gate_reason` |
| All **four** caches | `job_cache.py:27`, `embedding_cache.py:24`, `config.py:122`, `config.py:114`. Relocate three and the fourth is the one nobody walks. Closes Q31 |
| `RunRegistry` path + `/api/run` + `/api/runs` | Per-user `runs.db` makes these correct automatically |

**The landmine:** `tools/resume/embedding_scorer.py:176` — `_EMBEDDING_CACHE` is
a **module-level singleton, one per process**. Under `--workers 1` the first
user's request builds it and every later user in that process inherits that
directory. It fails silently: wrong vectors for the right text still produce a
plausible score. Key the memo by `user_id` or pass the cache down. This is the
only item in A3 with no error path.

Secondary: `job_store.py:41` and `run_registry.py:38` compute `DEFAULT_DB` at
import time. Both constructors accept an explicit path — always pass one, and do
not leave the constant reachable from a hosted path.

**Closing move (the R80 shape):** `test_no_store_resolves_a_path_outside_paths`
— AST-walk `tools/`, `agents/`, `config.py`; fail on any string literal bound to
`*_DIR|*_DB|CACHE*` not produced by a `tools.paths` call. Fails on cache #5.

### A4. Work authorization (1–1½ days)

**In Stage A, immediately after the seam.** This is the one bug that hits an
individual friend regardless of tenancy, and the pilot pool includes F-1 and
H-1B holders. Today they would see jobs they cannot take, on day one.

#### What is wrong

`web/src/components/steps/AboutYouStep.tsx:93-101` derives two booleans from a
dropdown: `us_citizen = visa_status === 'US Citizen'`, `permanent_resident =
visa_status === 'Green Card'`. So `F1 OPT`, `F1 CPT`, `H1B` **and `Other /
prefer not to say`** all collapse to `false/false`. Prefer-not-to-say silently
asserts non-US-person — a direct violation of "unknown is never a value".

`holds_security_clearance` is absent from `NEEDS_HUMAN`
(`init_profile.py:53-56`), so nothing tells a user it went unanswered.
`visa_status` is read by nothing behavioural. `CitizenshipRestrictions`
(`profile_schema.py:48-52`) is a dead class.

#### The model

```
personal_info.work_authorization:
    us_person:         "yes" | "no" | "unknown"
    needs_sponsorship: "yes" | "no" | "unknown"
    holds_clearance:   "yes" | "no" | "unknown"
```

`Literal[...]` defaulting to `"unknown"` — **not** `Optional[bool]`. A string
cannot be silently coerced by `bool()` at a call site that forgot the third
case, which is exactly how `_is_us_person` (`job_filter.py:453-457`) turns a
missing attribute into a confident `False` today.

- `visa_status` stays free text for display, documented as reading nothing.
- Delete `us_citizen` / `permanent_resident`. Keeping them alongside guarantees
  a fix lands on one and not the other. Precedent: R66/R68 removed fields and
  pydantic ignores extra keys, so old profiles still load.
- **Do not add clearance level, OPT/STEM-OPT end date or EAD.** Nothing reads
  them — `posting_demands` does not distinguish Secret from TS/SCI. Adding them
  is instance seven of the recurring bug. Log as questions.

**Migration table** (table-driven test including the absent cases — R75: any
test that walks a range has not walked the absence):

| stored | → |
|---|---|
| `us_citizen: true` | `us_person: yes`, `needs_sponsorship: no` |
| `false` + `visa_status == 'Green Card'` | `yes` / `no` |
| `false` + `F1 OPT \| F1 CPT \| H1B` | `no` / `yes` |
| `false` + `''` or `'Other / prefer not to say'` | **`unknown` on all three** |
| key missing entirely | **`unknown`** |

Row four is the point. `tools/assets/profile_template.json:17-18` ships
`false/false`, so every profile the current wizard produces has that shape
unless the user picked Citizen or Green Card. `yash_pathak.json` maps to `yes`
and is the one profile this change cannot test — build against Priya and the
second stranger.

#### Where the gate goes

**Do not add `eligibility_disqualifiers` to `evaluate`.** Its absence is
correct: `evaluate` runs pre-enrichment on title plus snippet, where
`posting_demands` returns all-`False` — that would be a second silent pass.

The real defect is R61's shape. `agents/enrichment_agent.py:145-162` falls back
to `job.description` on a scrape failure with `scraped_successfully: False`.
`_apply_body_gate` (`orchestrator.py:992-1030`) runs `body_disqualifiers` on
that snippet, which returns `[]` for thin text (`job_filter.py:544-545`), and
the job is stored `gate_reason = ""` — **eligible**. The orchestrator already
reads `scraped_successfully` in `_split_unreadable` (`:1071-1090`), but at
*generation*, not at the gate.

Three parts, one change:

1. `gate_reason` returns a three-valued verdict — shown / hidden /
   **undecidable** — rather than `"" | reason`. Add a discriminator rather than
   overloading the empty string.
2. `_apply_body_gate` marks `scraped_successfully is False` rows `undecidable`.
   `tools/jobs/posting_facts.py` — production code whose only importer is its
   own test — has `demands_basis` for exactly this. Wiring it here turns a dead
   module into its consumer.
3. Same verdict when `work_authorization == "unknown"` meets a posting that does
   demand: **shown, badged and counted**, never silently eligible and never
   silently hidden. Unknown-as-eligible ships the prefer-not-to-say bug;
   unknown-as-ineligible empties the board for every new user, since the
   template starts `false/false` and `Wizard.tsx:111-115`'s `onSkipAhead` lets a
   returning user skip step 1 entirely. The badge is also the nudge that closes
   that hole.

`gate_fingerprint` (`:775-800`) must hash the three new names — it will, because
the names change, so every stored row re-judges once. Bounded, now that stores
are per-user.

#### The onboarding question set

Derived from the resume (do not ask): name, email, phone, GitHub, LinkedIn,
school, degree, graduation date/term.

Asked — all three eligibility questions go into `NEEDS_HUMAN`:

1. Where are you based? *(exists)*
2. **Are you a US citizen or green-card holder?** yes / no / prefer not to say
3. **Will you need visa sponsorship, now or in future?** yes / no / prefer not
   to say — the question employers actually ask, and not derivable from
   `visa_status`: an H-1B holder needs a transfer, an F-1 on OPT needs future
   sponsorship, a green-card holder needs none
4. **Do you hold an active security clearance today?** yes / no / prefer not to
   say
5. Target roles · 6. Years of experience (`None` is a real state — R75) ·
   7. Locations, remote, relocation · 8. Skip postings mentioning *(all exist)*

Deferred, logged as questions: minimum salary (there is **no** salary field in
the user schema at all — it exists only job-side) and `employment_types` (in the
schema, in both profiles, surfaced by no UI, read by nothing — full-time /
intern / contract is a real filter for the students in the pilot, but wiring the
consumer is the price of adding it).

### A5. Accounts, session, per-route authorization (1½–2 days)

Lands **after** A3 — until the data is partitioned an ownership check returns
403 over data that is still physically shared, which is authorization theatre.

- `/api/health` returns the **caller's** profiles, not `available_profiles()`
  over a shared directory.
- `web/src/lib/api.ts` has **five** fetch sites, not two: `get` (`:135`),
  `send` (`:155`), `fileUrl` (`:186`), `extractResume` (`:193`),
  `createProfile` (`:207`). A cookie covers all five.
- No router. `web/src/App.tsx` grows a third state
  (`'signin' | 'setup' | 'board'`) on the `useState` it already has.

### A6. The delete path (½ day)

`DELETE /api/account` (there are currently **zero** `@app.delete` routes).
Facade: `agents.orchestrator.delete_user_data(user_id) -> dict` returning
counts, because the API may not import `tools.*`. Removes the `users/<uid>/`
tree in full, the accounts row, the event log rows, and the session cookie. Not
a soft delete, and it **returns what it removed** — "a filter that removes
things must say how many", pointed at deletion.

`test_no_byte_of_a_deleted_user_survives`: create user B, run under `--mock`,
delete, then walk the entire data home asserting the user id and the profile's
`personal_info.name` appear in no path and no file's bytes, and no database
holds a row. That walker is reused verbatim by A7.

**State the limit rather than overclaim it.** Fly volume snapshots and Sentry
events live outside the data home and outside the walker. Acceptable for a
friends pilot; it goes in the privacy copy so "deleted" never means more than it
does.

**`scripts/admin.py` ships with this (≈1 hr).** Invite-only with no password
reset means *you are the reset flow*. Four subcommands — `invite`,
`reset-passphrase`, `list-users`, `delete-user` — with the last calling the same
`delete_user_data` facade rather than a second deletion path, because two
deletion paths is the twin-path bug pointed at the one thing that must be
provably complete. Without this, the first friend who forgets their passphrase
costs you hand-editing `accounts.db` over SSH.

### A7. Bring-your-own-key, built properly (1 day)

Not a paste box. The full step:

- **A step-by-step AI Studio page with screenshots.** This is the narrowest
  point in the funnel and the most likely place a friend quits.
- **A "test this key" button that makes one real cheap call before saving.**
  `POST /api/backend` already takes a candidate key in the body and reports
  which rung would run — extend it from a presence check to an actual call, so
  a typo'd key fails at paste time rather than eight minutes into a run.
- **A plain sentence that free-tier content may be used by Google to improve
  their models**, next to the field, not buried.
- **Instrument drop-off at this step** (see A8) — whether friends quit here is
  a pilot finding, and a pilot that does not measure its own narrowest point is
  wasting the friends.
- Stored in `localStorage`, sent only in POST bodies.

**Not a gate.** `none` is a complete product: discovery, scoring, component
selection, one-page layout and a compiled PDF — a real resume tailored *by
selection*, with bullets copied verbatim from the master resume instead of
reworded per posting. A friend who skips the key gets that, not an error. If the
key UI blocks the run, it is R72's dead button rebuilt.

**What `none` scores with, since most friends will meet it first.**
`config.py:105` sets `EMBEDDING_BACKEND = "auto"`: Gemini
(`gemini-embedding-001`) when a key resolves, otherwise the local
`minishlab/potion-base-8M` (`config.py:109`). Genuinely semantic, not
keyword-only — but **weaker, and unverified as a ranking**. `acceptance.py`
passing 3 of 3 on `none` proves a compiled one-page PDF, not that the ordering
is sane. Add an explicit check: run Priya's fixture on both embedding backends
and read the top 10 side by side. If `none`'s ranking is bad, that is the first
experience of every friend who skips the key, and it changes whether the key
step should be more strongly encouraged.

**Rate limits — check the page, do not trust a number here.** Gemini's quotas
are **per Google Cloud project**, i.e. per key, so with BYO key each friend has
their own and concurrent friends do not contend. The real exposure is inside one
user's run: bursting past requests-per-minute on a 30-job run (~40 calls), and
the daily request cap for someone running several times a day. Google has cut
free-tier limits more than once, so read the current AI Studio rate-limit page
at build time rather than relying on any figure written down here.
**Action, unchanged:** find out whether the Gemini client backs off on a 429 or
fails the run, and add backoff if it does not. With one user this never came up.

`test_the_api_key_never_lands_anywhere`: run the pipeline with a sentinel key
through the mock rung, then reuse A6's walker over the data home **plus a
captured log handler**. A runtime walk, not a grep of the source — so it fails
when a sixth call site starts logging the config it resolved.

### A8. The feedback loop and what counts as success (½ day)

The pilot's purpose is feedback and nothing currently collects any.

**A per-user event log** — one SQLite table under `users/<uid>/`: run started,
run finished, resumes generated, status changed, key saved, key step abandoned,
onboarding step reached. Counts and timestamps only, no content. Covered by the
A6 deletion walker.

**A success criterion, written before the invite so it cannot be renegotiated:**
each friend applies with **≥5 generated resumes within two weeks**. Below that,
the failure modes separate cleanly — they never finished onboarding (funnel),
they finished and did not run (discovery), or they ran and did not use the
output (tailoring quality). Each points at different work.

**Making that measurable, because as written it is not.** "Applies with ≥5"
only appears in the log if friends mark jobs applied, and they may not. So
measure the pair — **resumes generated** (unambiguous, server-side) **and status
changes to an applied stage** (intent, but self-reported) — and accept that the
gap between them is a question you ask them directly. A metric that silently
undercounts is worse than one you know is partial.

**Absences need a paired event.** "Key step abandoned" is a thing that does not
happen, so it cannot be logged. Emit a client-side **`reached_key_step`** and
read abandonment as its presence with no subsequent `key_saved`. The same shape
applies to every funnel step worth measuring — log arrival, infer the drop.

**A feedback button** in the UI that opens a prefilled email. Friends will not
file issues.

### A9. Sentry (1 hr)

After A5, so it never ships in front of an unauthenticated instance.
`send_default_pii=False` plus a `before_send` that scrubs the API key and
truncates exception values — `run_registry.fail(run_id, f"{type(exc).__name__}:
{exc}")` already puts scrape URLs and JD fragments into an error string Sentry
would capture verbatim.

### A10. Concurrency, reaper, machine size (½ day)

- **One active run per user**, enforced server-side. Five simultaneous runs in
  one process under `--workers 1` is five threads scraping and embedding on one
  machine.
- **Stale-run reaper**: `state='running' AND updated_at < now - N min →
  'failed'`. One restart with in-flight threads leaves permanent spinners, and
  that is the first thing a friend sees. None exists today.
- **Auto-stop must stay off, and that needs a test.** `fly.toml:60-62` is
  already correct — `auto_stop_machines = "off"`, `auto_start_machines = true`,
  `min_machines_running = 1`. So this is not a change, it is a **guard**: Fly
  stops on idle HTTP and a background run thread is not HTTP traffic, so
  enabling auto-stop would kill in-flight runs silently. It is the same shape as
  the fail-closed issue — a setting that breaks runs with no error if someone
  later "optimizes" it. Add a deploy check or a test that parses `fly.toml` and
  fails on `auto_stop_machines != "off"` or `min_machines_running < 1`.
  The $4–8/month estimate assumes this always-on machine.

- **Check memory headroom against the $10 cap.** `fly.toml:86-87` already
  declares `shared-cpu-1x` / `1gb`, so the question is whether **512 MB**
  suffices — roughly halving the compute line. The lever is in R86's notes:
  `pyarrow` is 156 MB and arrives via `streamlit`, which exists for `app.py` —
  the local UI the container never serves. With `pandas` and `pydeck` that is
  ~290 MB of a 565 MB site-packages tree. Verify the saving against Fly's
  current pricing at deploy rather than against the numbers here.

- **Trimming streamlit forces a dependency split, and that has to be decided
  here.** `requirements.txt` is deliberately the install list for people running
  the app locally, not a dev manifest — and `app.py` is one of the two supported
  UIs, so streamlit cannot simply be dropped. The container needs either its own
  requirements file or an extras split (`[hosted]` vs the local default). Decide
  which in A10; discovering it at `docker build` is how this becomes a deploy-day
  surprise.

### A11. Resume pre-flight on the friends' real resumes (½ day)

Before inviting, run each friend's actual resume through `extract_resume`
locally and read the output. The pool spans CS students to 10-year engineers, so
formats and lengths vary far beyond Jake's template. Two specific things to
look at: whether the parser produces a sane profile, and whether the
3-experience / 1-page defaults make sense for someone with ten years — that is
R74's bullet-budget problem waiting to happen. Cheap, and it is the last chance
to find a parser bug before it costs a first impression.

### A12. Deploy, acceptance, invite (½ day)

Deploy and run `scripts/acceptance.py` against the instance, gated on the `none`
row (Q27: a gemini row flips PASS/FAIL on identical code, and with no key on the
instance `none` is what it runs anyway). Seed the volume with Priya's fixture at
`/data/user_profiles/priya_raghunathan.json` and
`/data/data/master_resumes/priya_raghunathan.{tex,pdf}` — the doubled `data/` is
real. Then invite.

**Discovery breadth last, after the invite is proven:** enable Adzuna
(`adzuna_search.py` is fully implemented and needs only `ADZUNA_APP_ID` /
`ADZUNA_APP_KEY`) and grow `tools/assets/ats_companies.json` beyond its current
113 slugs across 5 boards. Measure one user's `jobs.db` growth first — each
source multiplies disk and embedding cost by N users on one volume.

---

## Stage B — the tracker (deferred until friends ask for it)

The design holds, but it is a guess at what they want and the pilot exists to
replace guesses. Ship the free wins any time; build the rest on request.

**Free wins, already built and unused:** `GET /api/board/ghosted` is end-to-end
and React never calls it. `api.job(url)` is exposed in `api.ts` and nothing in
the React tree calls it — `JobDetail.history` is already typed. `table.tsx`,
`card.tsx`, `tooltip.tsx`, `separator.tsx` are vendored shadcn components sitting
unused. The `.dark` block in `index.css` is complete and nothing ever adds the
class.

**When it is built:** `STATUSES` becomes a 15-tuple, **additive only** — keep
`new`/`seen`/`applied`/`rejected`/`archived` verbatim, because renaming forces a
`status_history` rewrite and leaves history rows failing future validation.
Additive means no data migration.

**One `status` column, not stage + last-event.** `status_history` already *is*
the last-event table. Add `STATUS_STAGE: dict[status -> stage]` in
`job_store.py` (`not_applied` / `applied` / `in_process` / `closed`).

**The silent casualty:** `job_store.ghosted()` (`:286-307`) is `WHERE
j.status='applied' AND h.status='applied'`. With 15 states that inverts — moving
`applied → coding assessment` and then hearing nothing for five weeks *is*
ghosting, and the query will never report it. Fewer rows, no error: R62's silent
subtraction in the one feature the board exists for. `ghosted()` must read
`STATUS_STAGE` and measure from the most recent history row in any
"ball in their court" status.

**Labels move onto the facade in the same commit.** `job_statuses()` returns
`[{value, label, stage}]`, `/api/health` carries it, `app.py:1219`
`STATUS_LABELS` is deleted, React groups the `Select` by stage. Otherwise it
ships the twin-path divergence on day one — Streamlit has labels, React renders
raw `snake_case`, and `.get(s, s)` means neither crashes.

**"Date applied" sort** is a new key in `SORTS` (`job_store.py:317`) over a
correlated subquery on `status_history` — server-side, because the view is
contractually forbidden from building SQL.

**Columns:** company + link, role, status, match score, date applied, salary,
qualifications, reason for rejection — plus **which resume was sent**,
**source**, and **next action / date**. Dense table, not kanban; nobody drags a
card to "Ghosted". Row expands in place. Load Inter — the `cv02/cv03/cv04/cv11`
font features in `index.css` already assume it and currently do nothing.

---

## Stage C — Workday

Most of the Fortune 500 runs `myworkdayjobs.com` and there is zero coverage.
This is what the 6–10-year friends hit first. A new fetcher alongside the five
in `BOARDS` (`ats_search.py:254`). Per-tenant endpoints make it the most brittle
item here, which is why it is last — Adzuna plus a wider seed list may close
enough of the gap that it never has to happen.

---

## Verification

Both gates on every commit:

```bash
python -m unittest discover -s tests -q
python scripts/baseline.py verify --all
```

End-to-end, in order:

1. `python -m agents.orchestrator --profile priya_raghunathan --max-jobs 5 --mock`
   still passes unscoped — the checkout fork must not move.
2. `docker build --target verify` — baselines plus `acceptance.py --rung none`
   inside the container, 3 of 3.
3. Two-user acceptance: create a second account, run both under `--mock`,
   assert the A2 tests pass.
4. `DELETE /api/account` then the residue walker.
5. Deploy; `scripts/acceptance.py` against the instance on the `none` row.
6. Egress probe from Fly and from home, comparing status codes (this one runs
   first, at A0, and again after deploy).

Bug-class tests, each written to fail on the *next* instance:

- `test_no_store_resolves_a_path_outside_paths` — fails on cache #5
- `test_every_facade_that_touches_user_data_takes_a_user_id` — `inspect.signature`, fails on facade #25
- `test_every_route_is_authenticated` — enumerate `app.routes`, fails on route #23
- `test_every_route_that_names_a_resource_checks_ownership` — user B gets **404**, not 403 (403 confirms existence), **plus a companion asserting the table covers every route**
- `test_no_byte_of_a_deleted_user_survives` — fails on store #5
- `test_the_api_key_never_lands_anywhere` — runtime walk plus log capture
- `test_unknown_work_authorisation_is_never_a_no` — table-driven over the option list **read out of `AboutYouStep.tsx:24-31`**, not retyped; a retyped list agrees with you
- `test_the_machine_never_scales_to_zero` — parse `fly.toml`, fail on `auto_stop_machines != "off"` or `min_machines_running < 1`. Correct today; this stops a later "optimization" from silently killing in-flight runs
- `test_the_hosted_image_carries_no_gemini_key` — `fly.toml` must not set `GOOGLE_API_KEY`; friends bring their own

---

## Explicitly not in this plan

Payments · public signup · password reset · clearance level · OPT expiry dates ·
salary preferences · `employment_types` · non-tech roles · Postgres · a job
board (R66) · mobile · the Q28 repair-loop asymmetry (logged, not fixed) ·
landing page and public posting (plan.md gates 3–4, parked until friends have
used it).
