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

## Stage A — the pilot (~11–14 focused days, plus A9b)

A0–A6 are done (A0–A3 2026-09-22, A2 on 2026-09-21; A4 R92–R94; A5 R95; A6
R96). A9b was split out of A0 and adds 1–1½ days.

### The remaining order (revised 2026-09-23)

The author's order after the A7 work turned up what friends would actually
hit. **Scoring does not block the invite. The output friends judge does.**
Local ranking is keyword order until Q53 (R98, R99), which friends are told
plainly. Keyword order is the half R67 found discriminates about 8× better, so
it is not a random board.

**Before the invite, in order:**

1. **Q59: the bullet budget for sparse resumes.** Three jobs and one project
   get 2 bullets per job and about three-quarters of a page, and one project
   costs every job a bullet. This is what every friend's PDF looks like.
   Also check where the projects and skills went missing (Q59 names the
   master `.tex` check).
2. **Q55: remote postings bypass the country whitelist.** It must carry three
   states (known in, known out, unknown), not flip a default.
3. **Q54's label: a job below the threshold is shown as "Not scored".** Store
   the score with a below-the-bar state.
4. **Q58's copy: what changes between postings without a key.** It lives in
   A7's key step.
   - *Decided 2026-09-23:* the rest of A7 that is cheap and not about
     scoring rides with it:
     - the free-tier data-use sentence, which decision 4 relies on;
     - `localStorage` for the key, without which every visit re-pastes it.

     The test-this-key call and the step-by-step page wait. R101 already
     checks a key's form at paste time, and Q61's numbers are now known
     rather than guessed.
5. **A8:** the event log and the success criterion.
6. **A9:** Sentry.
7. **A10:** concurrency, reaper and machine size. Q49's stale-run sweep is
   part of it.
8. **A11:** resume pre-flight on the friends' real resumes. After Q59, so it
   reads the budget that will ship.
9. **A11b: a clean clone runs green.** *Confirmed 2026-09-23, kept before A12
   because A12 depends on it.* `docker build --target verify` runs the suite
   from a clone, and the 14 `yash_pathak` errors would fail it.
10. **A12:** deploy, acceptance, invite.

**After the invite:**
- **Q53, the null set.** R99's cheap window failed its held-out check. Friends'
  applied / rejected marks become the labels its blind comparison needs.
- **A7b, a second free provider (Q60).** Flash is 20 requests a day (Q61),
  which is 3–6 tailored resumes per friend per day.
- **Q61: quota-aware embedding backoff and token pacing.** Before any Gemini
  embedding measurement is trusted again, and before Q53 runs on Gemini.
- *Decided 2026-09-23:* **A9b** ("0 discovered" says why), with a trigger. A0
  found no board blocking, and Q56 put scrape coverage at 15 of 20 from home,
  so it is diagnostic rather than blocking. Pull it forward if the first
  friend sees an empty board.
- The rest of A7: the test-this-key call and the illustrated AI Studio page.

### A0. Fly egress probe — before anything else (½ day) — **DONE 2026-09-22**

If Greenhouse, Lever or Ashby block datacenter IPs, hosting on Fly is in
question and everything built before finding out was built on sand.

Deploy a throwaway machine, hit a sample of the 113 slugs in
`tools/assets/ats_companies.json`, and **compare status codes against the same
run from a home connection as a control**. Q32 is why this needs status codes
rather than counts: `ats_search._fetch` returns `None` for 403, 429, 404 and a
Cloudflare HTML-200 alike, every reader turns that into `[]`, and Sentry sees no
exception — so from a datacenter IP a block is indistinguishable from an empty
board.

#### Result: Fly is not blocked. Proceed.

`scripts/egress_probe.py`, both legs, all 98 slugs the seed file actually
carries (the 113 above counted the `_comment` key and the duplicate
SmartRecruiters case variants — see the findings below).

| | home control | Fly `ord` |
|---|---|---|
| taken (UTC) | 2026-09-22 02:26 | 2026-09-22 03:28 |
| origin | residential | Fly datacenter |
| 200 | 95 | 95 |
| 404 | 3 | 3 |
| blocked / challenged / unreachable | **0** | **0** |
| roles returned | 11,965 | 11,936 |
| served via Cloudflare | 35 | 35 |

