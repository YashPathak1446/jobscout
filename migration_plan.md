# JobScout V3 — Migration Plan

This document is a **field-by-field taxonomy** of the user profile. It exists to
keep the team honest about which configuration options are user-authored,
which are derived from the user's resume, and which are internal heuristics
that should never be exposed.

The goal is to make the eventual UI migration mechanical: when we build the
profile-creation flow, each field already has a category that tells us exactly
where it belongs.

---

## Why this matters

The current `user_profiles/john_doe.json` is hand-tuned. It contains things like:

```json
"proj_autonomous_minecraft_agent": {
  "include_if_jd_contains": [
    "reinforcement learning", "rl agent", "pathfinding",
    "a* search", "autonomous agent", "gameplay ai",
    "state machine", "mineflayer", "stable baselines"
  ]
}
```

No real user is going to write that. But the system needs *something* in that
field for selection to work. The migration plan answers: where does that
"something" come from when there's no developer in the loop?

---

## Categories

Every profile field falls into exactly one of three buckets:

| Category | Meaning | Source |
|---|---|---|
| **DERIVED** | Computed from the master resume + heuristics | Resume parser, no UI |
| **USER-INPUT** | Asked of the user during onboarding | UI form |
| **INTERNAL** | Implementation detail, ships as a default constant | Code, not exposed |

A field is **DERIVED** only if a reasonable default can be produced from the
resume alone. A field is **USER-INPUT** only if the user genuinely needs to
make a choice the system can't infer. Everything else is **INTERNAL**.

---

## Field-by-field taxonomy

### `user_id`, `version`, `created`, `description`

| Field | Category | Notes |
|---|---|---|
| `user_id` | DERIVED | Auto-assigned UUID on signup |
| `version` | INTERNAL | Schema version, ships as a constant |
| `created` | DERIVED | Timestamp on signup |
| `description` | INTERNAL | Optional dev comment, drop in production |

### `personal_info`

| Field | Category | Notes |
|---|---|---|
| `name` | DERIVED | Parsed from resume header |
| `email` | DERIVED | Parsed from resume header |
| `phone` | DERIVED | Parsed from resume header |
| `linkedin` | DERIVED | Parsed from resume header |
| `github` | DERIVED | Parsed from resume header |
| `location` | USER-INPUT | Onboarding form: city/state |
| `visa_status` | USER-INPUT | Onboarding dropdown: Citizen / GC / OPT / H1B / etc. |
| `graduation_date` | DERIVED | Parsed from resume education section |

The resume header parser already extracts most of this. The user only confirms
`location` and `visa_status` — both have legal/eligibility implications the
system can't infer.

### `job_preferences`

| Field | Category | Notes |
|---|---|---|
| `target_roles` | USER-INPUT | Multi-select: SWE, ML Eng, Data Eng, Frontend, Backend, etc. |
| `experience_level` | DERIVED | Inferred from resume (years of experience, education status) |
| `seniority` | DERIVED | Inferred from `experience_level` |
| `graduation_eligibility` | DERIVED | From resume's graduation date |
| `employment_types` | USER-INPUT | Checkboxes: full-time, internship, contract |
| `exclude_keywords` | USER-INPUT | Checkboxes with sensible defaults: "Senior", "Staff", "Security clearance", "5+ years" |
| `locations.countries` | USER-INPUT | Multi-select with profile-default of resume location's country |
| `locations.cities` | USER-INPUT | Free text or multi-select of major hubs |
| `locations.remote_ok` | USER-INPUT | Toggle |
| `locations.exclude_countries` | USER-INPUT | Multi-select |
| `citizenship_restrictions` | DERIVED | From `visa_status` — auto-populates "US citizenship required", "security clearance" if user is non-citizen |
| `job_recency_hours` | INTERNAL | Default 168 (1 week) |
| `comments` | INTERNAL | Drop in production |

### `resume_preferences`

| Field | Category | Notes |
|---|---|---|
| `master_resume_path` | DERIVED | File the user uploaded |

#### `resume_preferences.experiences`

| Field | Category | Notes |
|---|---|---|
| `max_count` | INTERNAL | Default 3 (industry standard for new-grad resumes) |
| `typical_count` | INTERNAL | Default 3 |
| `min_count` | INTERNAL | Default 2 |
| `selection_strategy` | INTERNAL | Always "jd_dependent" |
| `always_include` | USER-INPUT | UI: each experience gets a "Always show this" toggle |
| `priority_order` | INTERNAL | Always "auto" with composite scoring |
| `conditional_inclusion` | DERIVED | **Auto-generated from each experience's tech stack and bullet keywords** |
| `rarely_include` | REMOVED | Deleted (R31). `component_importance` says this already |
| `never_include` | USER-INPUT | UI: each experience gets a "Never show this" toggle |
| `bullets_per_experience` | INTERNAL | Computed by `_allocate_with_importance()` |
| `comments` | INTERNAL | Drop in production |

#### `resume_preferences.projects`

