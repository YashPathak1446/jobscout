"""
Bullet Compression — deterministic text transformations.

Provides a library of safe, order-priority transformations that shrink a
bullet's character count without changing its meaning. Each transformation
is a pure function (text in, text out) that we can compose and test
independently.

The compression is **deterministic** — same input produces same output.
We do not depend on an LLM for length compliance, because LLMs are bad at
precise numerical constraints (verified empirically with Gemini 2.5 Flash).

Transformations are organized by aggressiveness. We apply them in order,
re-measuring after each, and stop as soon as the target is met.

Location: tools/generation/bullet_compress.py
"""

import re
from typing import List, Tuple, Callable


# Below this length, a bullet stops being meaningful — protect against
# over-aggressive compression that would gut the content.
SUBSTANTIVE_MIN = 60


# ============================================================================
# Tier 1: Free wins — whitespace, punctuation, formatting
# ============================================================================
# These are pure cleanup and never change meaning.

def collapse_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs/newlines into single spaces."""
    return re.sub(r'\s+', ' ', text).strip()


def remove_trailing_period(text: str) -> str:
    """Resume bullets traditionally don't end with periods."""
    text = text.rstrip()
    if text.endswith('.') and not text.endswith('...'):
        return text[:-1]
    return text


def normalize_dashes(text: str) -> str:
    """Convert em-dashes and en-dashes to hyphens (saves no chars but normalizes)."""
    return text.replace('—', '-').replace('–', '-')


# ============================================================================
# Tier 2: Verbose-phrase substitutions
# ============================================================================
# Each pair: (verbose_form, concise_form). Always saves >=1 char.
# Patterns are case-insensitive and use word boundaries to avoid mid-word matches.

VERBOSE_SUBSTITUTIONS: List[Tuple[str, str]] = [
    # Connector phrases
    (r'\bin order to\b',           'to'),
    (r'\bso as to\b',              'to'),
    (r'\bas well as\b',            'and'),
    (r'\balong with\b',            'and'),
    (r'\bin addition to\b',        'plus'),
    (r'\bdue to the fact that\b',  'because'),
    (r'\bfor the purpose of\b',    'for'),
    (r'\bwith the goal of\b',      'to'),
    (r'\bwith respect to\b',       'for'),
    (r'\bwith regards to\b',       'for'),
    (r'\bin terms of\b',           'for'),
    (r'\bin the process of\b',     'while'),
    (r'\bon the basis of\b',       'using'),

    # Verbose verbs
    (r'\butilized\b',              'used'),
    (r'\butilize\b',               'use'),
    (r'\bleveraged\b',             'used'),
    (r'\bimplemented\b',           'built'),
    (r'\bspearheaded\b',           'led'),
    (r'\bfacilitated\b',           'enabled'),
    (r'\bsuccessfully\s+',         ''),
    (r'\bdemonstrated\s+',         ''),

    # Result/outcome phrasing
    (r'\bresulting in\b',          'producing'),
    (r'\bwhich resulted in\b',     'producing'),
    (r'\bin order to achieve\b',   'to'),
    (r'\bproviding the ability to\b', 'enabling'),
    (r'\bgiving the ability to\b', 'enabling'),

    # Hedging / weak intensifiers
    (r'\bapproximately\s+',        '~'),
    (r'\bover a period of\b',      'over'),
    (r'\ba total of\s+',           ''),
    (r'\ba number of\b',           'several'),
    (r'\bnumerous\b',              'many'),
    (r'\bvarious\b',               ''),
    (r'\bdifferent\b',             ''),

    # Time / scope
    (r'\bcurrently\b',             ''),
    (r'\bpresently\b',             ''),
    (r'\bnow\s+',                  ''),

    # Tech-specific verbose forms
    (r'\bvia (the )?use of\b',     'via'),
    (r'\bthrough the use of\b',    'using'),
    (r'\bby way of\b',             'via'),
    (r'\bin the form of\b',        'as'),
    (r'\bmade use of\b',           'used'),
    (r'\bcarried out\b',           'ran'),
    (r'\bset up\b',                'configured'),

    # Common qualifier patterns
    (r'\bcomprised of\b',          'with'),
    (r'\bcomposed of\b',           'with'),
    (r'\bconsisting of\b',         'with'),
]


def apply_substitution(text: str, pattern: str, replacement: str) -> str:
    """Apply one regex substitution with whitespace cleanup."""
    new_text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return collapse_whitespace(new_text)


# ============================================================================
# Tier 3: Article drops (more aggressive — context-sensitive)
# ============================================================================

