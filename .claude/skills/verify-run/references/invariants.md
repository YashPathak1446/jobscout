# Unknown is never a value — where each instance is observable

**The rule:** nothing may render or score "not yet known" as though it were
known. Every field with a "not yet" state needs three cases — known, absent,
unknown — and the code has to carry all three to the place that displays or ranks
it. A loading state is not an empty state, an empty state is not a zero, and a
zero is not a "no".

The point of this file is the right-hand column. Most of these are **not**
checkable from an acceptance run, and saying otherwise is the R81 failure:
reporting coverage you do not have.

| `CLAUDE.md` item | Where it is checkable | Visible in the acceptance run? |
|---|---|---|
| `years_required: None` read as "no experience required" (R64) | `tests/test_posting_facts.py::test_a_body_that_asks_for_none`, `::test_experience_asked_for_in_words_is_unknown_not_none` | no — unit tests |
| country parse failure read as a country that did not match (R55) | `tests/test_location_country.py`; `tests/test_doc_claims_hold.py::test_r55_no_us_state_code_is_read_as_a_country` | no — unit tests |
| `location_score == 0` conflating "a state you did not name" with "state unknown" (R69) | `tests/test_location_preferences.py::test_an_unresolved_state_is_not_treated_as_elsewhere` | no — unit test |
| the React board's "Not scored" beat | **nothing** | **no — eyes only** |
| the bullet budget spending half a page on an absent projects section (R74) | `tests/test_page_is_a_page.py::test_three_jobs_and_no_projects_get_more_than_half_a_page` | **yes, partly** — see below |
| years `None` coerced to `0` (R72, R75) | `tests/test_preferences_gate.py::test_an_unanswered_number_of_years_derives_nothing_on_purpose`; `tests/test_template_presumes_nothing.py::test_years_of_experience_is_unknown_not_zero` | no — unit tests |
| visa / citizenship defaults (R72) | `tests/test_template_presumes_nothing.py::test_it_asserts_nothing_about_citizenship` | no — unit test |

## The one that is visible in a run

R74 is an **allocation**, not a display, which is why it reaches the artifacts.
The bullet budget split half a page across a projects section a resume did not
have, so three jobs shared six bullets and the bottom third of the page was
blank.

With `--keep`, look at a generated `.tex` for a fixture with no projects. If its
experience bullets number only `count // 2`, R74 has returned. The frozen list's
`page_count == 1` assertion will not catch it — a half-empty page is still one
page.

The rule reaches further than rendering: **any budget, quota or average split
across sections has to ask whether a section is empty or absent.**

## The one that is checkable by nothing

The React board rendered every job as **"Not scored"** for the beat before the
score bands arrived — a claim where a placeholder was wanted, telling the reader
analysis had skipped their whole list.

There are no frontend tests in this tree. `web/package.json` has `dev`, `build`,
`lint`, `preview` — no `test` — and there are no `*.test.*` or `*.spec.*` files
under `web/src/`. R65's 23 filter tests belonged to the deleted `frontend/`.

So this item is **eyes only**, and the way to check it is the `stranger-fixture`
skill, not this one. Report it as unchecked rather than as passing.

This item also appeared within hours of a frontend existing, which is the
general point: **anything that arrives asynchronously has an unknown state by
construction.** Every screen in the wizard displays data that loads after it
mounts.

## The sharpest form, and the test that could not see it

R75. The preferences Save button was gated on the levels a profile's years imply,
and an unanswered years field implies none — so the fix for R72's dead button
rebuilt the same dead button one field over, on both UIs. The test could not see
it because it walked `range(0, 41)` and never `None`.

**Any test that walks a range is a test that has not walked the absence.** When
reviewing a new test for one of these, check that the absent case is in it.

## The related, older rule

**A filter that removes things must say how many** (R62). The board hides jobs
the gates reject and states the count under the current filters — 59 of 136, and
14 of 19 when narrowed to one company. Silent subtraction is the same failure
wearing product clothes, and it is the reason this skill always states the
`needs_review` count.