| Field | Category | Notes |
|---|---|---|
| `max_count` | INTERNAL | Default 4 |
| `typical_count` | INTERNAL | Default 3 |
| `min_count` | INTERNAL | Default 2 |
| `selection_strategy` | INTERNAL | Always "jd_dependent" |
| `always_include` | USER-INPUT | UI: each project gets a "Always show this" toggle |
| `high_priority` | DERIVED | Inferred from high-importance projects |
| `conditional_inclusion` | DERIVED | **Auto-generated from each project's tech stack** |
| `never_include` | USER-INPUT | UI: each project gets a "Hide from resume" toggle |
| `bullets_per_project` | INTERNAL | Computed by `_allocate_with_importance()` |
| `comments` | INTERNAL | Drop in production |

#### `resume_preferences.formatting`

| Field | Category | Notes |
|---|---|---|
| `max_bullet_chars_experiences` | INTERNAL | Default 280 |
| `min_bullet_chars_experiences` | INTERNAL | Default 140 |
| `max_bullet_chars_projects` | INTERNAL | Default 140 |
| `min_bullet_chars_projects` | INTERNAL | Default 120 |
| `target_page_count` | USER-INPUT | Toggle: 1 page (default) vs 2 pages |
| `template` | USER-INPUT | Dropdown of LaTeX templates (eventually) |

#### `resume_preferences.component_importance`

| Field | Category | Notes |
|---|---|---|
| `experiences.*` | USER-INPUT | UI: per-experience radio buttons (high / medium / low) |
| `projects.*` | USER-INPUT | UI: per-project radio buttons (high / medium / low) |

This is the single most user-facing tuning knob. The UI shows the user a list
of their parsed components and asks: *"How important is this to your story?"*

### `agent_preferences`

| Field | Category | Notes |
|---|---|---|
| `discovery_sources` | INTERNAL | Default `["github_newgrad", "serper", "adzuna"]` — system decides where to search |
| `discovery_source_priority` | INTERNAL | Mirrors `discovery_sources` order |
| `scoring_threshold` | INTERNAL | Default 50 — internal calibration |
| `max_jobs_to_discover` | USER-INPUT | UI slider: how many jobs per run? Default 30 |
| `max_jobs_to_enrich` | INTERNAL | Mirrors `max_jobs_to_discover` |
| `max_jobs_to_generate` | USER-INPUT | UI: "How many resumes to generate per run?" Default 10 |
| `checkpoint_after_discovery` | INTERNAL | Default false |
| `checkpoint_after_enrichment` | INTERNAL | Default false |
| `checkpoint_after_scoring` | USER-INPUT | UI toggle: "Review jobs before generating resumes?" |

---

## Auto-derivation of conditional triggers

This is the largest derivation task. Today we hand-author triggers like:

```json
"proj_spotify_music_browser": {
  "include_if_jd_contains": [
    "angular", "typescript", "oauth", "rxjs",
    "angular components", "reactive forms", "observable",
    "spotify api", "music api"
  ]
}
```

The auto-derivation algorithm:

1. **Extract tech stack** from the project's `\emph{...}` heading in the LaTeX
   resume (e.g. `Angular, TypeScript, Node.js, Express, Spotify Web API`)
2. **Lowercase and split** on commas, keeping multi-word phrases intact
3. **Filter out generic terms** using the same `_GENERIC_TERMS` set the
   composite scorer uses (`api`, `frontend`, `backend`, `data`, etc.)
4. **Add the project name** if it's distinctive (e.g. "spotify", "minecraft")
5. **Optionally: extract distinctive keywords from bullets** using the same
   `TECH_KEYWORDS` matching the parser already does

The result for Spotify would be:
```python
["angular", "typescript", "node.js", "express", "spotify web api", "spotify"]
```

That's narrower than what we hand-authored, but still correct. The trigger
matching uses word boundaries + JD section normalization, so it's fine.

For experiences, the same approach applies but using bullet keywords instead
of an `\emph{...}` block. The bullet of "AI Ensured" mentions "radiology",
"QA system", "report classification" — those become the triggers.

---

## What the onboarding UI would actually look like

Based on this taxonomy, the onboarding flow has roughly **6 screens**:

### Screen 1: Resume upload
"Drop your resume here." Parse it. Confirm extracted name/email/links.

### Screen 2: Personal context
- Where are you based? (city, state, country)
- What's your work authorization?
- When did you graduate (or when will you)?

### Screen 3: Job preferences
- What roles are you targeting? (multi-select with smart defaults from resume)
- Locations? (multi-select cities, remote toggle, exclude countries)
- Are there roles you want to avoid? (preset checkboxes: Senior, Staff,
  Security clearance, etc., with a free-text fallback)

### Screen 4: Component importance
"Here are the experiences and projects we found in your resume. How
important is each one to your story?"
- Per-component radio: Strongest / Solid / Use only when relevant
- Per-component toggle: Always include / Hide from resumes

### Screen 5: Output preferences
- One page or two pages?
- How many jobs per run? (slider)
- Review jobs before generating resumes? (toggle)

### Screen 6: Review and confirm
Show the generated profile JSON in a read-only preview.

