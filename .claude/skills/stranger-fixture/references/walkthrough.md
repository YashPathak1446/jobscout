# The walk, and the log

One sitting, in order, fixing nothing. Every screen below loads data after it
mounts, so every screen has an unknown state by construction — that is where to
look first.

## 1. Resume upload — `ResumeStep.tsx`

Accepts `.tex`, `.pdf`, `.docx` ([ResumeStep.tsx:156](web/src/components/steps/ResumeStep.tsx#L156)).
A `.tex` goes straight through; a PDF or DOCX goes to extraction and then to the
confirmation screen.

- **Upload a PDF, not a `.tex`.** The `.tex` path is the author's path. R69's
  escape table and R70's experience field order were both fixed in one renderer
  and left in the other, and this is the fork.
- The "continue with an existing profile" control is disabled until one is
  selected — check what a first-time user with **zero** profiles sees, not what
  a returning user sees.
- Try a file the extractor will struggle with. The floor is meant to be
  *honestly wrong in a visible place*, never quietly right-looking.

## 2. Import confirmation — `ImportConfirm.tsx`

R33: every extracted field is shown for correction before anything is written.
This screen is the second half of a two-step import, and the half that R84 found
missing from Streamlit.

- Check the `_unparsed` leftovers block. Lines the reader could not split are
  surfaced, not guessed at — the glued email (`Boston, MApriya@...`), `A WS` for
  AWS, `Lakeside UniversityFairview, IL`. **Surfacing them is correct.** A
  finding here is the screen *hiding* one, or claiming to have parsed one it did
  not.
- Use **Add an experience** and the remove buttons. With no model the floor
  returns `experiences: []` and hands the raw lines over; a stranger on the free
  tier finishes the import entirely through these controls or not at all.
- Edit a skill group heading and value. Add one, remove one, leave one blank.
- Confirm the education rows. Two degrees merged into one record, a coursework
  bullet read as a school name, and a margin wrap read as a second school are
  all real findings from this screen.

## 3. About you — `AboutYouStep.tsx`

- Continue is gated on `location` and `visa_status`
  ([AboutYouStep.tsx:194](web/src/components/steps/AboutYouStep.tsx#L194)).
  **Check the gate with each field empty, in both orders.**
- The location box placeholder is `City, State`. It used to be a *value*, and
  agreeing with the form recorded a location that does not exist. Confirm it is
  still a placeholder and that Continue is not enabled by it.
- The work-authorisation select has an `UNANSWERED` sentinel that is disabled.
  Confirm unanswered is distinguishable from answered — not a silent default,
  and not `us_citizen: true` for someone who never said so.
- Leave the clearance field alone and see what the profile records for it.

## 4. Preferences — `PreferencesStep.tsx`

This screen has produced two dead Save buttons in a row. Both were gated on
something a new profile does not have.

- Save is gated on `target_roles` being non-empty
  ([PreferencesStep.tsx:384](web/src/components/steps/PreferencesStep.tsx#L384)).
  Check it with roles set and **years left blank**. R75: the previous gate was on
  levels derived from years, and `derived_levels(None)` is `[]`, so the button
  was dead for everyone whose years field was untouched.
- Leave `years` empty and continue. Then check whether anything downstream reads
  it as `0` — `0` is a claim of new-grad status and `null` is the truth.
- Leave `states_priority` and `states_acceptable` empty. A posting listed only as
  "United States" must not be excluded as relocation (R69).
- Set a country the parser will not resolve and see whether it scores as "a
  country that did not match" or as unknown (R55).

## 5. Tuning — `TuningStep.tsx`

Component importance and JD triggers, both normally *derived* from the resume
rather than authored.

- Check what this shows for a profile whose derivation produced little — an
  empty section is not the same as a section that has not loaded.
- Save, then Skip. Confirm skipping does not silently write defaults.

## 6. Run — `RunStep.tsx`

- Unavailable rungs stay listed and disabled with a reason
  ([RunStep.tsx:186](web/src/components/steps/RunStep.tsx#L186)). Confirm the
  reason is legible: "Ollama (not running)" tells somebody something; a missing
  row does not.
- Start a run and watch the progress. Runs are background threads with on-disk
  progress, so **close the tab mid-run and reopen it** — the progress must still
  be there.
- Run on `none` at least once. It is a complete product and it is what a stranger
  with no key lands on.

## 7. Board — `Board.tsx`, `BackendPanel.tsx`

- **Watch the first beat after the board mounts.** Score bands arrive
  asynchronously; the board rendered every job as **"Not scored"** in that
  window, telling the reader analysis had skipped their whole list. A loading
  state is not an empty state.
- `BackendPanel` has the same shape — `backend === null` is "still detecting",
  which is not "no model" ([BackendPanel.tsx:72](web/src/components/BackendPanel.tsx#L72)).
- Narrow by company and by source. The count under the current filters must be
  stated (R62) — `59 of 136`, `14 of 19`. A list shorter than what was stored
  owes the reader a number.
- Clear all filters from an empty result. The empty state must distinguish "no
  jobs stored" from "no jobs match".
- Mark a job applied, then re-run discovery. The status must survive.

---

# The log format

A table. One row per finding. Nothing else — no severity, no triage, no
proposed fix.

| # | Screen | Exact input | What happened | What was expected |
|---|---|---|---|---|
| 1 | Preferences | `years` left empty, `target_roles = ["Backend Engineer"]` | Save stayed disabled | Save enabled; years is optional |

**Write non-ASCII as a code point.** `U+2192`, not `→`. `U+2013`, not `–`. R81's
harness crashed while printing the first real finding it ever produced, because
a bullet in a validation error contained `U+2192` and the console was cp1252 —
the report destroying the finding. R77 recorded a defect that did not exist for
the mirror-image reason: the code points were right and the terminal could not
draw them. **Before recording a defect in what a byte says, check what is doing
the saying.**

Close the log with two lines:

- **Axes exercised:** which rows of [axes.md](axes.md) this fixture actually
  differed on.
- **Axes not exercised:** the rest.

If the table is empty, the honest summary is *"this fixture found nothing, and
these axes went untested"* — not *"the product is clean"*.

Findings go to `known_questions.md` as backlog entries. The frozen list in
`scripts/acceptance.py` does not grow.