def drop_articles_conservative(text: str) -> str:
    """
    Drop 'the', 'a', 'an' in positions where grammar still works.

    Safe positions:
    - After common prepositions (with, by, for, in, on, of, via, using)
    - At the start of a comma-separated clause
    """
    # After preposition
    text = re.sub(
        r'\b(with|by|for|in|on|of|via|using|across|over|within|through)\s+(the|a|an)\b',
        r'\1',
        text,
        flags=re.IGNORECASE
    )
    # Start of clause
    text = re.sub(r'(^|,\s+)(the|a|an)\s+', r'\1', text, flags=re.IGNORECASE)
    return collapse_whitespace(text)


# ============================================================================
# Tier 4: Last-resort — drop weakest trailing clause
# ============================================================================

def _split_top_level_clauses(text: str) -> List[str]:
    """
    Split on commas and semicolons at the top level (outside parentheses).
    Either is a reasonable place to trim the last piece.
    """
    parts: List[str] = []
    current: List[str] = []
    paren_depth = 0

    for ch in text:
        if ch == '(':
            paren_depth += 1
            current.append(ch)
        elif ch == ')':
            paren_depth = max(0, paren_depth - 1)
            current.append(ch)
        elif ch in (',', ';') and paren_depth == 0:
            piece = ''.join(current).strip()
            if piece:
                parts.append(piece)
            current = []
        else:
            current.append(ch)

    if current:
        piece = ''.join(current).strip()
        if piece:
            parts.append(piece)

    return parts


def drop_trailing_clause(text: str) -> str:
    """
    Drop the last clause if there are at least 2 clauses, split on commas
    or semicolons at the top level (not inside parentheses).

    Refuses to drop if the result would be too short to be substantive.
    """
    text = text.rstrip()
    had_period = text.endswith('.')
    if had_period:
        text = text[:-1]

    parts = _split_top_level_clauses(text)
    if len(parts) < 2:
        return text + ('.' if had_period else '')

    # Drop the last clause
    kept = parts[:-1]
    result = ', '.join(kept) if len(kept) > 1 else kept[0]

    if len(result) < SUBSTANTIVE_MIN:
        return text + ('.' if had_period else '')

    return result + ('.' if had_period else '')


# ============================================================================
# Public API: ordered transformation pipeline
# ============================================================================

COMPRESSION_STAGES: List[Tuple[str, Callable[[str], str]]] = [
    # Tier 1 — free wins
    ('collapse_whitespace',     collapse_whitespace),
    ('remove_trailing_period',  remove_trailing_period),

    # Tier 2 — verbose phrase substitutions
    *[
        (f'sub:{pattern[:30]}', lambda t, p=pattern, r=replacement: apply_substitution(t, p, r))
        for pattern, replacement in VERBOSE_SUBSTITUTIONS
    ],

    # Tier 3 — article drops
    ('drop_articles_conservative', drop_articles_conservative),

    # Tier 4 — last resort
    ('drop_trailing_clause',    drop_trailing_clause),
]


def compress_bullet(
    text: str,
    target_max: int,
    verbose: bool = False,
) -> Tuple[str, List[str]]:
    """
    Apply compression stages in order until text fits target_max chars,
    or all stages are exhausted.

    Returns (final_text, transformations_applied).
    """
    current = text
    applied: List[str] = []

    if len(current) <= target_max:
        return current, applied

    for stage_name, transform in COMPRESSION_STAGES:
        previous = current
        try:
            current = transform(current)
        except Exception as e:
            if verbose:
                print(f"  [warn] {stage_name} failed: {e}")
            current = previous
            continue

        if current != previous:
            applied.append(stage_name)
            if verbose:
                saved = len(previous) - len(current)
                print(f"  [{stage_name}] saved {saved} chars → {len(current)}")

        if len(current) <= target_max:
            break

    return current, applied


# ============================================================================
# Quick self-test
# ============================================================================
if __name__ == "__main__":
    samples = [
        ("Containerized Weaviate and MongoDB services with Docker for dev environment parity, "
         "streamlining local testing and cross-environment consistency.", 110),

        ("Optimized MySQL read throughput via master-slave replication; implemented JWT-based "
         "authentication and Jasypt for password hashing.", 110),
    ]

    for original, target in samples:
        print(f"\nOriginal ({len(original)}): {original}")
        print(f"Target: ≤{target}")
        result, log = compress_bullet(original, target, verbose=True)
        print(f"Final   ({len(result)}): {result}")
        print(f"Stages applied: {log}")
