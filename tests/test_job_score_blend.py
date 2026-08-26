"""
A score that barely discriminated, and the signal it ignored (R67 / Q17).

Q17 was opened when a tutoring job beat an AI internship by 0.033 of embedding
similarity. The product version of the same problem is worse and measurable:
across 69 real scored jobs the score ran **41.5 to 55.8, standard deviation
3.58** — a coefficient of variation of 0.071. Half of every job sat inside a
four-point band. A user shown "55% match" against "52% match" was reading
noise. R49 met the symptom with display bands; this is the cause.

Concrete overlap — technologies named by both the posting and the resume —
discriminates about eight times better on the same corpus (CoV 0.586), and the
two orderings agree only weakly (Spearman 0.312). Where they disagreed, the
embedding was indefensible:

    Samsara  Finance & Strategy AI Engineer   ranked  2nd   3 shared terms
    Affirm   Software Engineer I, Fullstack   ranked  4th   2 shared terms
    Nuro     Full Stack Software Engineer     ranked 47th  11 shared terms
    Squarespace  Software Engineer, Frontend  near last    11 shared terms

The resume is AI-heavy, so the embedding rewards a posting that *reads* like AI
over one that names the same tools.

**Q17's own proposed remedy was measured and rejected.** It suggested deriving
a role-type signal from the title and weighting it. On this corpus
`role_score` is the maximum for **100% of scored jobs** — discovery already
gates on `target_roles`, so analysis only ever sees survivors, and the term
would have added a constant. That is the dead-signal bug this codebase has
found five times; it is not worth adding a sixth.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume.embedding_scorer import (  # noqa: E402
    KEYWORD_SATURATION,
    KEYWORD_WEIGHT,
    EmbeddingScore,
    keyword_overlap,
    resume_terms,
)


class _Component:
    def __init__(self, comp_id, keywords):
        self.id = comp_id
        self.keywords = list(keywords)


class _Resume:
    def __init__(self, experiences=(), projects=()):
        self.experiences = list(experiences)
        self.projects = list(projects)


RESUME = _Resume(
    experiences=[_Component("exp_a", ["python", "aws", "docker", "engineer"])],
    projects=[_Component("proj_a", ["pytorch", "react", "data"])],
)


class TestWhatTheResumeClaims(unittest.TestCase):
    def test_terms_come_from_every_component(self):
        self.assertEqual(
            resume_terms(RESUME),
            {"python", "aws", "docker", "pytorch", "react"})

    def test_words_every_posting_contains_are_dropped(self):
        """
        "engineer" and "data" appear in nearly every technical posting, so
        matching them is evidence of nothing.
        """
        terms = resume_terms(RESUME)
        self.assertNotIn("engineer", terms)
        self.assertNotIn("data", terms)

    def test_an_empty_resume_claims_nothing(self):
        self.assertEqual(resume_terms(_Resume()), set())


class TestOverlap(unittest.TestCase):
    def test_it_finds_the_shared_technologies(self):
        jd = "We use Python and Docker to ship services on AWS."
        self.assertEqual(keyword_overlap(jd, RESUME), ["aws", "docker", "python"])

    def test_a_posting_that_shares_nothing(self):
        self.assertEqual(keyword_overlap("We are hiring a chef.", RESUME), [])

    def test_it_matches_terms_not_substrings(self):
        """
        R18's finding, which this inherits by using `term_matches`: crediting
        "java" inside "javascript" would make the evidence half as vague as the
        embedding half.
        """
        resume = _Resume(experiences=[_Component("e", ["java"])])
        self.assertEqual(keyword_overlap("We write JavaScript here.", resume), [])
        self.assertEqual(keyword_overlap("We write Java here.", resume), ["java"])

    def test_empty_and_missing_text(self):
        self.assertEqual(keyword_overlap("", RESUME), [])
        self.assertEqual(keyword_overlap(None, RESUME), [])


class TestTheBlend(unittest.TestCase):
    """The arithmetic, stated so a weight change cannot pass unnoticed."""

    @staticmethod
    def blend(embedding_pct, shared):
        keyword_pct = min(shared / KEYWORD_SATURATION, 1.0) * 100
        return embedding_pct * (1 - KEYWORD_WEIGHT) + keyword_pct * KEYWORD_WEIGHT

    def test_evidence_lifts_a_middling_embedding_above_a_better_one(self):
        """
        The case the whole change exists for: eleven shared technologies must
        beat two, even when the embedding prefers the two.
        """
        indefensible = self.blend(54.6, 2)   # Affirm, ranked 4th
        defensible = self.blend(47.8, 11)    # Nuro, ranked 47th
        self.assertGreater(defensible, indefensible)

    def test_saturation_caps_the_evidence_half(self):
        """A posting cannot climb by repeating technologies past the cap."""
        self.assertEqual(self.blend(50, KEYWORD_SATURATION),
                         self.blend(50, KEYWORD_SATURATION * 5))

    def test_no_overlap_costs_the_keyword_share_and_no_more(self):
        self.assertAlmostEqual(self.blend(100, 0), 100 * (1 - KEYWORD_WEIGHT))

    def test_the_embedding_still_carries_most_of_it(self):
        """
        Mirrors `_composite_score`, where keyword is capped at 0.25 against an
        embedding near 0.6. The semantic half is still the majority.
        """
        self.assertLess(KEYWORD_WEIGHT, 0.5)

    def test_the_weights_are_the_measured_ones(self):
        self.assertEqual((KEYWORD_WEIGHT, KEYWORD_SATURATION), (0.3, 8))


class TestTheScoreCanBeTakenApart(unittest.TestCase):
    """
    R57's lesson applied to job scoring: a single number nobody can decompose
    is what let two shared technologies outrank eleven without anyone noticing.
    """

    def test_the_parts_are_carried(self):
        score = EmbeddingScore(
            job_id="", title="", company="", overall_score=60.0,
            best_experience_ids=[], best_project_ids=[],
            experience_scores={}, project_scores={},
            embedding_score=54.6, keyword_score=75.0,
            keyword_hits=["aws", "python"])
        self.assertEqual(score.keyword_hits, ["aws", "python"])
        self.assertEqual(score.embedding_score, 54.6)

    def test_hits_default_to_a_list_not_none(self):
        """A list field defaulting to None is a crash waiting for a consumer."""
        score = EmbeddingScore(
            job_id="", title="", company="", overall_score=0,
            best_experience_ids=[], best_project_ids=[],
            experience_scores={}, project_scores={})
        self.assertEqual(score.keyword_hits, [])
        self.assertEqual(list(score.keyword_hits), [])

    def test_two_scores_do_not_share_a_default(self):
        a = EmbeddingScore("", "", "", 0, [], [], {}, {})
        b = EmbeddingScore("", "", "", 0, [], [], {}, {})
        a.keyword_hits.append("python")
        self.assertEqual(b.keyword_hits, [])


class TestAgainstTheRealCorpus(unittest.TestCase):
    """
    The claim the constants were chosen on. Skipped on a clean clone.

    Not a fixed threshold: what must hold is that blending *increases* how much
    the score discriminates. If a future change makes the score flatter again,
    this fails.
    """

    def setUp(self):
        if not (ROOT / "data" / "jobs.db").exists():
            self.skipTest("needs a real job store")
        master = ROOT / "data" / "master_resumes" / "yash_pathak.tex"
        if not master.exists():
            self.skipTest("needs a real master resume")

        from tools.jobs.job_store import JobStore
        from tools.resume.resume_parser import ResumeParser

        self.parsed = ResumeParser(str(master)).parsed_resume
        store = JobStore()
        try:
            self.rows = [r for r in store.query(limit=500) if r["score"] is not None]
        finally:
            store.close()
        if len(self.rows) < 20:
            self.skipTest("needs a scored corpus")

    def test_blending_widens_the_spread(self):
        import statistics

        embedding, blended = [], []
        for row in self.rows:
            hits = keyword_overlap(row["full_jd"] or "", self.parsed)
            keyword_pct = min(len(hits) / KEYWORD_SATURATION, 1.0) * 100
            embedding.append(row["score"])
            blended.append(row["score"] * (1 - KEYWORD_WEIGHT)
                           + keyword_pct * KEYWORD_WEIGHT)

        self.assertGreater(statistics.stdev(blended), statistics.stdev(embedding),
                           "blending made the score less discriminating, not more")

    def test_the_role_signal_q17_proposed_is_still_constant(self):
        """
        Pins the negative result. If discovery ever stops gating on
        `target_roles`, this fails and the role term becomes worth revisiting.
        """
        from tools.profile import load_profile

        if not (ROOT / "user_profiles" / "yash_pathak.json").exists():
            self.skipTest("needs a real profile")

        roles = [r.lower() for r in load_profile("yash_pathak").job_preferences.target_roles]
        matched = sum(1 for row in self.rows
                      if any(role in (row["title"] or "").lower() for role in roles))
        self.assertEqual(matched, len(self.rows),
                         "role matching now varies — the term may be worth adding")


if __name__ == "__main__":
    unittest.main()
