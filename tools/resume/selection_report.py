"""
Why this resume looks like this.

`select_components` already returns everything needed to answer that —
`score_breakdown` carries all five terms for every component it scored, and
`_composite_score` has always built them. The docstring calls them "for
logging/debugging", and that is exactly where they went: one INFO line per run,
gone when the terminal scrolled. The board could never show them because it
reads a SQLite row and the breakdown only ever existed in a per-date JSON file.

**Why a counterfactual rather than the numbers.** Printing five figures per
component is not an explanation, it is the same debug line with better
punctuation. Embedding similarity is 0.6-ish for everything and dwarfs every
other term, so naming the largest term would answer "semantic similarity" every
time and mean nothing.

What a person actually wants to know is which term *changed the outcome*: drop
it, and does this component still beat the best one that was left out? That is
computable here, because every scored component is in the same dict and the
cutoff is simply the highest-scoring component that did not make it. A term
that can be removed without changing the selection did not decide anything, no
matter how large it is.

This is the shape Q17 asked for. Its case was a tutoring role beating an AI
internship by 0.033 with every other term identical — a real outcome, defensible
even, but one that should be *visible as a near-tie* rather than presented as a
verdict. A report that says "chosen on semantic similarity alone, by 0.03" is
that.

Location: jobscout_v3/tools/resume/selection_report.py
"""

import logging

logger = logging.getLogger(__name__)

# The terms a person can act on. Embedding is deliberately absent: it is not a
# rule anyone set, and "the model thought it was similar" is the *default*
# explanation this report exists to distinguish itself from.
_ACTIONABLE = ("always", "conditional", "importance", "keyword")

_TERM_NAMES = {
    "always": "your always-include rule",
    "conditional": "a JD keyword trigger you configured",
    "importance": "its importance tier",
    "keyword": "tech terms shared with the posting",
}

# Below this the selection was a coin toss, and saying so is the point. The
# figure is Q17's margin: two components separated by 0.033 out of finals near
# 1.0, where every term but the embedding was identical.
NEAR_TIE = 0.05


def _entry(comp_id, kind, label, terms):
    return {
        "id": comp_id,
        "kind": kind,
        "label": label,
        "final": round(float(terms.get("final", 0.0)), 4),
        "terms": {name: round(float(terms.get(name, 0.0)), 4)
                  for name in ("embedding",) + _ACTIONABLE},
    }


def _decisive_terms(terms, cutoff) -> list:
    """
    Which terms, removed one at a time, would drop this below the cutoff.

    One at a time rather than in combination: the question a user is asking is
    "what put this here", and a rule that only matters in concert with another
    is not an answer they can act on.
    """
    final = float(terms.get("final", 0.0))
    decisive = []
    for name in _ACTIONABLE:
        value = float(terms.get(name, 0.0))
        if value > 0 and final - value < cutoff:
            decisive.append(name)
    return decisive


def build_selection_report(selected, labels, passed_over=3) -> dict:
    """
    Turn one job's selection into something a person can read.

    Args:
        selected: the dict `select_components` returns — needs
            `experiences`, `projects` and `score_breakdown`; `jd_keywords` and
            `conditional_fired` are carried through when present.
        labels: {component_id: human label}. Ids with no label fall back to
            the id, which is ugly but never wrong.
        passed_over: how many near-misses to keep per kind.

    Returns:
        A JSON-safe dict. Empty `picked` means there was nothing to explain,
        which is a real state — a job can be scored and never generated.
    """
    breakdown = (selected or {}).get("score_breakdown") or {}
    if not breakdown:
        return {"picked": [], "passed_over": [], "jd_keywords": [],
                "conditional_fired": {}}

    picked, missed = [], []

    for kind, key in (("experience", "experiences"), ("project", "projects")):
        chosen = list((selected.get(key) or []))
        chosen_set = set(chosen)

        # Only components of this kind, which is what the id prefix is for.
        # Falling back to "everything not of the other kind" would put projects
        # in the experience cutoff and quietly corrupt every counterfactual.
        prefix = "exp_" if kind == "experience" else "proj_"
        scored = {cid: terms for cid, terms in breakdown.items()
                  if cid.startswith(prefix)}

        rest = sorted(
            ((cid, terms) for cid, terms in scored.items() if cid not in chosen_set),
            key=lambda item: -float(item[1].get("final", 0.0)),
        )
        # Nothing was left out, so nothing was displaced and no term can be
        # shown to have decided anything. A cutoff of 0 says exactly that.
        cutoff = float(rest[0][1].get("final", 0.0)) if rest else 0.0

        for cid in chosen:
            terms = scored.get(cid)
            if terms is None:
                # Selected without a score: `always_include` can put a
                # component in the list that scoring never reached.
                continue
            entry = _entry(cid, kind, labels.get(cid, cid), terms)
            entry["margin"] = round(entry["final"] - cutoff, 4)
            entry["decisive"] = _decisive_terms(terms, cutoff)
            entry["near_tie"] = bool(rest) and entry["margin"] < NEAR_TIE
            picked.append(entry)

        for cid, terms in rest[:passed_over]:
            entry = _entry(cid, kind, labels.get(cid, cid), terms)
            # Against the *weakest* thing that got in, which is the one it
            # actually lost to.
            weakest = min(
                (float(scored[c].get("final", 0.0)) for c in chosen if c in scored),
                default=0.0)
            entry["short_by"] = round(weakest - entry["final"], 4)
            entry["near_tie"] = entry["short_by"] < NEAR_TIE
            missed.append(entry)

    return {
        "picked": picked,
        "passed_over": missed,
        "jd_keywords": list(selected.get("jd_keywords") or []),
        "conditional_fired": dict(selected.get("conditional_fired") or {}),
    }


def describe(entry) -> str:
    """
    One sentence for one chosen component.

    Deliberately says "and would have been chosen anyway" out loud when no term
    is decisive. A rule that fired but changed nothing is the most misleading
    thing this report could show — it is what the old reasoning strings did,
    reporting "Always included (profile rule)" for a component that outscored
    the field by half a point.
    """
    decisive = entry.get("decisive") or []
    margin = entry.get("margin", 0.0)

    if decisive:
        causes = " and ".join(_TERM_NAMES[name] for name in decisive)
        # Each term is tested alone, so with more than one every single one is
        # independently load-bearing. "without it" would read as "both were
        # needed together", which is the opposite of what was measured.
        tail = "without either" if len(decisive) > 1 else "without it"
        return f"Chosen because of {causes} — {tail}, this drops out."

    if entry.get("near_tie"):
        return (f"Chosen on semantic similarity alone, by {margin:.2f}. "
                f"A near-tie: the next component behind it is a defensible "
                f"substitute.")

    return (f"Chosen on semantic similarity, clear of the next component "
            f"by {margin:.2f}. No rule of yours was needed.")
