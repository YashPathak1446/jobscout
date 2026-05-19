"""
Bullet Fit — pick a target zone for a bullet and use the compression
library to land in that zone.

Bridge between the LLM (which produces text) and the validator (which checks
zone compliance). Given a raw bullet from the LLM, decides which line-count
target makes sense and uses deterministic compression to reach it.

Strategy: when the LLM produces a bullet in an orphan zone, compress it
to the nearest LOWER good zone. We never expand — expansion requires content
that didn't come from the master, which is inventing.

Location: tools/generation/bullet_fit.py
"""

from dataclasses import dataclass, field
from typing import List

from tools.generation.bullet_compress import compress_bullet


# Mirrored from validation.py. Kept in sync manually.
LINE_1_END = 110
LINE_2_WELL_FILLED_START = 180
LINE_2_END = 213
LINE_3_WELL_FILLED_START = 283
LINE_3_END = 316


@dataclass
class FitResult:
    """Result of fitting one bullet."""
    text: str
    original_length: int
    final_length: int
    target_zone: str
    transformations: List[str] = field(default_factory=list)
    needs_review: bool = False


def _zone_of(length: int, component_type: str) -> str:
    """Return the zone label for a given length and component type."""
    if length == 0:
        return 'empty'
    if length <= LINE_1_END:
        return 'line_1'
    if length < LINE_2_WELL_FILLED_START:
        return 'orphan_2'
    if length <= LINE_2_END:
        return 'line_2'

    if component_type == 'experience':
        if length < LINE_3_WELL_FILLED_START:
            return 'orphan_3'
        if length <= LINE_3_END:
            return 'line_3'
        return 'overflow'
    else:
        return 'overflow'


def fit_bullet(text: str, component_type: str) -> FitResult:
    """
    Fit a raw bullet to a valid zone using deterministic compression.

    Strategy by current zone:
      - line_1, line_2, line_3:  already good, return unchanged
      - orphan_2 (111-179):      compress to line_1 (≤110)
      - orphan_3 (214-282):      compress to line_2 (target ≤213; lands in 180-213)
      - overflow (>316 exp, >213 proj): compress to nearest good zone
    """
    text = text.strip()
    original_length = len(text)
    current_zone = _zone_of(original_length, component_type)

    # Already in good zone? Return unchanged.
    if current_zone in ('line_1', 'line_2', 'line_3'):
        return FitResult(
            text=text,
            original_length=original_length,
            final_length=original_length,
            target_zone='unchanged',
        )

    if current_zone == 'empty':
        return FitResult(
            text=text,
            original_length=0,
            final_length=0,
            target_zone='failed',
            needs_review=True,
        )

    # Decide compression target.
    # When starting from orphan_3 (e.g. 228 chars), target line_2 (≤213).
    # Compression will stop as soon as we cross under 213; aiming for 180-213.
    if current_zone == 'orphan_2':
        target = LINE_1_END
        intended_zone = 'line_1'
    elif current_zone == 'orphan_3':
        target = LINE_2_END
        intended_zone = 'line_2'
    elif current_zone == 'overflow':
        if component_type == 'experience':
            target = LINE_3_END
            intended_zone = 'line_3'
        else:
            target = LINE_2_END
            intended_zone = 'line_2'
    else:
        return FitResult(
            text=text,
            original_length=original_length,
            final_length=original_length,
            target_zone='failed',
            needs_review=True,
        )

    compressed, log = compress_bullet(text, target)
    final_length = len(compressed)
    final_zone = _zone_of(final_length, component_type)

    if final_zone in ('line_1', 'line_2', 'line_3'):
        return FitResult(
            text=compressed,
            original_length=original_length,
            final_length=final_length,
            target_zone=final_zone,
            transformations=log,
        )

    return FitResult(
        text=compressed,
        original_length=original_length,
        final_length=final_length,
        target_zone='failed',
        transformations=log,
        needs_review=True,
    )


def fit_bullets(bullets: List[str], component_type: str) -> List[FitResult]:
    """Fit a list of bullets, returning one FitResult per input."""
    return [fit_bullet(b, component_type) for b in bullets]


# ============================================================================
# Self-test
# ============================================================================
if __name__ == "__main__":
    test_bullets = [
        ("Optimized MySQL read throughput via master-slave replication; implemented JWT-based authentication and Jasypt for password hashing.",
         "project", "131 chars (orphan_2) → should compress to line_1"),

        ("Architected a multi-tier data pipeline for PubMed's 36M-article corpus, designing FTP-based ingestion, Weaviate hybrid search, and Streamlit-based query interfaces for clinicians evaluating data quality.",
         "experience", "210 chars (line_2) → should stay unchanged"),

        ("Engineered a comprehensive Python batch ingestion pipeline to process PubMed articles via FTP, parsing PMID and DOI metadata, indexing chunked full-text content into Weaviate for hybrid search across the corpus, with retry logic.",
         "experience", "228 chars (orphan_3) → should compress to line_2"),
    ]

    for original, ctype, description in test_bullets:
        result = fit_bullet(original, ctype)
        print(f"\nCASE: {description}")
        print(f"  Input  ({result.original_length}): {original[:80]}...")
        print(f"  Output ({result.final_length}): {result.text}")
        print(f"  Zone: {result.target_zone}  |  needs_review: {result.needs_review}")
        if result.transformations:
            print(f"  Stages: {result.transformations[:3]}...")
