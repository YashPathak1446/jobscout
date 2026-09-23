"""
Where a profile's raw similarities sit against the scale's ceiling (Q51).

`embedding_scorer._normalise` maps the raw blended cosine onto 0-100 with a
per-backend window, and **clips** everything above its top. The local window
is `(0.00, 0.10)`, fit on the frozen 20-JD baseline against the author's own
new-grad resume, where raw ran about 0.00-0.08. Priya's potion top 10 had
seven jobs tied at exactly 77.5, which is 0.7 x 100 + 0.3 x 25 — the
embedding half pinned at the ceiling. For every job pinned there, the
embedding contributes a constant, so the order among them is keyword count
alone.

This prints the distribution so that can be read as a number rather than
inferred from ties:

    python scripts/calibration_probe.py --input outputs/<date>/enriched_jobs.json
    python scripts/calibration_probe.py --input ... --profile priya_raghunathan --backend local

**It measures; it does not refit.** Moving `CALIBRATION` moves the meaning of
`scoring_threshold` with it (R24's shape), so a refit is its own decision,
made from this output and recorded as an R.

One backend per process, chosen before the first embedding: the scorer
resolves its backend once per process, so a single invocation can never mix
two. The run's resume cache is keyed by the model that wrote it (R97), so the
probe shares caches with real runs safely.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The raw range each window was fit on, as `embedding_scorer`'s CALIBRATION
# comment records it. Printed beside the measurement so the reader compares
# against the fit, not only against the clip.
FIT_ON = {
    # Void (R98): not a potion measurement; kept to print what was believed.
    "local": ((0.00, 0.08), "R36's recorded fit, void (R98)"),
    "gemini": ((0.30, 0.90), "the original Gemini calibration"),
}


def _print(text: str = "") -> None:
    # R81: a harness that dies printing its finding reports nothing.
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")


def summarise(rows: list, floor: float, span: float) -> dict:
    """
    The distribution of `raw` over the scored rows, against `(floor, span)`.

    `rows` are dicts with `raw`, `embedding`, `overall`, `hits`, and `raw`
    None for a job that could not be scored — counted, never averaged in.
    """
    scored = [r for r in rows if r["raw"] is not None]
    raws = sorted(r["raw"] for r in scored)
    ceiling = floor + span
    out = {
        "jobs": len(rows),
        "scored": len(scored),
        "unscored": len(rows) - len(scored),
        "floor": floor,
        "ceiling": ceiling,
    }
    if not raws:
        return out

    q1, median, q3 = (statistics.quantiles(raws, n=4, method="inclusive")
                      if len(raws) > 1 else (raws[0],) * 3)
    at_ceiling = [r for r in scored if r["raw"] >= ceiling]
    at_floor = [r for r in scored if r["raw"] <= floor]
    top = sorted(scored, key=lambda r: -r["overall"])[:10]
    out.update({
        "min": raws[0], "q1": q1, "median": median, "q3": q3, "max": raws[-1],
        "at_ceiling": len(at_ceiling),
        "at_floor": len(at_floor),
        "share_at_ceiling": len(at_ceiling) / len(scored),
        "top10_at_ceiling": sum(1 for r in top if r["raw"] >= ceiling),
        "top10_distinct_scores": len({r["overall"] for r in top}),
    })
    return out


def score_corpus(profile_name: str, input_file: str, backend: str) -> tuple:
    """Score every job in `input_file` — no threshold — on `backend`."""
    import tools.resume.embedding_scorer as scorer

    # Before anything embeds: the scorer memoises its backend per process.
    scorer.EMBEDDING_BACKEND = backend
    scorer._BACKEND = None
    name, model, dims = scorer.active_backend()
    if name != backend:
        sys.exit(f"asked for {backend}, the scorer resolved {name}")

    from agents.orchestrator import master_resume_path
    from tools.profile.profile_loader import load_profile
    from tools.resume.resume_parser import ResumeParser

    profile = load_profile(profile_name, user_id=None)
    resume = master_resume_path(None, profile.resume_preferences.master_resume_path)
    parser = ResumeParser(resume, user_id=None)
    if parser.using_mock_embeddings:
        sys.exit("The resume could not be embedded, so scoring fell back to mock "
                 "vectors. That is not a measurement. "
                 + scorer.describe_report(scorer.summarise_report(parser.embedding_report)))

    data = json.loads(Path(input_file).read_text(encoding="utf-8"))
    jobs = data["enriched_jobs"] if isinstance(data, dict) else data

    rows = []
    for i, job in enumerate(jobs):
        jd = job.get("full_jd") or job.get("short_description") or ""
        s = parser.score_job(jd, job_id=job.get("id", f"job_{i}"),
                             title=job.get("title", "?"), company=job.get("company", "?"))
        rows.append({
            "label": f"{job.get('company', '?')} - {job.get('title', '?')}",
            "raw": s.raw_similarity if s else None,
            "embedding": s.embedding_score if s else None,
            "overall": s.overall_score if s else None,
            "hits": len(s.keyword_hits) if s else None,
        })
    return rows, (name, model, dims), parser.embedding_report


def report(rows, backend_info, embedding_report) -> dict:
    import tools.resume.embedding_scorer as scorer

    name, model, dims = backend_info
    floor, span = scorer.CALIBRATION.get(name, scorer.CALIBRATION["gemini"])
    s = summarise(rows, floor, span)
    (fit_lo, fit_hi), fit_source = FIT_ON.get(name, ((None, None), "unknown"))

    _print(f"backend   {name}  {model} ({dims}d)")
    _print(f"jobs      {s['jobs']} in the input, {s['scored']} scored, "
           f"{s['unscored']} not scored")
    if embedding_report:
        _print("          " + scorer.describe_report(scorer.summarise_report(embedding_report)))
    _print()
    _print(f"window    raw {floor:.2f} -> 0,  raw {s['ceiling']:.2f} -> 100 (clipped above)")
    _print(f"fit on    raw {fit_lo:.2f} - {fit_hi:.2f}  ({fit_source})")
    if "min" not in s:
        _print("\nnothing scored; no distribution to report")
        return s

    _print()
    _print("raw similarity of this profile against this corpus")
    for key in ("min", "q1", "median", "q3", "max"):
        _print(f"  {key:<7} {s[key]:.4f}")
    _print()
    _print(f"at or above the ceiling  {s['at_ceiling']} of {s['scored']} "
           f"({s['share_at_ceiling']:.0%}) -- embedding half pinned at 100; "
           f"their order is keyword count alone")
    _print(f"at or below the floor    {s['at_floor']} of {s['scored']}")
    _print(f"top 10                   {s['top10_at_ceiling']} at the ceiling, "
           f"{s['top10_distinct_scores']} distinct overall scores")
    _print()
    _print(f"{'raw':>8} {'emb':>6} {'hits':>4} {'overall':>7}  job (top 10 by overall)")
    for r in sorted((r for r in rows if r["raw"] is not None),
                    key=lambda r: -r["overall"])[:10]:
        _print(f"{r['raw']:>8.4f} {r['embedding']:>6.1f} {r['hits']:>4} "
               f"{r['overall']:>7.1f}  {r['label'][:60]}")
    return s


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", required=True,
                        help="enriched_jobs.json from a run, as --input takes it")
    parser.add_argument("--profile", default="priya_raghunathan")
    parser.add_argument("--backend", choices=("local", "gemini"), default="local")
    parser.add_argument("--json", action="store_true",
                        help="print the summary as JSON after the report")
    args = parser.parse_args(argv)

    rows, info, embedding_report = score_corpus(args.profile, args.input, args.backend)
    summary = report(rows, info, embedding_report)
    if args.json:
        _print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
