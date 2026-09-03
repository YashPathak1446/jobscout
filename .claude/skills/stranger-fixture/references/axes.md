# The axes a stranger has to differ on

## Why an axis table and not "use a different resume"

`yash_pathak.json` is the least representative fixture in this repo. It predates
every question the wizard has since changed, so it carries fields no
newly-built profile has — and it therefore **satisfies gates a new profile
cannot**. Four times:

- the template presumed a new grad; his profile did not (R70/R72)
- the seniority literal (R68) was fixed in the wizard, not in what it starts from
- `us_citizen: true` was never seen as a problem, because his profile says what
  he is
- the preferences Save button was gated on `seniority` — populated in his profile
  from before R68, empty in every profile built since. **Dead for every new user
  and enabled for him.**

That last one is the worst in product terms. A stranger does not file a bug
report; they close the tab.

So the fixture is not "someone else's resume". It is a profile that **differs on
every axis that touches parsing, scoring, gating or defaults**.

## The table

Measured from `user_profiles/yash_pathak.json` and
`user_profiles/priya_raghunathan.json`.

| axis | `yash_pathak` | `priya_raghunathan` |
|---|---|---|
| location | San Francisco, California | Boston, Massachusetts |
| `visa_status` | US Citizen | H1B |
| `us_citizen` | `true` | `false` |
| `holds_security_clearance` | **absent** | `false` |
| `years_experience` | **absent** | `6` |
| `seniority` | `["new grad", "entry level", "junior"]` | `[]` |
| `graduation_date` | `June 2025` | `""` |
| `degree` | `Bachelor of Science in Computer Science` | `""` |
| `states_priority` | `["California", "New York"]` | `[]` |
| `cities` | 6 California/NY/Seattle cities | `["Boston", "Remote"]` |
| master resume | `.tex`, hand-written | `.pdf`, imported |

Two rows carry most of the weight:

- **`seniority: []` with `years_experience: 6`** is exactly the shape that
  produced R75's dead Save button. Any gate derived from levels has to survive
  it.
- **`.pdf`, imported** is the fork the author never walks. His resume is a
  `.tex`, so he never sees the PDF/DOCX import path — where the escape table
  (R69) and the experience field order (R70) were both left unfixed after being
  fixed in the other renderer.

## Priya's limits, stated

`priya-raghunathan.json` in this directory is a **verbatim copy** of the profile
as it stood, kept here so the axis table can be checked against something rather
than remembered.

**It does not make her portable.** Her `master_resume_path` points at
`data/master_resumes/priya_raghunathan.tex`, which is gitignored, as is the
profile itself. On any machine but the author's,
`python scripts/acceptance.py --fixture priya` fails with *"profile
'priya_raghunathan' does not exist and this script does not own it"*
([acceptance.py:368](scripts/acceptance.py#L368)). That gap is known, is not on
the frozen list, and is not closed by this file.

**She was invented here, so she agrees with us** (R77). She can only contain
problems somebody thought of. The two fixtures in `tests/fixtures/` —
`resume_two_degrees_non_us.txt` and `resume_glued_runs_six_roles.txt` — are real
strangers' resumes as anonymized extracted text, identity replaced and every
structural artifact kept byte for byte. **Do not copy them here and do not tidy
them.** A fixture cleaned up is a fixture that has stopped testing anything, and
a fixture that is a paraphrase agrees with you too.

## Seeding a fresh fixture

If a pass finds nothing, the fixture is probably too close. To build a new one:

1. Start from a resume this repo did not produce, in a format that is not
   `.tex`. Import it through the real path — the wizard's upload, or
   `scripts/init_profile.py`, which is the same importer both UIs call.
2. Check the new profile against the table above. **Every row should differ from
   `yash_pathak`**, and ideally several should differ from Priya too — she is
   one point in the space, not the space.
3. Prefer values that are *absent* or *unknown* over values that are merely
   different. Unknown is where this codebase breaks: `years_required: None`
   (R64), country parse failures (R55), `location_score == 0` meaning both "a
   state you did not name" and "state unknown" (R69).
4. Do not hand-author the profile JSON. Keyword vocabulary, component importance
   and JD triggers are *derived* from the resume by
   `tools/profile/derivation.py`. A hand-written profile skips the derivation
   the product actually runs.

**Do not source a new stranger's real resume for this.** `plan.md` rule 1 turned
that method off deliberately — it finds bugs forever, and stopping is a decision
rather than an oversight. This skill re-walks fixtures that are already
committed.
