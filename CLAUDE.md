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