That's it. Six screens, ~20 form interactions total. Everything else (~80%
of the current JSON) is either DERIVED from the resume or shipped as
INTERNAL defaults.

---

## Migration tracker

When changing the system, every profile-touching change has to answer:

- Is this **DERIVED**? Then the resume parser produces it automatically.
- Is this **USER-INPUT**? Then the UI form needs a field for it.
- Is this **INTERNAL**? Then it lives in code as a default constant.

If a change adds a new profile field that's USER-INPUT, that's debt. Track
it in this doc until the UI catches up.

### Current debt (updated 2026-08-23)

These fields are USER-INPUT but currently hand-edited in JSON:

- [~] `component_importance.{experiences,projects}` — **now derived from
      resume order (R15)**, so the UI form became an override rather than a
      requirement. Top-2 high, next-4 medium; explicit profile values win.
- [ ] `experiences.always_include` / `never_include` — needs UI toggle
- [ ] `projects.always_include` / `never_include` — needs UI toggle
- [x] `job_preferences.exclude_keywords` — **done (R40)**, a multi-select on
      the preferences screen, seeded from the profile.
- [~] `job_preferences.locations.*` — **cities and `remote_ok` done (R40)**.
      The rest (countries, state priorities, relocation) are still JSON, but
      the form no longer destroys them — see R40 on the merge bug.
- [x] `target_roles` — **done (R40)**, a multi-select that keeps roles the
      option list has never heard of.
- [x] `job_preferences.seniority` — **done (R40)**, added once R34 made the
      gate read it. Was not on this list because nothing read the field when
      the list was written.

These fields are DERIVED but currently hand-edited:

- [x] `experiences.conditional_inclusion` — **done (R21)**, derived from the
      bullet keyword vocabulary, since experiences carry no tech stack.
- [x] `projects.conditional_inclusion` — **done (R21)**, derived from the tech
      stack plus bullet keywords. The algorithm below is implemented with
      three departures, each recorded in R21: document-frequency filtering
      (the generic-term set alone cannot know `python` is in 7 of 13 stacks),
      no component-name source (it yields `resume` and `computer`, which every
      JD contains), and compound-vs-part pruning (R14 counts per hit, so
      "oauth 2.0" plus "oauth" double-scores one technology).
      **Caveat:** shipping it did not measurably close the gap to a hand-tuned
      profile — see R21 for what the measurement could and could not show.
- [x] `experiences.rarely_include` — **removed (R31)** rather than derived. It
      was computed on every call and read by nothing; `component_importance`
      expresses the same idea and R15 derives it.
      Note the current keys `exp_outlier` and `exp_tutor` do not resolve to
      real component IDs, so these rules have never fired.
- [x] `personal_info.{name,email,phone,linkedin,github,graduation_date}` —
      **done (R16)**, plus school, degree and graduation term. Derived at
      profile-creation time by `scripts/init_profile.py`.

These fields are INTERNAL but exposed in profile (cleanup opportunity):

- [ ] `experiences.{max,min,typical}_count` — should be code constants
- [ ] `projects.{max,min,typical}_count` — should be code constants
- [ ] `formatting.*_chars_*` — should be code constants
- [ ] `agent_preferences.discovery_sources` — system should decide
- [ ] `agent_preferences.scoring_threshold` — internal heuristic

---

## Privacy and dev-vs-public profiles

**Superseded 2026-08-21. The section below describes an arrangement that was
considered and rejected; it is kept for the reasoning, not as instructions.**

What is actually true:
- The real profile is `user_profiles/<name>.json` and the real resume
  `data/master_resumes/<name>.tex`. Both gitignored.
- `user_profiles/template.json` is the committed starting point, and
  `scripts/init_profile.py` fills it from a resume.
- **No synthetic example profile exists, by decision (R1).** The maintenance
  cost was judged higher than the benefit for a single-contributor repo.
- The git history purge this section anticipated has happened: personal data
  and generated artefacts were removed from all history with `git
  filter-repo`, and the phone number and email that were hardcoded in
  pre-v3 source were redacted (R12 covers the related tracking bug).

The original plan follows.

The dev profile (real name, real resume, real preferences) lives at:
- `user_profiles/john_doe.json` (gitignored)
- `data/master_resumes/john_doe.tex` (gitignored)

A synthetic example profile lives at:
- `user_profiles/john_doe.example.json` (committed)
- `data/master_resumes/john_doe.example.tex` (committed)

The example profile uses the placeholder name "John Doe" and a fictional
resume that exercises the same code paths. This way the repo is publishable
without exposing personal information, and contributors can run the pipeline
end-to-end against the example data.

---

## Open questions

1. **Can we infer importance tiers from resume order?** Most people put their
   strongest project first. Default to high → medium → low based on order,
   then let the user adjust.
2. **Should `target_roles` be multi-select with limits, or free-form?**
   Free-form is more flexible but harder to filter on. Multi-select with a
   curated list is more constrained but more reliable.
3. **For multi-resume users (different resumes per role type), how do we
   handle profile-per-resume vs profile-with-multiple-resumes?** Defer to
   Phase 5 (multi-user product).