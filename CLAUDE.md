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

**A sixth, and it was committed inside the change that adds a setting (R80).**
`resolve_backend` was written to hold the precedence chain for the LLM rung
and its first draft never read `LLM_BACKEND` — the constant whose only purpose
is to be read there. Reasoning did not catch it; five tests that pin a rung by
setting that constant fell through to detection and started making real
network calls, and the suite went from 66 seconds to 197. **A config value you
just made overridable is a config value with a new way to go unread.**

## A cache key encodes how much variation lives inside a category

Three times, the same fix one level down, and each was correct when written:

- **R11** — the embedding cache needed the *model* in its key
- **R45** — the LLM cache needed the *rung*: three llama3.1 replies were
  served to a run pinned to Gemini and read as a Gemini regression
- **R80** — the LLM cache needed the *model too*, because `llama3.1:8b` and
  `qwen2.5:7b` are both the `ollama` rung and shared one key

Nothing edited those decisions and none of them was wrong. What changed was
**the meaning of the category underneath them**. "Provider" meant Gemini's
fixed fallback chain, where flash-lite answering for flash is the entire
point; R37 made it mean "whatever you happened to pull", and the same key
became a bug without a character of it changing.

The tell was a comment: *"the rung, not the model id, so a fallback within a
provider still hits."* A correct sentence that stopped being correct while
nobody was editing it — the same shape as R55's comment crediting a guard that
never fired.

So when a rung, a provider or a source is added: **ask what the key assumes is
interchangeable, and whether that is still true.** A key is a claim about which
differences do not matter, and widening a category is exactly the change that
falsifies one silently — there is no error, only a table that agrees with
itself.

## The other recurring bug: two paths, one walked

A fix lands on the path the author uses and not on the twin. Found five times,
twice in the same pair of modules: the escape table (R69) and the experience
field order (R70) were both fixed in one renderer and left in the other.

The author's resume is a `.tex`, so he never walks the PDF/DOCX import path.
He reads generated resumes as PDFs, so he never parses one back. Both bugs
lived exclusively where he does not go, and neither was findable by care on
the path he does — `test_tex_renderer.py` asserted the correct behaviour the
whole time, for its own module.

**And the rule is not "check the other one" — it is *count them* (R80).** The
plan for the backend seam predicted two consumers. The code had four:
`GenerationAgent._resolve_backend`, `complete_json`, `backend_status`, and a
caption in `app.py` telling users to edit `config.py`. The count is reliably
higher than the pair in mind, which is why the closing move is a test that
fails on a fifth — `test_nothing_outside_config_reads_the_constant` walks the
syntax tree, not the text, because prose that *explains* the seam is not a
violation of it.

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

**And a fixture you wrote is a fixture that agrees with you (R77, R78).** Priya
was invented to test the importer, so she can only contain problems somebody
thought of. Two real resumes from outside the project have now found eight
defects between them — a `Research/Projects` heading that matched nothing, a
`Publications` section filed as project bullets, two degrees merged into one
wrong record, `\bmaster\b` never matching "Masters", the PDF link appendix
becoming a skills category, a coursework bullet becoming a school name, its
margin wrap becoming a second school, and `Lakeside UniversityFairview, IL`
read as a location.

Both live in `tests/fixtures/` as **anonymized extracted text**: identity
replaced, every structural artifact kept byte for byte. Text, not PDF, because
they are strangers' resumes and this repository is public. Keep at least one
fixture nobody here authored, and do not tidy it — a fixture cleaned up is a
fixture that has stopped testing anything.

The same trap catches a fixture *derived* from a real one. R77's tests used
text written here from the real resume, so the thing verifying the heading
rule was authored by the person the rule existed to escape. If a fixture is a
paraphrase, it agrees with you too.

## A measurement taken through a terminal is a measurement of the terminal

R77 recorded a data defect that did not exist: en dashes, `²` and `×` "arriving
as `�`" from a PDF. The code points were correct — U+2013, U+00B2, U+00D7
— and the console could not print them. Left standing, that entry was an
invitation to write a repair pass for a problem nobody had.

**Before recording a defect in what a byte says, check what is doing the
saying.** Assert the code point, not the glyph: `assertIn("–", body)`
passes or fails on the data, and `print()` does not. The same applies to
anything read through a shell, a log line, or a screenshot — R74's own note
says a screenshot is not a measurement, and this is that rule pointed at
encodings.

**And it applies hardest to the tools that do the measuring (R81).** The
acceptance run crashed while printing its first real finding: a validation
error quoting a bullet contained `→`, the console was cp1252, and the report
died on the thing it existed to report. **A measurement tool that fails on
some findings is worse than no tool**, because it does not fail uniformly —
it reports success on exactly the cases it cannot render, and those are
correlated with the interesting ones. Two other page-count reads and one log
parse in this repo have had the same shape. Any harness that prints what it
found needs the encoding guard `agents/orchestrator._console_print` already
carries.

**The other half: check the instrument before trusting the reading.** R81
recorded Ollama at 0 of 3, and re-scoring the same output against a corrected
bar made it 1 of 3 — no change to the model or the code. The first number was
an artifact of the measuring bar, and had it been accepted it would have
entered the log as fact and survived there the way R44's verdict did for four
months. **When a result is bad enough to close a direction, re-derive it once
before writing it down.**

## The pattern reader never guesses at content

It surfaces what it cannot resolve, for a person or a model to fix. Stated once
because it has now been decided three times, identically:

- the glued email (`Boston, MApriya@...`) — every rule that trims the prefix
  also breaks `JSmith@example.com`
- `A WS` for AWS — repairing spaces inside words invents content
- `Lakeside UniversityFairview, IL` — rejected as a location, never split,
  because the same boundary splits PostgreSQL, JavaScript and LinkedIn

What makes this survivable is R33: every field is shown for correction before
anything is written. The extraction prompt asks the *model* to repair these,
and it names `"W ebApp"` as its example — the model can tell the difference and
a regex cannot. So the floor's job is to be honestly wrong in a visible place,
never quietly right-looking.

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
