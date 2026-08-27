"""
The definition of "working". It passes or it does not.

**Why this exists.** Until now "done" implicitly meant "no more bugs found",
which is unbounded: four stranger resumes produced roughly twenty defects and
the rate falls to a trickle, never to zero. The stranger method works, which
is exactly why it will keep producing findings for as long as it is pointed at
the code. So the bar has to be a fixed list that passes, and this is it.

**The list is frozen.** Items are not added mid-flight, no matter what turns
up while fixing one. Anything found that is not on this list goes to
`known_questions.md` as a backlog entry and is not touched. What that costs is
shipping with known, logged, real defects — which is the trade, made on
purpose.

**What it asserts**, for each fixture resume, on each rung:

    the resume imports            -> a profile and a master .tex exist
    the pipeline runs             -> jobs are scored, above the threshold
    generation produces resumes   -> `valid`, not `needs_review`
    the file compiles             -> a PDF, exactly one page
    the run says what wrote it    -> the R79 rung record matches the ask

Reuses what already exists rather than re-implementing it:
`scripts.init_profile` for import, `agents.orchestrator` for the run,
`tools.generation.pdf_builder.compile_pdf` for the page count, and the R79
`rung` field for provenance.

Usage:
    python scripts/acceptance.py                  # every fixture, every rung
    python scripts/acceptance.py --rung none      # just the free-tier floor
    python scripts/acceptance.py --fixture priya
"""

import argparse
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# --- what is under test ------------------------------------------------------
#
# Each fixture needs a corpus of postings it could plausibly match. A senior
# engineer scored against new-grad postings fails for a reason that says
# nothing about the pipeline, and `tools/scraping/mock_scraper` cannot supply
# one — every JD it generates says "entry-level position perfect for new
# graduates", which is the author's own shape baked into the test data.
#
# One corpus, committed, covering the shapes the gates need: a years floor, an
# entry-level exclusion, a clearance line, a non-US location, a remote role,
# and an ordinary mid-level posting where nothing should fire. Built by
# `scripts/build_acceptance_corpus.py`, which explains why it is written
# rather than scraped or mocked.
#
# It replaces two gitignored run outputs. Those worked on one laptop and could
# never have verified a deployed instance, which is what this run has to do at
# the end of Phase 1.

CORPUS = ROOT / "tests" / "fixtures" / "acceptance_jobs.json"

FIXTURES = {
    "priya": {
        "resume": ROOT / "data" / "master_resumes" / "priya_raghunathan.pdf",
        "profile": "priya_raghunathan",
        "why": "six years, Boston, imported from a PDF this repo did not make",
    },
    "two_degrees": {
        "resume": ROOT / "tests" / "fixtures" / "resume_two_degrees_non_us.txt",
        "profile": "acceptance_two_degrees",
        "why": "a masters in progress, a bachelors abroad, Research/Projects",
    },
    "glued_runs": {
        "resume": ROOT / "tests" / "fixtures" / "resume_glued_runs_six_roles.txt",
        "profile": "acceptance_glued_runs",
        "why": "six roles, an expected graduation, bold runs with no spaces",
    },
}

# `none` is the free tier and is not optional: it is the rung a stranger with
# no key lands on, and the one that produced files that would not compile as
# recently as R73. `gemini` is the paid tier.
RUNGS = ("none", "gemini", "ollama")

# Run and reported, but not gating.
#
# Ollama cannot be the *hosted* free tier — renting a GPU to run a 7B model
# when Gemini does the same job better for 2c a resume is worse on cost,
# quality and latency at once. That path is closed deliberately, so a
# local-only rung must not block a hosted MVP.
#
# It is **not** established that it is useless locally. That is a separate
# claim and it is undiagnosed: one measurement, one deliberately-stale model
# (llama3.1:8b, chosen for comparability with R44), against a bar that turned
# out to be mis-specified. Three things are unknown and none of them are on
# the path to paying users — see the entry in known_questions.md.
ADVISORY = {"ollama"}


