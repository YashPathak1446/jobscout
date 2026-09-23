"""
Job Filter

Evaluates whether a job should be included or excluded based on
user profile preferences. Handles all filtering and scoring decisions.

This module is the "how" of filtering — the profile is the "what."

Location: jobscout_v3/tools/jobs/job_filter.py
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List

from .location_matcher import parse_location, LocationResult

logger = logging.getLogger(__name__)


@dataclass
class FilterDecision:
    """Result of evaluating a job against a profile."""
    exclude: bool
    reason: Optional[str] = None

    # Scores (higher = better match)
    location_score: int = 0      # 3=priority, 2=acceptable, 1=remote, 0=other, -1=unknown
    role_score: int = 0          # 0-3 based on title match
    seniority_score: int = 0     # 2=explicit entry-level, 1=acceptable, 0=unknown, -1=senior

    # Parsed location for downstream use
    location_result: Optional[LocationResult] = None

    # Human-readable reasoning for UI/logging
    reasons: List[str] = field(default_factory=list)

    @property
    def overall_score(self) -> int:
        """
        Composite discovery score.
        Used for ranking jobs after filtering.
        Higher is better.
        """
        if self.exclude:
            return -1
        return (
            self.location_score * 10
            + self.role_score * 8
            + self.seniority_score * 5
        )


# Wording that marks a posting as pitched above entry level. Used only to
# decide whether a posting *needs* to match the profile's accepted range —
# a title with none of these is never excluded on seniority.
SENIOR_INDICATORS = [
    'senior', 'sr.', 'sr ', 'staff', 'principal',
    'lead', 'director', 'manager', 'head of',
]

# How each level a profile can ask for actually appears in job ads. The
# profile stores levels ("new grad"); postings phrase them a dozen ways
# ("recent graduate", "0-2 years", "University Graduate"), so the profile
# field alone would match far less than it should.
SENIORITY_SYNONYMS = {
    "new grad": ["new grad", "new graduate", "recent graduate",
                 "university graduate", "early career", "campus"],
    "entry level": ["entry level", "entry-level", "associate",
                    "0-2 years", "0-1 years", "1-2 years"],
    "junior": ["junior", "jr.", "jr "],
    "mid": ["mid-level", "mid level", "2-4 years", "3-5 years",
            "engineer ii", "engineer iii"],
    "senior": ["senior", "sr.", "sr ", "5+ years", "engineer iv"],
    "staff": ["staff", "principal", "8+ years", "10+ years"],
    "lead": ["lead", "manager", "director", "head of"],
}


# How many years of experience each band covers, and which level words a
# posting at that band tends to use. The wizard asks the fact a person knows —
# how long they have worked — and this turns it into the vocabulary the gates
# and the search queries need (R68).
#
# Two levels per band because people apply upward: someone three years in reads
# both junior and mid postings as plausible.
_YEARS_TO_LEVELS = (
    (1,  ["new grad", "entry level"]),
    (2,  ["entry level", "junior"]),
    (4,  ["junior", "mid"]),
    (7,  ["mid", "senior"]),
    (9,  ["senior", "staff"]),
)
_TOP_BAND = ["staff", "lead"]

# The gap between what you have and the highest floor still worth applying to.
#
# Three, because that is what the old level map already produced at both points
# a real profile had been measured at: a new grad (0 years) tolerated a floor of
# 3, and a [mid, senior] profile tolerated 8 — which is 5 + 3. So R54's gate
# keeps the behaviour it was measured with and loses the lookup table from its
# path.
YEARS_TOLERANCE = 3


def derive_levels(years) -> list:
    """The seniority words that fit someone with this much experience."""
    if years is None:
        return []
    try:
        years = max(0, int(years))
    except (TypeError, ValueError):
        return []
    for ceiling, levels in _YEARS_TO_LEVELS:
        if years <= ceiling:
            return list(levels)
    return list(_TOP_BAND)


def effective_seniority(profile) -> list:
    """
    The levels this profile actually wants, derived unless it says otherwise.

    Follows R15's `merge_importance`: what the profile states explicitly wins,
    and what it leaves out is derived. **Emptiness is the flag** — nothing ever
    writes a derived value back into `seniority`, so a user who overrides the
    range keeps it through any number of edits to unrelated fields. A field
    that is recomputed on save is a field that loses your answer.
    """
    prefs = getattr(profile, "job_preferences", None)
    stated = [lvl for lvl in (getattr(prefs, "seniority", None) or []) if (lvl or "").strip()]
    if stated:
        return stated
    return derive_levels(getattr(prefs, "years_experience", None))


def primary_seniority_term(profile) -> str:
    """
    The level to put in a search query, or "" for a profile with no opinion.

    Keyword search takes one term, not a range, and the profile's list is
    ordered by preference — so the first level is the one to search for.

    This exists because both keyword-search callers passed the literal string
    `"new grad"` regardless of the profile (R66). R34 made the *gate* read
    `job_preferences.seniority` and roadmap item 13 recorded the work as done,
    but the queries kept hunting new-grad roles, so a mid-level user's pool was
    filled with jobs their own gate would then throw away.

    Empty rather than a default, because `build_serper_query` already omits an
    empty seniority and an unfiltered role search beats a wrong one.
    """
    for level in effective_seniority(profile):
        term = (level or "").strip()
        if term:
            return term
    return ""


def wants_early_career(profile) -> bool:
    """
    Is this profile's range low enough for new-grad sources to be worth reading?

    `github_newgrad` is curated new-grad lists by nature — there is no senior
    equivalent — so for a profile that does not accept those levels it fills
    the discovery pool with postings the gate immediately discards.
    """
    levels = {(level or "").strip().lower() for level in effective_seniority(profile)}
    return bool(levels & {"new grad", "entry level", "junior"})


def accepted_seniority_terms(levels) -> list:
    """
    Expand a profile's seniority levels into the phrasings ads actually use.

    This replaces a hardcoded entry-level list. `job_preferences.seniority`
    has existed on every profile since the schema was written and was read by
    nothing but a print statement — the same dead-field shape as
    `rarely_include` (R31). Reading it is what lets a mid-level or senior user
    see jobs at all, rather than having their whole range excluded by a
    constant written for one new grad.

    An unknown level falls back to matching itself, so a profile can name a
    level this map has never heard of and still work.
    """
    terms = []
    for level in levels or []:
        key = (level or "").strip().lower()
        if not key:
            continue
        # The level's own name always counts. An ad that literally says
        # "mid" should match the "mid" level, and only the paraphrases are
        # listed in the map.
        terms.append(key)
        terms.extend(SENIORITY_SYNONYMS.get(key, []))
    return sorted(set(terms))


# ---------------------------------------------------------------------------
# The body gate (R54)
#
# `evaluate()` above reads the *title*, and that is deliberate: it runs before
# enrichment, so it must not need a JD, which protects the scraping budget.
# The cost is that it cannot see a clean title over a disqualifying body, and
# three of eight resumes in one run went to jobs that ruled the candidate out
# in their second paragraph:
#
#   Samsara     "Finance & Strategy AI Engineer"        8+ years experience
#   Scale AI    "Forward Deployed Software Engineer"    5+ years experience
#   Databricks  "AI Engineer - FDE (ALL LEVELS)"        "not intended for
#                                                        new graduate ...
#                                                        applicants"
#
# Databricks is the sharpest: the title advertises all levels and the body
# excludes new graduates by name.
#
# So this is a second pass, after enrichment and before generation. It reads
# the JD and costs nothing — no model, no network, just regex — which is what
# lets it sit downstream of the cheap gate without undoing that gate's point.
# ---------------------------------------------------------------------------

# How many years of experience a candidate at each level can credibly claim.
# The gate compares a JD's *floor* against the top of the profile's range, so
# a profile of [new grad, entry level, junior] tolerates a floor of 3 and is
# ruled out by 5.
YEARS_BY_LEVEL = {
    "new grad": 0, "entry level": 2, "junior": 3,
    "mid": 5, "senior": 8, "staff": 10, "lead": 10,
}

# A requirement, not an anecdote. "5+ years" and "3-5 years" are floors; the
# nearby word "experience" is what separates them from "grew 40% in 3 years".
_YEARS_PATTERNS = (
    re.compile(r"(\d{1,2})\s*\+\s*years?", re.I),
    # The `\+?` on the upper bound matters more than it looks. A real posting
    # read "3-5+ years of QA automation experience": without it only the "5+"
    # matched, the floor was read as 5 rather than 3, and a job the candidate
    # qualifies for was dropped. A gate's false positives are invisible —
    # nobody sees the job that was never shown — so the range form has to win.
    re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*\d{1,2}\s*\+?\s*years?", re.I),
    re.compile(r"(?:at least|minimum(?:\s+of)?|min\.?)\s*(\d{1,2})\s*years?", re.I),
)

_EXPERIENCE_NEARBY = re.compile(
    r"experience|building|engineering|professional|industry|working", re.I)

# Terms that describe the candidate this profile is.
_ENTRY_TERMS = re.compile(
    r"new\s+grad(?:uate)?s?|entry[-\s]?level|recent\s+graduates?|"
    r"university\s+graduates?|early\s+career", re.I)

# Phrases that turn a mention of those terms into an exclusion. Without this
# the gate would reject the very jobs it exists to keep: Elastic's JD reads
# "an entry-level position perfect for new graduates", which contains every
# term above and means the opposite.
_EXCLUSION_CUES = re.compile(
    r"not\s+intended\s+for|not\s+(?:open|available|suitable)\s+(?:to|for)|"
    r"is\s+not\s+an?\s|does\s+not\s+(?:accept|consider)|"
    r"no\s+(?:new\s+grad|entry[-\s]?level)|unfortunately[^.]{0,40}not|"
    r"cannot\s+(?:accept|consider)|ineligible", re.I)


def _tolerated_years(profile) -> int:
    """
    The highest experience floor still worth applying to.

    Read from `years_experience` when the profile states it, because that is
    the number this has always been trying to recover — the level map existed
    only to turn words back into years (R68). A profile that overrides its
    levels instead still resolves through the map, so nothing that was tuned by
    hand changes.
    """
    prefs = getattr(profile, "job_preferences", None)
    years = getattr(prefs, "years_experience", None)
    stated_levels = [lvl for lvl in (getattr(prefs, "seniority", None) or [])
                     if (lvl or "").strip()]

    if years is not None and not stated_levels:
        return max(0, int(years)) + YEARS_TOLERANCE

    known = [YEARS_BY_LEVEL[level.strip().lower()]
             for level in effective_seniority(profile)
             if level.strip().lower() in YEARS_BY_LEVEL]
    # An unrecognised range should not silently reject everything, so an empty
    # result means "no opinion" rather than "zero years tolerated".
    return max(known) if known else max(YEARS_BY_LEVEL.values())


def required_years(text: str):
    """
    The lowest experience floor the JD states, or None if it states none.

    The *lowest* because a posting often lists several — "5+ years backend,
    2+ years with Go" — and the smallest is the one a candidate has to clear
    to be considered at all. Taking the largest would reject jobs over a
    nice-to-have.
    """
    floors = []
    for pattern in _YEARS_PATTERNS:
        for match in pattern.finditer(text or ""):
            window = text[max(0, match.start() - 60):match.end() + 60]
            if _EXPERIENCE_NEARBY.search(window):
                floors.append(int(match.group(1)))
    return min(floors) if floors else None


def excludes_entry_level(text: str) -> bool:
    """
    Does the body rule out early-career applicants *by name*?

    Presence of "new graduate" proves nothing on its own — the jobs worth
    keeping say it too. What matters is an exclusion cue shortly before it,
    which is how "not intended for internship, new graduate, or entry-level
    applicants" is told apart from "perfect for new graduates".
    """
    for term in _ENTRY_TERMS.finditer(text or ""):
        before = text[max(0, term.start() - 120):term.start()]
        if _EXCLUSION_CUES.search(before):
            return True
    return False


# ---------------------------------------------------------------------------
# Eligibility the JD states outright (R56 / Q10)
#
# R54 gates on how much experience a posting asks for. This gates on *who is
# allowed to hold the job at all* — a different failure class, and the one R2's
# bet explicitly does not cover. A wrong-level job scores low against a new-grad
# profile and falls out of the funnel on its own; a clearance-gated job can be a
# genuinely excellent semantic match and score high on merit. Scale AI's
# "DevOps Engineer, Infrastructure & Security" cleared R54 (2 years) and R55
# (Washington, DC) and sat in the pool with this in its Must-have list:
#
#   "candidates will not be considered who do not hold at least a TS/SCI
#    clearance"
#
# Q10 asked whether this needed an employer denylist. It does not: the postings
# say so themselves, and reading the text generalises where a list of defense
# primes would only encode one user's guess about who does cleared work.
#
# The candidate facts already exist and the UI already collects them —
# `personal_info.us_citizen`, `.permanent_resident` and `.visa_status` have been
# on every profile since R16 and were read by nothing. The only genuinely new
# one is whether the user holds a clearance, which no resume could imply.
#
# A4 replaced those booleans with `personal_info.work_authorization`: three
# answers, each "yes", "no" or "unknown", read only through `work_answer`.
# The booleans could not say "unknown", so a profile that never answered was
# judged a non-US person without sponsorship rights or a clearance.
# ---------------------------------------------------------------------------

# Held vs obtainable is the whole design. A posting that demands an *active*
# clearance rules out everyone who does not have one: clearances take months and
# need an employer to sponsor the investigation, so it is not something an
# applicant can go and get. A posting asking only for *eligibility* to obtain
# one rules out nobody who is a US person, because that is all eligibility
# means.
#
# Scale AI wrote both, one in each posting, and the difference decides whether a
# US citizen without a clearance should ever see the job:
#
#   FDE, Public Sector:  "An active TS/SCI clearance, or eligibility to
#                         obtain one."                          -> obtainable
#   DevOps, Infra:       "will not be considered who do not hold at least a
#                         TS/SCI clearance"                     -> held
#
# So when one sentence carries both cues the weaker one wins — the same rule
# `required_years` uses for "5+ years backend, 2+ years Go". Reading that
# disjunction as a hard requirement would hide a job the candidate may apply
# for, and a gate's false positives are invisible: nobody sees the job that was
# never shown.
_CLEARANCE_WORDS = r"clearance|ts/sci|top\s+secret|secret\s+level|polygraph|poly\b"

_CLEARANCE_HELD = re.compile(
    r"(?:active|current|existing|must\s+(?:possess|hold|have)|do\s+not\s+hold|"
    r"already\s+hold|in\s+possession\s+of)[^.]{0,60}?(?:" + _CLEARANCE_WORDS + r")|"
    r"(?:" + _CLEARANCE_WORDS + r")[^.]{0,40}?(?:is\s+required|required\s+to\s+start)",
    re.I)

_CLEARANCE_OBTAINABLE = re.compile(
    r"(?:ability|able|eligibility|eligible|willing(?:ness)?|qualify)\s+to\s+"
    r"(?:obtain|acquire|be\s+granted)|"
    r"(?:obtain|acquire)\s+(?:and\s+maintain\s+)?(?:an?\s+)?[^.]{0,30}?"
    r"(?:" + _CLEARANCE_WORDS + r")",
    re.I)

# "U.S. Person" is the ITAR term and it means citizen *or* lawful permanent
# resident, which is why green-card holders are checked alongside citizens
# rather than being lumped in with people who need sponsorship.
_US_PERSON_REQUIRED = re.compile(
    r"u\.?\s?s\.?\s*(?:citizen(?:ship)?|person)|united\s+states\s+citizen|"
    r"\bitar\b|export[-\s]control|public\s+trust|"
    r"must\s+be\s+a\s+(?:u\.?s\.?|united\s+states)",
    re.I)

_NO_SPONSORSHIP = re.compile(
    r"(?:not|unable|cannot|can\s?not|do(?:es)?\s+not)\s+"
    # Every optional word here is a phrasing seen in the wild: "unable to
    # provide", "not be able to offer", "does not currently sponsor". The
    # first draft required the verb immediately after the negation and matched
    # none of them.
    r"(?:be\s+)?(?:able\s+)?(?:to\s+)?(?:currently\s+)?"
    r"(?:offer|provide|support|sponsor)[^.]{0,40}?(?:sponsor|visa)|"
    r"no\s+h-?1b|without\s+(?:visa\s+)?sponsorship|"
    r"not\s+require\s+(?:visa\s+)?sponsorship|"
    r"sponsorship\s+is\s+not\s+(?:available|offered|provided)",
    re.I)

# The trap this gate had to be built around. Equal-opportunity boilerplate sits
# at the bottom of a large share of postings and it is *made of* the words
# above — Stripe's reads "military and veteran status" and "protected by US
# federal, state or local laws". It is the opposite of an eligibility
# restriction: it is a promise not to restrict. A sentence carrying any of these
# cues is not read at all.
_EEO_CUES = re.compile(
    r"equal\s+(?:employment\s+)?opportunit|without\s+regard\s+to|regardless\s+of|"
    r"protected\s+(?:by|veteran|characteristic|class)|discriminat|"
    r"affirmative\s+action|all\s+qualified\s+applicants|"
    r"reasonable\s+accommodation|fair\s+chance",
    re.I)

_BLOCK_END = re.compile(r"</(?:li|p|div|h\d|tr|ul|ol)>|<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")

# The abbreviation that breaks sentence splitting in exactly the domain where
# it matters most. Collins Aerospace writes "The ability to obtain and maintain
# a U.S. government issued security clearance is required" — one sentence, and
# splitting on every period turned it into three, stranding "ability to obtain"
# away from the requirement it qualifies. The gate then read a job open to any
# US citizen as one demanding a clearance already in hand.
_US_ABBREV = re.compile(r"\bU\.\s?S\.(?:\s?A\.)?", re.I)
_ENTITIES = (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
             ("&quot;", '"'), ("&#39;", "'"), ("&rsquo;", "'"))


def _plain(text: str) -> str:
    """
    HTML down to sentences, because the JD arrives as markup.

    `full_jd` is whatever enrichment scraped, and for every ATS source that is
    HTML. Stripping tags to nothing would run adjacent list items together, and
    this gate reasons one sentence at a time: an "or eligibility to obtain one"
    three bullets below a hard requirement must not soften it. So block-level
    tags become sentence breaks rather than vanishing.
    """
    text = _BLOCK_END.sub(". ", text or "")
    text = _TAG.sub(" ", text)
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    text = _US_ABBREV.sub("US", text)
    return re.sub(r"\s+", " ", text)


def work_answer(profile, field: str) -> str:
    """
    One `work_authorization` answer: "yes", "no" or "unknown".

    The only reader of those answers, and it is where absence becomes
    unknown rather than no. `_is_us_person` read `us_citizen` with a default
    of False, so a profile that never said anything was confidently not a US
    person (A4). Anything that is not literally "yes" or "no" — a missing
    section, a missing field, a value this code does not recognise — is
    unknown here, never a guess in either direction.
    """
    auth = getattr(getattr(profile, "personal_info", None),
                   "work_authorization", None)
    value = auth.get(field) if isinstance(auth, dict) else getattr(auth, field, None)
    return value if value in ("yes", "no") else "unknown"


def posting_demands(text: str) -> dict:
    """
    What the posting demands of whoever holds it — about the *job*, not a person.

    Split out of `eligibility_disqualifiers` for the public board (R64), which
    has no visitor to judge against. A board that says "this role wants a
    clearance" is stating a fact about the posting; a board that says "you are
    not eligible" would need to know who is reading, and it does not.

    The detection is unchanged: sentence by sentence, skipping equal-opportunity
    boilerplate, and taking the weakest reading when one sentence states both an
    active-clearance requirement and an obtainable one. Only the judgement moved
    out.

    Returns three flags, all False for text that demands nothing. Whether the
    text was substantial enough to be worth reading is the caller's question —
    see `posting_facts.demands_basis`.
    """
    demands = {"clearance_held": False, "us_person": False,
               "no_sponsorship": False}
    if not text:
        return demands

    for sentence in re.split(r"[.;!?]\s+|\n", _plain(text)):
        if not sentence.strip() or _EEO_CUES.search(sentence):
            continue

        obtainable = _CLEARANCE_OBTAINABLE.search(sentence)
        if _CLEARANCE_HELD.search(sentence) and not obtainable:
            demands["clearance_held"] = True
        if obtainable:
            # Eligibility to obtain a clearance is US-person status and nothing
            # more, so it lands in the same bucket as ITAR rather than its own.
            demands["us_person"] = True
        if _US_PERSON_REQUIRED.search(sentence):
            demands["us_person"] = True
        if _NO_SPONSORSHIP.search(sentence):
            demands["no_sponsorship"] = True

    return demands


def _judge_demands(demands: dict, profile) -> tuple:
    """
    (ruled_out, unanswered) — what the posting demands, against the answers.

    Three-valued on purpose. A demand meets "yes" (passes), "no" (rules out)
    or "unknown" (neither — the reader has not said). Unknown-as-eligible is
    the prefer-not-to-say bug this replaced; unknown-as-ineligible empties the
    board for every new profile, since the template starts unknown.

    **One entailment, and only one:** a US person cannot need sponsorship, so
    `us_person == "yes"` satisfies a no-sponsorship posting even when
    `needs_sponsorship` is unanswered. That follows from an answer. The
    reverse does not hold — not needing sponsorship says nothing about
    citizenship (a TN or an H-4 EAD holder needs none) — and no further
    entailments are chained without a decision to do so.
    """
    clearance = work_answer(profile, "holds_clearance")
    us_person = work_answer(profile, "us_person")
    sponsorship = work_answer(profile, "needs_sponsorship")

    ruled_out, unanswered = [], []

    if demands["clearance_held"]:
        if clearance == "no":
            ruled_out.append(
                "requires a security clearance you already hold; this profile "
                "says it does not have one")
        elif clearance == "unknown":
            unanswered.append(
                "requires an active security clearance, and you have not said "
                "whether you hold one")

    if demands["us_person"]:
        if us_person == "no":
            ruled_out.append(
                "is restricted to US citizens or permanent residents "
                "(clearance, ITAR or export-control work)")
        elif us_person == "unknown":
            unanswered.append(
                "is restricted to US citizens or permanent residents, and you "
                "have not said whether you are one")

    if demands["no_sponsorship"] and us_person != "yes":
        if sponsorship == "yes":
            ruled_out.append(
                "states it does not sponsor visas, and this profile needs "
                "sponsorship")
        elif sponsorship == "unknown":
            unanswered.append(
                "states it does not sponsor visas, and you have not said "
                "whether you will need sponsorship")

    return ruled_out, unanswered


def eligibility_disqualifiers(text: str, profile) -> list:
    """
    Reasons the posting's stated eligibility rules this candidate out.

    Only the answers that settle it: a demand met by "unknown" is not a reason
    here, and not a pass either — `judge_body` reports it as undecidable.
    """
    if not text:
        return []
    return _judge_demands(posting_demands(text), profile)[0]


def _experience_disqualifiers(text: str, profile) -> list:
    """The R54 half: a years floor above the profile, or no early-career."""
    reasons = []

    floor = required_years(text)
    tolerated = _tolerated_years(profile)
    if floor is not None and floor > tolerated:
        reasons.append(
            f"asks for {floor}+ years of experience; this profile's range "
            f"tops out around {tolerated}")

    if excludes_entry_level(text):
        reasons.append("states that early-career applicants are not eligible")

    return reasons


def body_disqualifiers(text: str, profile) -> list:
    """
    Reasons this JD's body rules the profile out. Empty means *not ruled out*
    — which is not the same as eligible; see `judge_body`.

    Deterministic and offline by design: it runs on every enriched job, and a
    gate that cost an API call per posting would be a gate nobody could afford
    to leave on.
    """
    if not text:
        return []
    return _experience_disqualifiers(text, profile) + eligibility_disqualifiers(
        text, profile)


# ---------------------------------------------------------------------------
# The verdict (pilot A4)
#
# `gate_reason` returned "" or a reason, and "" meant two things: this
# posting was read and nothing rules you out, and nothing could be read at
# all. R61 made the pipeline keep postings whose scrape failed, and the gate
# waved every one of them through as eligible on a one-line snippet.
#
# So the verdict has three states and a discriminator rather than an
# overloaded empty string. Undecidable jobs are **shown, badged and counted**:
# never silently eligible, never silently hidden.
# ---------------------------------------------------------------------------

SHOWN, HIDDEN, UNDECIDABLE = "shown", "hidden", "undecidable"
VERDICTS = (SHOWN, HIDDEN, UNDECIDABLE)

UNREADABLE_REASON = ("its description could not be read, so its requirements "
                     "are unknown")


@dataclass(frozen=True)
class GateVerdict:
    """What the gates make of one posting for one profile."""
    state: str
    reason: str = ""


def judge_body(text: str, profile, *, readable=None) -> GateVerdict:
    """
    The body gate's verdict, shared by the pipeline and the board (Q39).

    `readable` is what the caller knows about the text's provenance: the
    pipeline passes `scraped_successfully`, the board has no such column and
    passes None, leaving length to decide via `posting_facts.demands_facet`.

    Precedence: anything that rules the profile out hides the job, even on a
    thin body — a snippet that says "8+ years" or "active TS/SCI" is the
    posting's own words. Otherwise a demand met by an unanswered question, or
    a body too thin to read, is undecidable. Otherwise shown.
    """
    # Imported here: posting_facts imports this module. `_gate_source` hashes
    # both files, so an edit to the readability rule re-judges the board too.
    from .posting_facts import demands_facet

    text = text or ""
    demands, basis = demands_facet(text)
    if basis == "unknown":
        # Too thin to trust as a whole, but what it does say, it says.
        demands = posting_demands(text)
    if readable is False:
        basis = "unknown"

    ruled_out, unanswered = _judge_demands(demands, profile)
    ruled_out = (_experience_disqualifiers(text, profile) if text else []) + ruled_out

    if ruled_out:
        return GateVerdict(HIDDEN, ruled_out[0])
    if unanswered:
        return GateVerdict(UNDECIDABLE, unanswered[0])
    if basis == "unknown":
        return GateVerdict(UNDECIDABLE, UNREADABLE_REASON)
    return GateVerdict(SHOWN)


# ---------------------------------------------------------------------------
# Where a posting is, against where the profile will work (Q55)
#
# Three answers, not two. A remote posting used to be accepted before either
# country list was consulted, and its country had already been thrown away by
# the parser, so "Argentina Remote" read as remote-and-acceptable for a
# US-only profile. The fix is not to flip that default: a posting that says
# only "Remote" has not said where it hires, and that is unknown, not no.
# ---------------------------------------------------------------------------

COUNTRY_IN, COUNTRY_OUT, COUNTRY_UNKNOWN = "in", "out", "unknown"

REMOTE_UNKNOWN_REASON = ("remote, but the posting does not say which "
                         "countries it hires in")


def country_decision(loc: LocationResult, preferred, excluded=()) -> tuple:
    """
    `(state, reason)` for a parsed location: in, out, or unknown.

    Shared by discovery's `evaluate` and the board's `gate_verdict`, so the two
    cannot read the same location differently. A posting naming several
    countries is in when any of them is acceptable: "US or Canada" is open to
    someone in the US.
    """
    named = list(loc.countries) or ([loc.country] if loc.country else [])
    if not named:
        return COUNTRY_UNKNOWN, ""

    excluded = list(excluded or [])
    open_to = [country for country in named if country not in excluded]
    if not open_to:
        return COUNTRY_OUT, f"Location country '{named[0]}' is excluded"

    preferred = list(preferred or [])
    if preferred and not any(country in preferred for country in open_to):
        return COUNTRY_OUT, (f"Location country '{' or '.join(open_to)}' "
                             f"not in preferred countries {preferred}")
    return COUNTRY_IN, ""


def evaluate(job, profile) -> FilterDecision:
    """
    Evaluate a job against a user profile.

    Args:
        job: JobListing object with title, description, location fields
        profile: UserProfile object with job_preferences

    Returns:
        FilterDecision with exclude flag, reason, and scores
    """
    decision = FilterDecision(exclude=False)

    # -----------------------------------------------------------------------
    # 1. Seniority / keyword filtering
    # -----------------------------------------------------------------------
    text = f"{job.title} {job.description}".lower()
    prefs = profile.job_preferences

    for keyword in prefs.exclude_keywords:
        if keyword.lower() in text:
            decision.exclude = True
            decision.reason = f"Excluded keyword: {keyword}"
            return decision

    has_senior = any(ind in text for ind in SENIOR_INDICATORS)
    accepted = accepted_seniority_terms(effective_seniority(profile))
    has_accepted = any(term in text for term in accepted)

    if has_senior and not has_accepted:
        decision.exclude = True
        decision.reason = (
            "Seniority above this profile's range "
            f"({', '.join(effective_seniority(profile)) or 'unset'})"
        )
        return decision

    if has_accepted:
        decision.seniority_score = 2
    elif not has_senior:
        decision.seniority_score = 1  # Unknown seniority — acceptable
    else:
        decision.seniority_score = 0  # Senior wording, but within range

    # -----------------------------------------------------------------------
    # 2. Role relevance scoring
    # -----------------------------------------------------------------------
    title_lower = job.title.lower()
    role_score = 0
    for target_role in prefs.target_roles:
        role_lower = target_role.lower()
        if role_lower in title_lower:
            # Exact match in title
            role_score = 3
            decision.reasons.append(f"Matches target role: {target_role}")
            break
        # Partial word match
        role_words = set(role_lower.split())
        title_words = set(title_lower.split())
        overlap = role_words & title_words
        if overlap and len(overlap) >= 1:
            role_score = max(role_score, 2)

    decision.role_score = role_score

    # -----------------------------------------------------------------------
    # 3. Location filtering and scoring
    # -----------------------------------------------------------------------
    loc_result = parse_location(job.location)
    decision.location_result = loc_result

    # Remote check. The posting's country is judged first, like any other
    # location's (Q55): a remote job in Argentina is in Argentina.
    if loc_result.is_remote:
        preferred_countries = prefs.locations.countries
        state, reason = country_decision(
            loc_result, preferred_countries,
            getattr(prefs.locations, "exclude_countries", None))
        if state == COUNTRY_OUT:
            decision.exclude = True
            decision.reason = reason
            return decision
        if state == COUNTRY_UNKNOWN and preferred_countries:
            # Kept, never ranked as a known match. The board badges it.
            decision.location_score = -1
            decision.reasons.append("Remote, country not stated")
        elif prefs.locations.remote_ok:
            decision.location_score = 3
            decision.reasons.append("Remote (accepted)")
        else:
            decision.location_score = 0
            decision.reasons.append("Remote (not preferred)")
        return decision

    # Unknown / vague location — keep but rank low
    if loc_result.confidence == "low" or loc_result.country is None:
        decision.location_score = -1
        decision.reasons.append(f"Location unclear: {job.location or '(empty)'}")
        return decision

    # Blacklist first — it is the narrower statement. A user who names no
    # preferred countries but rules one out has said something specific, and
    # the whitelist below would never reach it (R68).
    # Then the whitelist. Both through `country_decision`, the same judgement
    # the remote branch above and the board's gate make.
    state, reason = country_decision(
        loc_result, prefs.locations.countries,
        getattr(prefs.locations, "exclude_countries", None))
    if state == COUNTRY_OUT:
        decision.exclude = True
        decision.reason = reason
        return decision

    # Country matches — score by state preference
    location_score = _score_us_location(loc_result, prefs.locations)
    decision.location_score = location_score

    # Not willing to relocate: a gate, not a penalty (R68).
    #
    # A weighted location score is the wrong shape here and R55 is why — a
    # penalty gets outrun by vocabulary overlap, which is how a São Paulo
    # posting scored 54% while the profile asked for the United States. So
    # "somewhere I would have to move to" excludes rather than deducts.
    #
    # Guarded on the profile having named somewhere. A profile that lists no
    # cities and no priority states has expressed no preference, and gating on
    # it would empty the board — R55's lesson pointing the other way, where an
    # unknown country silently passed a filter built to catch it.
    # And only when the posting says *where*. `location_score == 0` covers two
    # different things — "in this country, in a state you did not name" and "in
    # this country, state unknown" — and a first run excluded three postings
    # listed only as "United States" on the second reading. Unknown is not
    # elsewhere; the same distinction R64 drew for years and R55 for countries.
    named_somewhere = bool(prefs.locations.cities or prefs.locations.states_priority)
    if (named_somewhere
            and not getattr(prefs.locations, "willing_to_relocate", True)
            and location_score == 0
            and loc_result.state):
        decision.exclude = True
        decision.reason = (
            f"{loc_result.state or loc_result.city or job.location} is outside "
            f"the places you named, and you are not willing to relocate"
        )
        return decision

    if location_score >= 3:
        decision.reasons.append(
            f"Priority location: {loc_result.state or loc_result.country}"
        )
    elif location_score >= 2:
        decision.reasons.append(
            f"Acceptable location: {loc_result.state or loc_result.country}"
        )
    else:
        decision.reasons.append(
            f"Other US location: {loc_result.state or loc_result.city or job.location}"
        )

    return decision


def _score_us_location(loc_result: LocationResult, location_prefs) -> int:
    """
    Score a US job location based on state preferences.

    Returns:
        3 = priority state
        2 = acceptable state
        0 = US but not in priority/acceptable
    """
    if not loc_result.state:
        return 0

    state_lower = loc_result.state.lower()

    for priority_state in location_prefs.states_priority:
        if priority_state.lower() == state_lower:
            return 3

    for acceptable_state in location_prefs.states_acceptable:
        if acceptable_state.lower() == state_lower:
            return 2

    return 0

# ---------------------------------------------------------------------------
# Keeping a stored verdict current (R62 / Q22)
#
# Every gate above runs between enrichment and analysis, which is right for a
# pipeline and wrong for a board. A pipeline is a pass over new work; a board
# accumulates. So a gate shipped on Tuesday never saw a job scored on Monday,
# and after R61's purge 26 of the 69 scored jobs in the store — 38%, holding
# the entire top of the board — were postings the gates as they stand would
# have removed.
#
# The verdict is therefore stored per row, and recomputed when it goes stale.
# What makes it stale is not a date: it is a change to the gate's own code, or
# a change to the parts of the profile the gate reads. Both are folded into one
# fingerprint.
#
# **Derived rather than declared, deliberately.** The obvious design is a
# `GATE_VERSION = 3` constant bumped by hand when a gate changes. This project
# has been bitten repeatedly by exactly that shape — a field written and never
# read (R31), a flag set by every path and consulted by none (R61) — and a
# version somebody must remember to bump is the same bug waiting to happen.
# Hashing the source means the only way to change a gate without invalidating
# the verdicts is to not change it. The cost is that editing a comment in this
# file re-runs the gate over the store, which is milliseconds.
# ---------------------------------------------------------------------------

# `judge_body` reads its readability rule from posting_facts, so that file is
# gate code too. A third file joining the gate belongs on this list, or an
# edit to it leaves every stored verdict judged under the old rule.
#
# location_matcher.py is on it since Q55: the country gate below reads
# `parse_location`, and a parser change that turns "Remote - Ireland" from
# no-country into Ireland has to re-judge every stored row.
_GATE_FILES = ("job_filter.py", "posting_facts.py", "location_matcher.py")


def _gate_source() -> str:
    """The gate's own text. Any edit to a gate changes it."""
    here = Path(__file__).parent
    try:
        return "\n".join((here / name).read_text(encoding="utf-8")
                         for name in _GATE_FILES)
    except OSError:  # pragma: no cover - only if the source is unreadable
        return __name__