**98 of 98 slugs returned the identical verdict from both origins**, from two
genuinely distinct public IPs, and no slug was probed on only one leg. The
three 404s are the same three on both legs — `greenhouse:kickstarter`,
`greenhouse:postman`, `workable:j` — which is companies that left the ATS, not
an origin decision.

**The subtle failure was checked for and cleared.** A block can hide behind a
200 that returns fewer roles, which is the same "counts are not enough"
reasoning pointed the other way. 16 slugs differ in role count, total delta
−29 of 11,965 (0.24%), and the differences run **both directions**
(`coinbase` returned one more from Fly). That is an hour of live board churn.
A datacenter filter does not return 99.76% of a board.

**Also measured, and this is the risk map for later:** 35 of 98 slugs are
served through Cloudflare — all 23 Ashby, all 6 SmartRecruiters, all 6
Workable. Greenhouse (57, 58% of the list) and Lever (6) are not. The
Cloudflare count is *identical* on both legs, so the edge did not treat the
datacenter differently. If this ever changes it will change on those three
boards, and Greenhouse — the majority of discovery — degrades last.

#### Two caveats. Neither is a reason to stop; both are reasons not to over-read this.

1. **One low-volume snapshot, an hour wide.** 98 requests at 0.3s spacing from
   one Fly machine in `ord`, once. These boards rate-limit by volume and
   several sit behind an edge that scores reputation over time, so five friends
   running discovery concurrently is a different traffic shape from this probe
   and could be answered differently. It says the IP range is not blocklisted;
   it does not say the app's steady-state volume is welcome. The plan already
   re-runs the probe after deploy (Verification step 6) — that is the run
   whose volume resembles production.