def say(text=""):
    """
    print(), but a console that cannot encode a character loses the character
    rather than the report.

    On Windows this script's output is cp1252, and a validation error quoting
    a bullet contains U+2192. The first Ollama run therefore **crashed while
    printing the failure it had just found** — the reporting destroying the
    finding, which is the terminal lesson from R78 arriving at the one place
    whose whole job is to tell you what broke.

    `agents/orchestrator._console_print` already does this for the same
    reason; this is the same guard rather than a second answer to it.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(text).encode(encoding, errors="replace").decode(encoding))


class Failure(Exception):
    """One assertion on the frozen list did not hold."""


def check(condition, message):
    """
    `message` may be a callable, and for anything that indexes a collection it
    must be. Python evaluates arguments before the call, so
    `check(not review, f"...{review[0]}...")` raises IndexError on the happy
    path — the failure message crashing the success case. Caught on the first
    run of this script, which is the correct place for a script like this to
    find its own bugs.
    """
    if not condition:
        raise Failure(message() if callable(message) else message)


# --- the run -----------------------------------------------------------------

def import_resume(spec):
    """
    The fixture, through the real import path, into a master `.tex`.

    The `.tex` needs a **durable** home, because `create_profile` stores an
    absolute path to it and a profile written against a temp workspace breaks
    the moment that workspace is cleaned up — which is how the second run of
    this script failed with `Resume not found` on a profile the first run had
    just made.

    Durable, but **not `data/master_resumes/`**. Putting it there made three
    property tests fail: they walk every master in the repo asserting things
    about the author's own writing, and an anonymized stranger's resume full
    of "low-latency" and "High-Performance" is not that. A harness that
    pollutes the directory the suite treats as ground truth has changed the
    thing it was measuring.

    So: a stable directory in the system temp area. Durable across runs,
    invisible to the repo, nothing to gitignore.
    """
    from scripts import init_profile

    source = spec["resume"]
    check(source.exists(), f"fixture is missing: {source}")

    home = Path(tempfile.gettempdir()) / "jobscout-acceptance"
    home.mkdir(parents=True, exist_ok=True)
    destination = home / f"{spec['profile']}.tex"
    extracted = init_profile.extract_resume(source.read_bytes(), source.name)
    if extracted["kind"] == "latex":
        shutil.copy(source, destination)
        tex = destination
    else:
        schema = extracted["schema"]
        check(schema.get("experiences") or schema.get("_unparsed"),
              "import produced no work history and nothing it could not split")
        tex = init_profile.save_extracted(schema, source, destination=destination)

    check(tex.exists() and tex.stat().st_size > 500,
          f"the imported .tex is missing or too small to be a resume: {tex}")
    return tex


def run_pipeline(profile_name, corpus, rung, output_dir):
    """The whole pipeline on a frozen corpus. No network, no discovery."""
    from agents.orchestrator import JobScoutOrchestrator

    check(Path(corpus).exists(),
          f"corpus is missing: {corpus}\n"
          f"    This is the known portability gap — corpora are run outputs "
          f"and are gitignored. See the note at the top of this file.")

    orchestrator = JobScoutOrchestrator(
        profile_name=profile_name,
        output_dir=str(output_dir),
        input_file=str(corpus),
        generate_pdf=True,
        backend=rung,
        use_cache=False,
    )
    return orchestrator.run(max_jobs=20)


def assert_the_frozen_list(state, rung):
    """Every assertion, in the order a person would care about them."""
    analysed = state.get("analysis_results") or []
    results = state.get("generation_results") or []

    check(analysed, "nothing was scored — the run found no jobs to look at")

    scores = sorted((r.get("score", {}).get("overall", 0) for r in analysed),
                    reverse=True)
    check(scores and scores[0] > 40,
          lambda: f"the best job scored {scores[0]:.1f}%, below the threshold "
                  f"of 40. This is what a stranger sees as an empty board.")

    check(results, "no resumes were generated for jobs that scored well")

    valid = [r for r in results if r.get("status") == "valid"]
    review = [r for r in results if r.get("status") == "needs_review"]

    # **At least one usable resume, and nothing bad delivered.**
    #
    # The first version of this demanded zero `needs_review`, which reads a
    # deliberate safety outcome as a failure. Gemini produced 9 valid resumes
    # and 1 quarantined for inventing "25%" — the fabrication guard doing
    # precisely its job — and the bar called that a failed run. Demanding zero
    # demands the model never miss, which is not the product's promise; the
    # promise is a usable resume and no silent bad output.
    check(valid,
          lambda: f"no resume passed validation. All {len(results)} were "
                  f"quarantined. First reason: "
                  f"{((review[0].get('validation') or {}).get('errors') or ['?'])[0][:160]}"
                  if review else "no resume passed validation")

    for record in valid:
        name = Path(record.get("latex_path") or "?").name
        check(record.get("pdf_path"),
              f"{name} was delivered as valid but produced no PDF")
        check(record.get("page_count") == 1,
              f"{name} was delivered as valid at {record.get('page_count')} "
              f"pages, not 1")

    # Nothing may be delivered that is not valid. The pipeline separates them
    # by directory, so this asserts the separation held rather than trusting
    # that it did.
    for record in review:
        check("needs_review" in str(record.get("latex_path") or ""),
              f"{Path(str(record.get('latex_path'))).name} failed validation "
              f"but was not quarantined")

    # R79: the run has to say what wrote it, and it has to be what was asked.
    used = (state.get("backend") or {}).get("used") or {}
    check(used, "the run did not record which rung wrote it")
    if rung == "none":
        check(set(used) == {"verbatim"},
              f"asked for the no-model floor and got {sorted(used)}")
    else:
        check("verbatim" not in used,
              f"asked for {rung} and the bullets came back verbatim, which "
              f"means the model was asked and did not answer: {sorted(used)}")

    return len(valid), len(review), scores[0]


def one(name, spec, rung, keep):
    """One fixture on one rung. Returns a line for the report."""
    from scripts import init_profile
    from tools.profile import list_available_profiles

    workspace = Path(tempfile.mkdtemp(prefix=f"acceptance-{name}-{rung}-"))
    try:
        # The orchestrator prints its own completion banner with `print`, not
        # through logging, so silencing logging is not enough to keep this
        # report readable.
        with contextlib.redirect_stdout(io.StringIO()):
            tex = import_resume(spec)
            # A harness may build a profile non-interactively; R33's rule
            # that a person confirms every field is about the product flow,
            # not about a test rig. `create_profile` is the same public call
            # the CLI makes, so this exercises the real path rather than a
            # parallel one.
            #
            # Rebuilt every run for the profiles this script owns, so a pass
            # means the import path still works rather than that it worked
            # once. Profiles it does not own — Priya, who is a real imported
            # fixture — are used as they are and never overwritten.
            if spec["profile"].startswith("acceptance_"):
                init_profile.create_profile(tex, spec["profile"], force=True)
            check(spec["profile"] in list_available_profiles(),
                  f"profile '{spec['profile']}' does not exist and this "
                  f"script does not own it")
            state = run_pipeline(spec["profile"], CORPUS, rung,
                                 workspace / "outputs")
        count, review, best = assert_the_frozen_list(state, rung)
        # The quarantined count is always stated, never implied by silence.
        # A gate that passes while hiding how much it set aside is the same
        # shape as a filter that removes rows without saying how many (R62).
        held = f", {review} held for review" if review else ""
        return f"{count} valid{held}, best job {best:.1f}%"
    finally:
        if not keep:
            shutil.rmtree(workspace, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=sorted(FIXTURES), default=None)
    parser.add_argument("--rung", choices=RUNGS, default=None)
    parser.add_argument("--keep", action="store_true",
                        help="leave the working directories for inspection")
    args = parser.parse_args()

    import logging
    logging.disable(logging.INFO)

    names = [args.fixture] if args.fixture else sorted(FIXTURES)
    rungs = [args.rung] if args.rung else list(RUNGS)

    print(f"Acceptance: {len(names)} fixture(s) x {len(rungs)} rung(s)\n")
    failures = []

    for name in names:
        spec = FIXTURES[name]
        say(f"{name} — {spec['why']}")
        for rung in rungs:
            label = f"  {rung:<8}"
            advisory = rung in ADVISORY
            try:
                say(f"{label} {one(name, spec, rung, args.keep)}   PASS")
            except Failure as failure:
                say(f"{label} {'(advisory) ' if advisory else ''}FAIL: {failure}")
                if not advisory:
                    failures.append((name, rung, str(failure)))
            except Exception as error:   # a crash is a failure, loudly
                say(f"{label} {'(advisory) ' if advisory else ''}"
                    f"ERROR: {type(error).__name__}: {error}")
                if not advisory:
                    failures.append((name, rung, f"{type(error).__name__}: {error}"))
        say()

    gating = len(names) * len([r for r in rungs if r not in ADVISORY])
    advisory_rungs = sorted(set(rungs) & ADVISORY)
    if advisory_rungs:
        say(f"({', '.join(advisory_rungs)} is reported, not gated — see "
            f"known_questions.md)")

    if failures:
        say(f"FAILED — {len(failures)} of {gating} gating check(s)")
        return 1
    say(f"PASSED — {gating} of {gating} gating check(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