def gate_fingerprint(profile) -> str:
    """
    A short hash of everything a stored verdict depends on.

    The profile half matters as much as the code half: R52 lets someone change
    their seniority range or preferred countries from the UI, and a verdict
    computed against the old answer is wrong the moment they do.
    """
    prefs = getattr(profile, "job_preferences", None)
    locations = getattr(prefs, "locations", None)

    relevant = json.dumps({
        "seniority": sorted(getattr(prefs, "seniority", None) or []),
        "years_experience": getattr(prefs, "years_experience", None),
        "exclude_keywords": sorted(getattr(prefs, "exclude_keywords", None) or []),
        "countries": sorted(getattr(locations, "countries", None) or []),
        "us_person": work_answer(profile, "us_person"),
        "needs_sponsorship": work_answer(profile, "needs_sponsorship"),
        "holds_clearance": work_answer(profile, "holds_clearance"),
    }, sort_keys=True)

    digest = hashlib.sha256()
    digest.update(_gate_source().encode("utf-8"))
    digest.update(relevant.encode("utf-8"))
    return digest.hexdigest()[:16]


def gate_verdict(row, profile) -> GateVerdict:
    """
    What the board should do with this stored job: shown, hidden, undecidable.

    Takes a store row rather than a `JobListing`, because this runs over what
    the board already holds rather than over what discovery just found. The
    body gate (R54, R56, A4) via `judge_body`, then the country gate (R55),
    which the pipeline's gate does not repeat because discovery applied it.

    A country that rules the job out hides it even when the body was
    undecidable: the location is a structured field, not the unread text.

    A remote posting that names no country is undecidable when the profile
    names countries (Q55): kept, badged and counted, never silently eligible.
    A body that is itself undecidable keeps its own reason.
    """
    body = judge_body(row.get("full_jd") or "", profile)
    if body.state == HIDDEN:
        return body

    preferred = getattr(
        getattr(getattr(profile, "job_preferences", None), "locations", None),
        "countries", None) or []
    if preferred:
        location = parse_location(row.get("location") or "")
        state, reason = country_decision(location, preferred)
        if state == COUNTRY_OUT:
            return GateVerdict(HIDDEN, reason)
        if (state == COUNTRY_UNKNOWN and location.is_remote
                and body.state == SHOWN):
            return GateVerdict(UNDECIDABLE, REMOTE_UNKNOWN_REASON)

    return body
