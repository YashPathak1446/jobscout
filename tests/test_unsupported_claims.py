r"""
A figure replaced by a word (R58).

R45 built `find_invented_metrics`: a number in the output that appears nowhere
in the master. That is the direction that catches fabrication, and Q6 recorded
that the other direction — does a master figure survive compression — was still
unmeasured with no observed failure.

It has one now, from 2026-08-25. Master:

    ... XGBoost achieving 94.2\% accuracy ($\pm$0.2\%) and a 15-point macro-F1
    lift over Random Forest (0.71 vs 0.56) - driven by recall gains on critical
    minority classes ...

Shipped as:

    ... achieving 94.2\% accuracy and significant macro-F1 gains over baseline
    models.

Four numbers left and one word arrived. **Dropping a metric is not the error** —
a 386-character master bullet cannot keep six figures inside a 213-character
budget, and compression is the job. The error is dropping it and asserting the
magnitude anyway, because "significant" is a claim the master never makes.

The discriminator is what makes this checkable rather than a style opinion.
Across every resume this repo has generated there are exactly three of these
words, and they split cleanly:

    "delivering a significant ~3.6x speedup (137s → 38s)"     padding  (warning)
    "...speedup..., significantly reducing redundant compute"  padding  (warning)
    "94.2% accuracy and significant macro-F1 gains"            standing in (error)

The master resume itself contains none of these words at all, which is what
makes their presence in output meaningful rather than stylistic.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.generation.validation import (  # noqa: E402
    VAGUE_INTENSIFIERS,
    extract_metrics,
    find_unsupported_claims,
    is_significant_metric,
    validate_resume_output,
)

# The real pair, verbatim.
ANTIBIOTIC_MASTER = (
    "Engineered k-mer feature extraction (k=6, 169K unique k-mers) with TF-IDF "
    "vectorization (scikit-learn) and trained Random Forest vs. XGBoost "
    "classifiers under stratified 5-fold cross-validation, with XGBoost "
    "achieving 94.2\\% accuracy ($\\pm$0.2\\%) and a 15-point macro-F1 lift over "
    "Random Forest (0.71 vs 0.56) - driven by recall gains on critical minority "
    "classes (carbapenem 0.17$\\rightarrow$1.00, aminoglycoside 0.42$\\rightarrow$0.89)."
)

ANTIBIOTIC_OUTPUT = (
    "Engineered an XGBoost machine learning pipeline to predict antibiotic "
    "resistance from bacterial protein sequences, achieving 94.2% accuracy and "
    "significant macro-F1 gains over baseline models."
)

JOBSCOUT_MASTER = (
    "Engineered an embedding cache and a persistent job-deduplication layer, "
    "delivering a 3.6x speedup on warm runs (137s to 38s)."
)


def output(component_id, bullets, section="projects"):
    payload = {"experiences": [], "projects": []}
    payload[section] = [{"id": component_id, "bullets": list(bullets)}]
    return payload


class TestTheObservedFailure(unittest.TestCase):
    """The bullet that started this."""

    def test_it_is_found(self):
        findings = find_unsupported_claims(
            output("proj_antibiotic", [ANTIBIOTIC_OUTPUT]),
            {"proj_antibiotic": [ANTIBIOTIC_MASTER]})
        self.assertEqual(len(findings), 1)

        component_id, word, dropped, _ = findings[0]
        self.assertEqual(component_id, "proj_antibiotic")
        self.assertEqual(word, "significant")
        self.assertIn("15-point", dropped)
        self.assertIn("0.71 vs 0.56", dropped)

    def test_the_figure_that_did_survive_is_not_reported_as_dropped(self):
        _, _, dropped, _ = find_unsupported_claims(
            output("proj_antibiotic", [ANTIBIOTIC_OUTPUT]),
            {"proj_antibiotic": [ANTIBIOTIC_MASTER]})[0]
        self.assertNotIn("94.2%", dropped)

    def test_it_is_an_error_not_a_warning(self):
        result = validate_resume_output(
            output("proj_antibiotic", [ANTIBIOTIC_OUTPUT, "A second bullet here."]),
            master_bullets={"proj_antibiotic": [ANTIBIOTIC_MASTER]})
        self.assertTrue(any("macro-F1" in e or "15-point" in e
                            for e in result.errors), result.errors)

    def test_dropping_the_claim_with_the_figure_is_accepted(self):
        """The fix the prompt asks for: lose the number, lose the sentence."""
        clean = ("Engineered an XGBoost pipeline to predict antibiotic resistance "
                 "from bacterial protein sequences, achieving 94.2% accuracy.")
        self.assertEqual(
            find_unsupported_claims(output("proj_antibiotic", [clean]),
                                    {"proj_antibiotic": [ANTIBIOTIC_MASTER]}),
            [])

    def test_keeping_the_figure_is_accepted(self):
        kept = ("Engineered an XGBoost pipeline achieving 94.2% accuracy and a "
                "15-point macro-F1 lift over Random Forest (0.71 vs 0.56).")
        self.assertEqual(
            find_unsupported_claims(output("proj_antibiotic", [kept]),
                                    {"proj_antibiotic": [ANTIBIOTIC_MASTER]}),
            [])


class TestPaddingIsNotTheSameFailure(unittest.TestCase):
    """
    The other two real cases: the word is wordy, not load-bearing.

    Treating these as errors would send a resume into the repair loop over a
    style nit, and would teach someone to ignore the error that matters — the
    trap R45 was calibrated against.
    """

    def test_an_intensifier_beside_its_own_number_is_only_a_warning(self):
        bullet = ("Engineered an embedding cache delivering a significant 3.6x "
                  "speedup on warm runs (137s to 38s).")
        findings = find_unsupported_claims(
            output("proj_jobscout", [bullet]), {"proj_jobscout": [JOBSCOUT_MASTER]})
        self.assertEqual(findings[0][2], [])

        result = validate_resume_output(
            output("proj_jobscout", [bullet, "Second bullet."]),
            master_bullets={"proj_jobscout": [JOBSCOUT_MASTER]})
        self.assertEqual(
            [e for e in result.errors if "significant" in e], [])
        self.assertTrue(any("significant" in w for w in result.warnings))

    def test_a_figure_moved_to_another_bullet_still_counts_as_kept(self):
        """A rewrite may reorganise. Per component, not per bullet."""
        findings = find_unsupported_claims(
            output("proj_jobscout", [
                "Engineered an embedding cache, significantly reducing overhead.",
                "Delivered a 3.6x speedup on warm runs, from 137s to 38s.",
            ]),
            {"proj_jobscout": [JOBSCOUT_MASTER]})
        self.assertEqual(findings[0][2], [])


class TestTheMetricsThatWereInvisible(unittest.TestCase):
    """
    Neither form was extractable before, which is how four numbers left unseen.
    """

    def test_a_margin_in_points(self):
        self.assertIn("15-point", extract_metrics("a 15-point macro-F1 lift"))
        self.assertTrue(is_significant_metric("15-point"))

    def test_a_before_and_after_pair(self):
        self.assertIn("0.71 vs 0.56",
                      extract_metrics("over Random Forest (0.71 vs 0.56)"))
        self.assertTrue(is_significant_metric("0.71 vs 0.56"))

    def test_an_arrow_pair(self):
        self.assertTrue(extract_metrics("recall rose 0.17 -> 1.00"))

    def test_a_bare_decimal_is_still_not_a_metric(self):
        """
        Deliberate. "0.71" alone cannot be told from a version number, and a
        check that fires on "Python 3.11" is one people learn to click past.
        """
        self.assertEqual(extract_metrics("built on Python 3.11 and Node 18"), [])


class TestScope(unittest.TestCase):
    """What the check must not do."""

    def test_no_master_bullets_means_no_opinion(self):
        result = validate_resume_output(
            output("proj_x", [ANTIBIOTIC_OUTPUT, "Second bullet."]))
        self.assertEqual([e for e in result.errors if "significant" in e], [])

    def test_a_component_with_no_source_is_skipped(self):
        self.assertEqual(
            find_unsupported_claims(output("proj_unknown", [ANTIBIOTIC_OUTPUT]),
                                    {"proj_other": [ANTIBIOTIC_MASTER]})[0][2],
            [])

    def test_clean_output_produces_nothing(self):
        self.assertEqual(
            find_unsupported_claims(
                output("proj_x", ["Built a thing with Python and shipped it."]),
                {"proj_x": ["Built a thing with Python, shipping it in 3 weeks."]}),
            [])

    def test_malformed_components_do_not_raise(self):
        self.assertEqual(
            find_unsupported_claims(
                {"experiences": ["not a dict"], "projects": None}, {}),
            [])

    def test_non_string_bullets_are_ignored(self):
        self.assertEqual(
            find_unsupported_claims(output("proj_x", [None, 42]), {}), [])

    def test_the_word_list_is_only_intensifiers(self):
        """
        No hedges, no adverbs of manner. This check is about asserting a
        magnitude, and widening it into a style guide would make it noise.
        """
        for word in VAGUE_INTENSIFIERS:
            self.assertNotIn(word, ("very", "really", "quite", "robust",
                                    "scalable", "efficient"))


class TestTheAdjectiveHalf(unittest.TestCase):
    r"""
    The adverbs above are how a model asserts a size in the abstract. When the
    figure that left was a latency or a rate, it reaches for an adjective
    instead, and for four months none of them fired.

    Measured across 61 generated resumes: this same 101gen bullet came back as
    "low-latency" seven times, "high-performance" twice and "high-speed" once,
    and the antibiotic bullet came back as "high precision" — every one beside
    a dropped figure, every one passing `validate_resume_output`. The one that
    shipped is from the 2026-08-26 run, the first run made by a profile that
    was not the author's.
    """

    LATENCY_MASTER = (
        "Benchmarked Weaviate against AWS Elasticsearch and Pinecone to select a "
        "vector database, achieving p99 query latency of $<$5ms and 5K+ QPS at "
        "million-scale via HNSW-indexed approximate nearest neighbor search."
    )
    # Shipped on the Affirm resume, 2026-08-26.
    LATENCY_OUTPUT = (
        "Designed a multi-tier data pipeline for PubMed's 36M-article corpus, "
        "architecting a storage system utilizing Weaviate and MongoDB to "
        "facilitate high-performance retrieval for domain-specific models"
    )

    def test_an_adjective_standing_in_for_a_rate_is_an_error(self):
        result = validate_resume_output(
            output("exp_101gen", [self.LATENCY_OUTPUT, "A second bullet here."],
                   section="experiences"),
            master_bullets={"exp_101gen": [self.LATENCY_MASTER]})
        self.assertTrue(any("high-performance" in e for e in result.errors),
                        result.errors)

    def test_low_latency_is_the_same_claim(self):
        bullet = ("Architected a multi-tier pipeline over PubMed's 36M-article "
                  "corpus to power low-latency LLM retrieval.")
        findings = find_unsupported_claims(
            output("exp_101gen", [bullet], section="experiences"),
            {"exp_101gen": [self.LATENCY_MASTER]})
        self.assertEqual([f[1] for f in findings], ["low-latency"])
        self.assertIn("5ms", findings[0][2])

    def test_high_precision_covers_the_accuracy_case(self):
        bullet = ("Engineered k-mer feature extraction with TF-IDF vectorization "
                  "and trained XGBoost classifiers to predict antibiotic "
                  "resistance with high precision and generalizability.")
        findings = find_unsupported_claims(
            output("proj_antibiotic", [bullet]),
            {"proj_antibiotic": [ANTIBIOTIC_MASTER]})
        self.assertEqual([f[1] for f in findings], ["high precision"])

    def test_keeping_the_figure_is_still_accepted(self):
        kept = ("Benchmarked Weaviate against Elasticsearch and Pinecone, "
                "achieving p99 query latency of 5ms and 5K+ QPS at million-scale.")
        self.assertEqual(
            find_unsupported_claims(
                output("exp_101gen", [kept], section="experiences"),
                {"exp_101gen": [self.LATENCY_MASTER]}),
            [])

    def test_the_words_measured_as_padding_stayed_off(self):
        """
        The half of the widening that was rejected. Each of these was proposed,
        measured across the same 61 resumes, and found beside *no* dropped
        figure — "strongly" 13 times, "optimal" 3, "comprehensive" 1, all of
        them padding. Adding them would have bought 0 signal and 17 warnings,
        which is what R58 deleted `_validate_metric_preservation` for.
        """
        for word in ("strongly", "optimal", "comprehensive", "extensive",
                     "superior", "highly"):
            self.assertNotIn(word, VAGUE_INTENSIFIERS)

    def test_the_authors_own_vocabulary_stayed_off(self):
        """
        "efficient" and "strongly" appear in the master resume's own bullets,
        so they carry no signal — the premise test below would reject them.
        Recorded here as a decision rather than left to be rediscovered.
        """
        for word in ("efficient", "strongly", "high-concurrency",
                     "high-traffic", "real-time"):
            self.assertNotIn(word, VAGUE_INTENSIFIERS)


class TestAgainstEveryResumeInTheRepo(unittest.TestCase):
    """
    Calibration, in R45's shape: the check is only worth having if the rate is
    low and each hit is real. Three across roughly thirty resumes when written.
    """

    def setUp(self):
        # `needs_review/` counts. It was excluded when this was written, and
        # that is exactly where the adjective family was shipping: a resume
        # held back for an unrelated length error still carried the claim, and
        # the calibration set could not see it. A check calibrated only
        # against output that passed cannot measure what fails.
        self.tex = sorted(ROOT.glob("outputs/*/*.tex")) + \
            sorted(ROOT.glob("outputs/*/needs_review/*.tex")) + \
            sorted(ROOT.glob("baselines/*/*.tex"))
        if not self.tex:
            self.skipTest("needs generated resumes")

    def test_the_master_resume_uses_none_of_these_words(self):
        """
        The premise. If the author wrote "significant" in their own bullets,
        the word would carry no signal and this check would be a style
        preference wearing a validator's clothes.
        """
        import re

        masters = list(ROOT.glob("data/master_resumes/*.tex"))
        if not masters:
            self.skipTest("needs a master resume")

        pattern = re.compile(r"\b(" + "|".join(VAGUE_INTENSIFIERS) + r")\b", re.I)
        for master in masters:
            found = pattern.findall(master.read_text(encoding="utf-8"))
            self.assertEqual(found, [], f"{master.name} contains {found}")

    def test_the_rate_across_generated_output_is_low(self):
        import re

        pattern = re.compile(r"\b(" + "|".join(VAGUE_INTENSIFIERS) + r")\b", re.I)
        hits = sum(len(pattern.findall(path.read_text(encoding="utf-8")))
                   for path in self.tex)
        self.assertLess(hits, len(self.tex) / 2,
                        f"{hits} intensifiers across {len(self.tex)} resumes — "
                        f"too common to treat as a signal")


if __name__ == "__main__":
    unittest.main()
