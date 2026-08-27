# JobScout — what this is

**The problem.** People hand-tailor their resume against job descriptions with
a chatbot, one posting at a time, over and over. JobScout does it for them:
they give it a resume and a profile, it discovers matching jobs and writes a
tailored resume per posting.

**It works.** This tool ran its author's job search — discovery, matching,
tailoring — and he got hired. That is the proof, not a hypothesis.

**Who it is for:** tech job seekers, **any level, any location**. It began as a
new-grad tool for one person; that constraint is gone and the code should not
assume it.

**Not other fields, yet.** Three specific blockers, not squeamishness:
Greenhouse/Ashby/Lever skew heavily to tech; the LaTeX template is a one-page
tech resume with a projects section; and Q17's vocabulary-over-role-type
problem gets worse when "analyst" means five different jobs. Expanding means
solving those first.

**Where it is going:** a hosted, paid web app. The local CLI stays for
developers. Spend ceiling is **$10/month** until there is revenue (OOS5).

**Not building:** a public job board. It was tried and dropped on 2026-08-26 —
it assumed discovery was shared across users, and once a profile drives *what
gets discovered* rather than only what gets ranked, there is no shared half
(R66).

---

## Working here

- `known_questions.md` is the decision log and the planning substrate. Every
  question and every resolution lives there, numbered. **Read the relevant
  entry before changing what it describes** — and check it against the code,
  because entries have gone stale while the code moved (Q2 claimed unbuilt work
  that had shipped two days earlier).
- Decisions are recorded as `R<n>`, open questions as `Q<n>`, one commit each.
- `python -m unittest discover -s tests -q` is the suite.
  `python scripts/baseline.py verify --all` checks the frozen measurement
  baselines. Both must pass before a commit.
- `app.py` is a view layer and imports only `agents.orchestrator` and
  `scripts.init_profile`. `tests/test_ui_contract.py` fails the build otherwise.

## The recurring bug in this codebase

Fields and flags that are **computed and never read**. It has been found five
times: `rarely_include` (R31), `scraped_successfully` (R61) — which let the
pipeline invent job descriptions and score them — the whole selection
breakdown (R57), and `graduation_eligibility` / `experience_level` (R66).

When adding a field, wire the consumer in the same change, or do not add it.

## The other recurring bug: two paths, one walked

A fix lands on the path the author uses and not on the twin. Found five times,
twice in the same pair of modules: the escape table (R69) and the experience
field order (R70) were both fixed in one renderer and left in the other.

The author's resume is a `.tex`, so he never walks the PDF/DOCX import path.
He reads generated resumes as PDFs, so he never parses one back. Both bugs
lived exclusively where he does not go, and neither was findable by care on
the path he does — `test_tex_renderer.py` asserted the correct behaviour the
whole time, for its own module.

So: **a test that checks one path against itself proves nothing about the
other.** Walk both and compare them. The known forks are `.tex` upload vs.
PDF/DOCX import, Gemini vs. `none` vs. `ollama`, LaTeX installed vs. not, and
cached vs. cold. Each is a branch where one machine takes the same side every
time.

## `yash_pathak.json` is the least representative fixture in this repo

It predates every question the wizard has since changed, so it carries fields
no newly-built profile has — and it therefore **satisfies gates that a new
profile cannot**. Four times now:

- R70/R72's shape: the template presumed a new grad; his profile did not
- the seniority literal (R68): fixed in the wizard, not in what it starts from
- `us_citizen: true`: never seen, because his says what he is
- the preferences Save button, gated on `seniority` — populated in his profile
  from before R68, empty in every profile built since, so the button was dead
  for every new user and enabled for him

That last one is the worst of them in product terms. **A stranger does not
file a bug report; they close the tab.**

**And a fixture you wrote is a fixture that agrees with you (R77).** Priya was
invented to test the importer, so she can only contain problems somebody
thought of. One run of the pattern reader over a real third resume from
outside the project found four defects at once — a `Research/Projects` heading
that matched nothing, a `Publications` section filed as project bullets, two
degrees merged into one wrong record, and `\bmaster\b` never matching
"Masters". Keep at least one fixture nobody here authored.

So: **build against Priya, not against yourself.** `priya_raghunathan` — six
years, Boston, Staff Engineer, imported from a PDF this repo did not produce —
is the default fixture for anything touching profile shape, gates, defaults or
onboarding. `yash_pathak` is a **legacy-migration test case**, which is what it
actually is: the shape a profile has when it was built before the current
questions existed. Both are worth testing. Only one of them is what a new user
gets.

## Ignore by pattern, never by filename

`.gitignore` named `data/jobs.db`. `data/runs.db` arrived four months later
(R51) and nobody added a second line, so a live store holding real run history
was committed while its twin was ignored. The same rule had already been
written for `data/master_resumes/*.tex` and missed every PDF and Word resume a
user uploads (R38 added that path).

**Any directory the app writes to gets a pattern, not a list of names.** A new
file format or a second store is exactly the change nobody remembers to
mirror, and the cost lands in a published commit rather than in a test.

## The invariant: unknown is never a value

**Nothing may render or score "not yet known" as though it were known.** Every
field with a "not yet" state needs a third case — known, absent, and unknown —
and the code has to carry all three to the place that displays or ranks it.

Five instances, and the fourth is what makes it a rule rather than a run of bad
luck:

- `years_required: None` read as "no experience required" (R64)
- country parse failures read as a country that did not match (R55)
- `location_score == 0` meant both "a state you did not name" and "state
  unknown", so three postings listed only as "United States" were excluded as
  relocation (R69)
- the React board rendered every job as **"Not scored"** for the beat before
  the score bands arrived, telling the reader analysis had skipped their whole
  list — a claim, where a placeholder was wanted

- the bullet budget spent half a page on the projects section a resume did
  not have, so three jobs shared six bullets and the bottom third was blank
  (R74). Not a display this time — an *allocation*. The rule reaches further
  than rendering: any budget, quota or average split across sections has to
  ask whether a section is empty or absent

The fourth appeared within hours of a frontend existing, which is the point:
**anything that arrives asynchronously has an unknown state by construction.**
Every screen in the wizard displays data that loads after it mounts, so this
will keep firing. A loading state is not an empty state, an empty state is not
a zero, and a zero is not a "no".

**The sharpest form of it, found by R75:** the preferences Save button was
gated on the levels a profile's years imply, and an unanswered years field
implies none — so the fix for R72's dead button rebuilt the same dead button
one field over, on both UIs, and the test could not see it because it walked
`range(0, 41)` and never `None`. **Any test that walks a range is a test that
has not walked the absence.**

Related and older: **a filter that removes things must say how many.** The
board hides jobs the gates reject (R62) and states the count under the current
filters — 59 of 136, and 14 of 19 when narrowed to one company. Silent
subtraction is the same failure wearing product clothes.