2. **JD scraping was not probed at all.** This measured the five ATS *listing
   APIs*. `enrichment_agent._real_scrape` fetches each posting's page through a
   different path with different anti-bot exposure, and it is the stage that
   would fail as an empty board with scored rows on it (R61's shape). A green
   listing probe says nothing about it. Fold this into the post-deploy re-run
   rather than a second probe now: `--input` replay means the scrape path can
   be exercised against the hosted instance directly.

**Raw records are deliberately not committed.** The home leg's record contains
the author's residential public IP and this repository is public; committing
one leg and not the other would leave a comparison nobody can check, so
neither is committed (`.gitignore` carries `probe-*.json` as a pattern, per the
ignore-by-pattern rule). The numbers above are the record. Re-derive with
`python scripts/egress_probe.py --label <leg> --out probe-<leg>.json`.

#### Findings logged, not fixed here

- `tools/assets/ats_companies.json` carries `BoschGroup`/`boschgroup`,
  `Experian`/`experian` and `SmartRecruiters`/`smartrecruiters` — six slugs,
  three companies, each fetched twice per run.
- `workable:j` is a one-letter slug that 404s from both origins, and
  `harvest_slugs`' `([a-z0-9_-]+)` pattern will match a single character.
- The "113 slugs" in this item was never 113.

**The half of this item that has not shipped** — carrying per-status-code
counts into the run result so "0 discovered" can say why — is **A9b** below.
It was split out deliberately rather than done here: see that item for why
doing it in A0 would have committed the bug it exists to fix.

### A1. Fix the facade parity test — first, because everything leans on it (1 hr) — **DONE 2026-09-22**

`tests/test_ui_contract.py:173-175` is `assertTrue((api_names & facade) <=
facade)`. An intersection with `facade` is a subset of `facade` for **every
possible input** — the assertion is a tautology, and `only_api` is computed for
the failure message and never asserted on. The one test standing between
Streamlit and React diverging asserts nothing, and `user_id` is about to enter
every facade signature. Five lines.

**It was worse than a tautology, and it took more than five lines.** Two
separate defects:

1. The failure message named a condition the mechanism *cannot* detect — "the
   API calls something that is not on the facade", when intersecting *with* the
   facade can only ever yield facade members. There was no non-tautological
   reading of the assertion to recover; it had to be replaced, not repaired.
2. It compared AST name scans, so `Optional` and `Path` registered as facade
   divergence: both files name them from `typing`/`pathlib`, and both collide
   with the orchestrator's module namespace. **16 of the 43 names `dir(orch)`
   reports are incidental imports**, not facade — including `dataclass`,
   `datetime` and the four agent classes.

Both views reach the pipeline through a single `from agents.orchestrator import
(...)`, which the sibling test already pins as the only way in, so the import
list *is* each view's visible surface. Comparing lists instead of name scans
drops the noise to zero and shows the real divergence: the API imports
`board_job` and `outputs_root`; Streamlit does not. Both are correct — HTTP
addresses resources by URL and an in-process view does not — so they sit in
`HTTP_ONLY` with the reason, a third fails the build, and a companion assertion
fails when an entry goes stale.

Verified by mutation rather than by passing: importing `recent_runs` into
`api/main.py` fails, dropping `board_job` fails, and the old assertion returns
`True` for `{'anything','at','all'}` against `{'board_jobs'}`.

### A2. Reproduce the two-user bugs (½ day, nothing ships) — **DONE 2026-09-21**

Add a second fixture user built from one of the anonymized stranger resumes in
`tests/fixtures/` — **not** derived from Priya, because a fixture derived from
one you have is a fixture that agrees with you. The two profiles must differ in
the fields `gate_fingerprint` hashes (`job_filter.py:775-800`) or the storm test
cannot fire.

`rohan_deshmukh`, imported through the real path from
`resume_two_degrees_non_us.txt`. Chosen over `glued_runs`, which carries
"low-latency" and "High-Performance" — the exact words three property tests
walk every master for. The pair differ on `years_experience`: Priya answers 6,
Rohan's is `None`, which is what a freshly imported profile actually holds.

Delivered as `tests/test_two_users.py`, six assertions, every one
`unittest.expectedFailure` with the stage named that should flip it. An
expected failure that passes is an unexpected success and fails
`wasSuccessful()`, so landing A3 produces a red build telling whoever did it to
drop the decorator — rather than a green one nobody re-reads.

1. `refresh_board_gate(A)`, `(B)`, `(A)` → the third call re-judges **zero**
   rows. Today it re-judges all of them.
2. A scores 8 jobs ~40, B scores 8 ~90 → A's `score_bands()` does not move.
3. Two runs on the same date land in **two directories** and A's `state.json`
   is intact. *This item used to say `previous_runs()` returns two entries,
   which no partitioned world can satisfy* — once A3 scopes `outputs_root`,
   A's listing holds A's one run and B's holds B's, and neither is ever two.
   The durable claim is that the directories differ; the count was a symptom
   of their being one.
4. The run listings hand a caller no run of anyone else's. *This item used to
   name `output_dir` and `error` on `GET /api/runs`, and both halves were
   wrong.* Those are `runs.db` columns surfaced by `RunRegistry.recent()`, and
   **no route serves `recent()`** — its facade wrapper `recent_runs` has no
   caller in either UI, and A1's contract test fails the build if
   `api/main.py` imports it. `GET /api/runs` is `previous_runs`, reading
   `outputs/` off disk as `{date, path, jobs, resumes}`. So the assertions are
   on what the two listings do carry: the run's `profile` on `GET /api/run`,
   and its directory on `GET /api/runs`. And **"as B" cannot be written yet** —
   there is no session, so there is no B; that is the finding, not a gap in
   the test.

**Found while doing it, fixed before it shipped (Q34).** The fixture has two
roles at one employer, and a component ID was `exp_{slug(company)}` — so they
collided, and seven consumers key a dict by that ID. `test_latex_round_trip`
caught it the moment the resume landed in `data/master_resumes/`; it had
asserted the right thing for six weeks against masters that happened not to
have a repeat. Fixed in its own commit first, because A2 could not otherwise
be committed green.

### A3. The scope seam and the threading — one commit (3–4 days) — **DONE 2026-09-22**

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

#### Exit criteria

1. Every `@unittest.expectedFailure` in `tests/test_two_users.py` that names A3
   is gone, and its test passes. The suite tells you which: an expected failure
   that passes is an unexpected success and fails `wasSuccessful()`, so A3 is
   not done while the build is red for that reason.

2. **The four non-discriminating tests pass the mutation check.** A2 measured
   which of its six assertions fail because a *second person* exists, by
   setting `USER_B = USER_A` and changing nothing else. Two did — the gate
   storm and the overwritten `state.json`. The other four were red under the
   mutation too, because the facade they call has no user to distinguish:
   `score_bands()` cannot tell "B's scores moved A's bands" from "A scored
   eight more jobs", `outputs_root(...) / date` already collapsed one person's
   two runs in a day, and the two API assertions have no caller identity to be
   the wrong one.

   After A3 those four must be **red under the mutation and green without
   it** — that is the difference between a partition and a coincidence. A run
   where all six pass either way has not proved scoping; it has proved that
   two calls with the same argument agree, which they did before A3 as well.

   The API pair (A2.4) is the exception and stays red under the mutation until
   A5/A6: A3 gives the facade a user to scope to, but the route has nothing to
   hand it until the session cookie exists. Recheck them there, not here.

3. `python -m agents.orchestrator --profile priya_raghunathan --max-jobs 5
   --mock` still passes unscoped, and `baseline.py verify --all` is unmoved —
   the checkout fork must not move, which is the hard constraint this stage
   was designed around.

#### What shipped, and where it departed from the above (R90)

All three exit criteria hold, measured rather than asserted:

1. The four A3 decorators in `test_two_users.py` are gone and their tests
   pass. The A2.4 pair stays an expected failure for A5/A6.
2. Mutation check, `USER_B = USER_A`: A2.2 and A2.3a go **red**, and are green
   without it. A2.1 and A2.3b are green both ways, which they already were as
   of A2.
3. The `--mock` Priya run writes byte-identical `.tex`, and its state files
   differ only in timestamps. **`baseline.py verify --all` could not be run
   here**: the baselines exist only on the author's machine, and it reports
   MISSING before and after. **Run it there before relying on this item.**

**A committed instrument for the hard constraint.** `scripts/path_snapshot.py
verify` asks every store where it lives and compares the answer with
`baselines/paths.unscoped.json`, which was taken from the pre-A3 code. It
checks from the repo root, from a foreign cwd (which reproduced Q31 before
the fix and holds it closed after), and it checks that a scoped user resolves
nothing outside their home. **A5 and every later stage that touches a path
re-run this rather than writing their own.**

Departures, each for a reason stated in R90:

- `user_path(*parts, user_id)`, **keyword-only**, not `user_path(user_id,
  *parts)`. The positional form would have quietly turned every old
  `user_path("data", ...)` call into a user called `data`.
- **Added to the pairs table:** `load_profile` + `available_profiles` + the
  `init_profile` writers (`resume_dir`, `profiles_dir` and about ten
  functions), and `master_resume_path`, now resolved once by
  `paths.stored_path`.
- **The learned ATS list is per user** (decided 2026-09-22).
- **Three more cwd-relative defaults:** `LLMCache`, `TextEmbeddingCache` and
  `generate_resumes`. None was on the list of four; the closing test found
  the first two.
- **The closing test's rule is wider than the pattern above**, which would
  have missed `PROFILES` and `LEARNED_FILE`. It lives in
  `tests/test_scope_seam.py`, with the known-bad sources it proves itself
  against.
- `test_hosted_mode_has_no_unscoped_call_site`, an expected failure that
  **A5 is responsible for flipping.** It counts the `None` call sites in
  `api/main.py` statically, and at runtime under `JOBSCOUT_MODE=hosted`
  (26 at A3, 28 after A4 and R93; the test is the count, not this line).
  `_as_the_api_serves` in `test_two_users.py` is the one line A5 changes there.

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

#### What shipped, and where it departed from the above (R92)

The model, the migration table and the three-valued verdict landed as
written, with these departures, each for a reason recorded in R92 or its Q:

- **Two gates, not one** (Q39). `_apply_body_gate` does not store
  `gate_reason`; the board's `refresh_board_gate` does. Both now call
  `job_filter.judge_body`. The plan's `demands_basis` is
  `posting_facts.demands_facet`, and `_gate_source` hashes that file too.
- **The verdict is a column**, `gate_verdict`, beside `gate_reason`, with a
  one-time backfill from `gate_reason` when the column is added.
- **Clearance `false` → unknown** and **`us_person=yes` satisfies a
  no-sponsorship demand**, and only that entailment — both decided
  2026-09-22.
- **The visa dropdown is gone** from both screens. `visa_status` stays in
  the schema, read by nothing. The wording, reviewed, lives in
  `init_profile.WORK_AUTHORIZATION_QUESTIONS`; question 1 names refugees and
  asylees, question 2's yes is "Yes, now or later" and its help opens "If
  you're on a work visa today, the answer is yes." A stored `unknown` is
  shown unanswered, never pre-selected as "Prefer not to say".
- **The React half reads defensively**, because `web/src/lib/` was never
  committed (Q41). Declare `gate_verdict`, `gate_reason` and `unconfirmed`
  in `api.ts` once it is.

Logged, not done: Q40 (the board judges discovery's text, not the scraped
JD), Q42 (undecidable jobs can take top-K; leaning: rank below confirmed),
Q43 (Streamlit preferences crash on unanswered years, found by A4's test).

**Run on the author's machine before relying on A4:** `baseline.py verify
--all`, the two `yash_pathak` corpus tests in `test_body_gate` and
`test_experience_profile` (a company dropped only for a clearance demand is
now undecidable — move the expectation), and `scripts/acceptance.py`, which
could not complete in the container (no `pdflatex`).

*Followed up 2026-09-22:* the third corpus test of this kind,
`test_eligibility_gate`'s Scale AI DevOps posting, failed on the author's
machine for exactly the clearance reason. It now asserts undecidable while
the question is unanswered and hidden once it is answered "no". The React
board did **not** re-judge, and worse, it was never judged at all. R93 wires
the re-judge into `PATCH /api/profile` and the start of every run. Q43 is
fixed. The `api.ts` types wait on Q41's push.

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

**Left for A5 by A3, and each one fails the build until it is done:**

- `tests/test_scope_seam.py::test_hosted_mode_has_no_unscoped_call_site` is
  an expected failure. Flip it by giving every one of `api/main.py`'s
  `None` call sites the session's caller. Local mode keeps `None` through the
  identity dependency, not as a literal. The runtime half's probe requests
  will need a session cookie.
- `tests/test_two_users.py::_as_the_api_serves` returns `None`. Its body
  becomes the caller's identity, and the A2.4 pair's decorators come off.
  Recheck that pair under the `USER_B = USER_A` mutation then, not before.
- `python scripts/path_snapshot.py verify` must still say `unmoved`.
  `data/accounts.db` is global by design, so it is not a user store and does
  not belong in the snapshot's table. Say so there when it lands.

#### What shipped, and where it departed from the above (R95)

All three items left by A3 are done, and all three were measured:

1. `test_hosted_mode_has_no_unscoped_call_site` passes. The static count went
   from 28 to 0. The runtime probe now signs in, and it asserts every facade
   call receives *that* caller, not just a non-`None` one.
2. `_as_the_api_serves(user)` returns `user`, and the A2.4 pair's decorators
   are gone. Under `USER_B = USER_A` both go red; without it both are green.
3. `path_snapshot.py verify` still says `unmoved`. `accounts.db` is noted
   there as global rather than listed.

Also as planned: `/api/health` lists the caller's own profiles. `api.ts`'s
fetch sites each report a 401. `App.tsx` gained the `'signin'` state, and it
renders nothing until the server has said which mode it is in.

Departures and additions, each recorded in R95:

- **Redeem, not only sign in.** `POST /api/account` claims an invite and
  signs in. `scripts/admin.py invite` shipped now rather than with A6,
  otherwise nobody could get in until A6. The other three subcommands stay
  with A6.
- **The Basic-auth gate is deleted** in the same change that proves the
  session gate. It is not kept alongside.
- **Local mode serves loopback only**, on top of decision 3's boot refusal.
  A deploy that loses `JOBSCOUT_MODE` refuses to boot on Fly, or else 403s
  and logs ERROR on every request from another machine, plus an ERROR at
  boot for a non-loopback `--host`.
- **Three 200s became 404s:** `POST /api/job/status` (a store behaviour
  change), `POST /api/board/gate` and `POST /api/run` for a profile the
  caller does not have.
- **`/users/` is ignored.**

Logged, not done: Q45 (a passphrase reset does not end sessions; ships with
A6's `reset-passphrase`), Q46 (no sign-in rate limit), Q47 (the API sends
absolute server paths) and Q48 (Streamlit serves every interface in local
mode, the twin of the loopback guard).

**Run on the author's machine before relying on A5:** `baseline.py verify
--all`, which reports MISSING here as it did at A3, and the 14 suite errors
that need `yash_pathak.json`, which is absent from this checkout and was
failing identically before A5.

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

#### What shipped, and where it departed from the above (R96)

As planned:

- `DELETE /api/account` removes the caller's account row and their whole
  `users/<id>/` tree, clears the cookie, and returns `account`, `files`,
  `bytes` and `areas`.
- `delete_user_data` is the only deletion path. `scripts/admin.py
  delete-user` calls it, and a test spies on the call to prove it.
- `test_no_byte_of_a_deleted_user_survives` is the walker test, and the walker
  lives in `tests/residue.py` for A7 to import.

The walker was mutation-checked. It goes red when the facade keeps the
account row, keeps the tree, or runs without `secure_delete`.

Departures and additions:

- **The walker found a real defect.** SQLite left the deleted email in
  `accounts.db`'s free pages. `secure_delete` is now on.
- **There are no event-log rows to delete yet.** A8 has not been built. Its
  table lives under `users/<id>/`, so the tree removal covers it, and the
  walker fails if it does not.
- **Refused while a run is live** (409). `delete-user --ignore-active-runs`
  handles a run that a crash left marked `running`, since the registry never
  clears one.
- **Reset is a re-invite of the same account.** The friend chooses the new
  passphrase through the existing redeem form, and the operator never knows
  it. This fixes Q45 with a session epoch covered by every MAC.
- **Q48 is fixed**: `.streamlit/config.toml` binds Streamlit to loopback.
- **Streamlit's view does not get delete.** `delete_user_data` is `HTTP_ONLY`
  in the UI contract, because Streamlit's user is the checkout and the facade
  refuses `None`.

**Run on the author's machine:** `baseline.py verify --all`. It reports
MISSING here, as it did at A3 and A5. The 14 suite errors that need
`yash_pathak.json` are unchanged.

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
*Read 2026-09-23 (Q61): flash 5 RPM / 20 RPD, flash-lite 15 / 500, embedding
100 RPM / 30K TPM / 1K RPD. Embeddings are token-bound, and the backoff does
not yet tell a minute limit from a day limit.*
**Action, unchanged:** find out whether the Gemini client backs off on a 429 or
fails the run, and add backoff if it does not. With one user this never came up.

*Answered 2026-09-23.*
- **Generation** retried once per model and then fell to the verbatim floor.
- **Embeddings** did not retry at all, and did not say why they failed.
  - The first side-by-side found this: 34 of 40 Gemini jobs unscored.
  - R97 adds classification, backoff and a per-run breaker for a spent daily
    cap.
  - The run report now names the failure kinds.
- **The import path** (`llm_backends.complete_json`) still has no backoff.
- **The side-by-side has not been re-run yet.** Before it is:
  - Q51: potion's scale clips a senior profile, and may be ranking Priya by
    keyword count alone.
  - Q52: a key pasted in the UI never reaches embeddings. On the hosted app
    every friend is scored with potion, key or not. So what the comparison
    decides is whether that should change.

`test_the_api_key_never_lands_anywhere`: run the pipeline with a sentinel key
through the mock rung, then reuse A6's walker over the data home **plus a
captured log handler**. A runtime walk, not a grep of the source — so it fails
when a sixth call site starts logging the config it resolved.

### A7b. More than one free provider (≈1 day, scoped in Q60, not started) — **after the invite**

One free Gemini key per friend is one daily cap per friend, and testing
exhausts it. Groq and Cerebras free tiers serve OpenAI-compatible endpoints,
which the `openai` rung already speaks. Needed, in order:

1. **Route the key to its provider.** Today `GROQ_API_KEY` is accepted and
   sent to OpenAI's URL (Q60's defect).
2. **Put the provider in the LLM cache key and the per-resume record** (R45,
   R80, R79).
3. **Give `_chat_tailor` the one repair attempt `_gemini_tailor` has.**
4. **Extend A7's key page to a provider choice,** with a per-provider test
   call, R101's key check and a data-use sentence per provider, each read
   from that provider's terms at build time.
5. **Cross-provider fallback on quota,** second, because it is a new
   behaviour with its own attribution question.

Each provider that becomes supported is an explicit new row in
`acceptance.py`, not a quiet addition to the frozen list.

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

### A9b. "0 discovered" has to say why — `_fetch` to both UIs (1–1½ days)

The half of A0 that did not ship there. Numbered `b` rather than renumbering
A10–A12, which the Verification section references by number.

**Why it was not done inside A0.** The information dies at the bottom: every
board reader does `if not payload: return []`, so a 403, a 429, a challenge page
and a board with no open roles are already the same value before `search_ats`
sees them. Threading a status out of `_fetch` and stopping at `search_ats`' log
line would add a field that nothing above reads — instance seven of this
project's signature bug, committed inside the change that exists to fix the
observability gap. **Wire the consumer in the same change, or do not add it.**

**Why after A3, not before.** `start_run` and `run_status` both gain `user_id`
in A3. Plumbing a new field through those signatures first means writing them
twice.

#### What is wrong today, at the top of the stack

`web/src/components/steps/RunStep.tsx:331` renders, when discovery returns
nothing:

> **No jobs found.** Discovery returned nothing at all. Widen your target
> roles or the places you would work, on the Preferences screen.

If every board 403s the datacenter, that sentence **blames the user's
preferences for a network failure**, and sends them to edit a profile that was
never the problem. This is the invariant in product clothing: `discovered == 0`
is being rendered as a known fact ("nothing matched you") when it is an unknown
("we could not tell"). A filter that removes things must say how many — and a
discovery stage that reached nothing must say that it reached nothing.

#### The seam, counted rather than paired

The rule is *count them*, and the count here is higher than the pair in mind:

| # | Consumer | Change |
|---|---|---|
| 1 | `ats_search._fetch` (`:88`) | return the outcome alongside the payload, not `None` |
| 2–6 | `_greenhouse`, `_lever`, `_ashby`, `_workable`, `_smartrecruiters` | propagate instead of `return []` |
| 7 | `_hydrate` (`:515`) — the sixth `_fetch` call site, and the one that is not a board reader | propagate |
| 8 | `search_ats` (`:459`) | `if not found: failed += 1` merges unreachable with empty. Split them |
| 9 | `discovery_agent._search_ats` (`:172`) | carry the tally up |
| 10 | orchestrator discovery stage | put the tally in the run result |
| 11 | `RunRegistry` | **no migration needed** — `result` is already a TEXT column holding JSON (`run_registry.py:52`). `_ADDED_COLUMNS` does not have to be touched |
| 12 | `run_status` / the run result read by both UIs | expose it |
| 13 | `RunStep.tsx:331` | three-valued: reached-and-empty vs. could-not-reach vs. unknown |
| 14 | `app.py`'s run display | the same, or R70 fires again |

Fourteen, from a change that reads as "add a counter". Both UIs are on the
list on purpose: the author runs Streamlit and the friends get React, so this
is exactly the pair where a fix lands on one.

#### Constraints

- **Do not reuse the probe's verdict vocabulary by copying it.** `verdict()` in
  `scripts/egress_probe.py` already names ok / absent / blocked / challenged /
  unparseable / unreachable, and two copies of that table will drift. Move it
  to a module both import, and let `test_egress_probe.py`'s drift guard cover
  the URL table only.
- **`_fetch` must not gain module-level state.** A counter on the module is the
  `_EMBEDDING_CACHE` shape from A3: one per process, shared across users,
  silently wrong. Return it or pass a sink.
- **Unknown is never a value.** A run replayed with `--input`, or a run from
  before this field existed, has no tally — that is a third case, not a zero.
  `RunStep` must not read a missing tally as "all boards reachable".
- **No new status vocabulary in the UI copy.** A user does not need "429"; they
  need "we could not reach 12 of 14 job boards — this is us, not you."

#### Closing move

`test_no_reader_collapses_a_failure_into_an_empty_list` — AST-walk
`tools/search/`, fail on `return []` in a function that calls `_fetch`. Fails on
board six, which Stage C (Workday) adds.

And the test that would have caught the product defect: a mock where every
board 403s must produce a run result that a UI can distinguish from a mock where
every board returns `[]`. Today those two runs are byte-identical by the time
they reach either front end.

### A10. Concurrency, reaper, machine size (½ day)

- **One active run per user**, enforced server-side. Five simultaneous runs in
  one process under `--workers 1` is five threads scraping and embedding on one
  machine.
- **Stale-run reaper**: `state='running' AND updated_at < now - N min →
  'failed'`. One restart with in-flight threads leaves permanent spinners, and
  that is the first thing a friend sees. None exists today.
  **Weightier than a spinner — see Q49.** A stale row also parks both UIs'
  run screen (Run *and* Back disabled) and makes `DELETE /api/account` 409
  indefinitely. The reaper has to walk every `users/<id>/data/runs.db`, not
  one registry. It has to cover `queued` as well as `running`. And it wants a
  startup sweep, because with one process at boot every active row is dead.
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
R74's bullet-budget problem waiting to happen. *It happened: Q59, which is now
item 1 of the remaining order, ahead of this.* Cheap, and it is the last chance
to find a parser bug before it costs a first impression.

### A11b. A clean clone runs green (½ day) — before A12, because the image is a clone

**Found 2026-09-22 (Q35), verifying that A2's two commits were each green on
their own.** Checking the Q34 commit out into a fresh worktree and running the
suite gives **14 errors and 66 skips**. The author's working tree gives 1 skip
and no errors. The suite has never been run anywhere else.

This sits before A12 and not after because **`docker build --target verify`
runs the suite inside an image built from a clone** (Verification step 2). That
step would fail on 14 tests that have nothing to do with the container, and the
natural reading of a red container build is that the container is wrong.

#### What the 14 are

One line, once in each of three modules, all of them `load_profile
("yash_pathak", ...)` in `setUp`:

| Module | Line | Tests |
|---|---|---|
| `tests/test_page_is_a_page.py` | `:89` | 9 |
| `tests/test_renderers_agree.py` | `:79` | 4 |
| `tests/test_empty_resume_refused.py` | `:132` | 1 |

`user_profiles/*.json` is gitignored, so the file is absent on a clone and
`ProfileLoadError` propagates. All three modules **already** guard on the
master resume and skip cleanly without it; none guards on the profile. Two
paths, one walked, inside one `setUp`.

#### The goal

A clean clone runs green. A test that needs a file only the author has either
skips explicitly with a reason, or moves to a committed fixture.

The convention already exists — 37 of the 66 skips say `"... skipped on a clean
clone"` verbatim (`test_component_editor.py:26`,
`test_fabrication_guards.py:150`, `test_import_confirmation.py:252`). These 14
are where it was not applied, not a new policy.

**But do not reach for the skip first.** A skip on a clean clone is a test that
never runs in CI, and 66 of them is most of what the container build would be
checking — a green `--target verify` over 66 skips is R81's shape, a harness
reporting success on the cases it cannot reach. Where a committed fixture can
carry a test, moving it there is worth more than a clean skip.

That trade is **not mechanical**, which is why this is half a day and not an
hour: Priya has **0 projects against Yash's 13**, and most of
`test_page_is_a_page` is about the projects half of the bullet budget (R74) —
swapped to Priya it would pass while measuring nothing, which is worse than
skipping. `rohan_deshmukh` (4 projects, 3 experiences, committed at A2) is the
closer substitute. Decide per module.

**And the count is the thing to watch.** The bar is not "14 fixed" — it is a
clean clone going green, with the number of skips *falling*. Re-run the fresh
worktree afterwards rather than trusting the working tree, because the working
tree is the one machine where this was never visible.

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
   inside the container, 3 of 3. **A11b first:** the image is built from a
   clone, and a clone currently fails 14 tests that have nothing to do with
   the container (Q35).
3. Two-user acceptance: create a second account, run both under `--mock`,
   assert the A2 tests pass.
4. `DELETE /api/account` then the residue walker.
5. Deploy; `scripts/acceptance.py` against the instance on the `none` row.
6. Egress probe from Fly and from home, comparing status codes (this one runs
   first, at A0, and again after deploy).
   `python scripts/egress_probe.py --label <leg> --out probe-<leg>.json`, then
   `--compare probe-home.json probe-<leg>.json`; exit 1 means at least one slug
   answers the control and refuses the test leg. **A0's leg passed 98/98 and
   the post-deploy re-run is still required**, for the two reasons A0 records:
   it was one low-volume snapshot, and it never touched the JD scrape path,
   which is the one whose failure looks like an empty board with scored rows on
   it. Probe the scrape path in this run, not in A0's.

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
