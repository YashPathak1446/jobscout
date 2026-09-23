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

**Fitting the local window (R99).** R36's window had no artifact, so nobody
could re-derive it (R98). This fits its replacement and records how:

    # 1. one dump per profile, each under whatever JOBSCOUT_HOME holds it
    python scripts/calibration_probe.py --input <abs>/enriched_jobs.json \
        --profile priya_raghunathan --dump dumps/priya.json
    # 2. pool them: the window, leave-one-profile-out, and the record
    python scripts/calibration_probe.py fit dumps/*.json \
        --write baselines/calibration/local-window.json
    # 3. the blind comparison sheets, and the jobs the threshold would drop
    python scripts/calibration_probe.py ab dumps/*.json \
        --record baselines/calibration/local-window.json --out ab/

A dump holds job labels and numbers only, never resume text, so a private
resume's dump says nothing about the resume.
"""

import argparse
import hashlib
import json
import random
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


# --- Fitting (R99) ------------------------------------------------------------
#
# Decided before any fit was run, so no number below was chosen by looking at
# the result it produces.

# The window spans the pooled observed range plus this share of it at each end:
# headroom for a resume slightly outside what was measured, while the measured
# range still uses ~83% of the scale.
MARGIN = 0.10

# A fit is recorded only from at least this many profiles (the author's
# condition: three he has, plus one real resume nobody here wrote).
MIN_PROFILES = 4

# Leave-one-profile-out: a window fit on the others may clip at most this share
# of the held-out profile's jobs. Failing it means a new resume would not fit,
# which is the event the guard exists to report — so the fit is not shipped.
LOO_MAX_CLIPPED = 0.10

# What every board on potion has shown until now: R36's void window (R98).
# Named rather than read from CALIBRATION, so the comparison still means
# "against today's boards" after the window is replaced.
TODAY_WINDOW = (0.00, 0.10)

# The blend, restated from embedding_scorer so the comparison is computed the
# way production computes it. Imported, not copied.
def _overall(raw, hits, floor, ceiling):
    from tools.resume.embedding_scorer import KEYWORD_SATURATION, KEYWORD_WEIGHT

    emb = max(0.0, min(100.0, (raw - floor) / (ceiling - floor) * 100))
    kw = min(hits / KEYWORD_SATURATION, 1.0) * 100
    return round(emb * (1 - KEYWORD_WEIGHT) + kw * KEYWORD_WEIGHT, 1)


def write_dump(path, profile, backend_info, input_file, rows) -> None:
    name, model, dims = backend_info
    data = Path(input_file).read_bytes()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({
        "profile": profile,
        "backend": name, "model": model, "dims": dims,
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "rows": [{"label": r["label"], "raw": r["raw"], "hits": r["hits"]}
                 for r in rows],
    }, indent=1), encoding="utf-8")


def load_dumps(paths) -> list:
    dumps = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    for path, d in zip(paths, dumps):
        if not {"profile", "rows", "model", "input_sha256"} <= set(d):
            sys.exit(f"{path} is not a dump from `--dump` (a fit record in the glob?)")
    for key in ("model", "input_sha256"):
        seen = {d[key] for d in dumps}
        if len(seen) > 1:
            sys.exit(f"dumps disagree on {key} ({sorted(seen)}): a window fit "
                     f"across different models or job sets measures the difference")
    names = [d["profile"] for d in dumps]
    if len(set(names)) != len(names):
        sys.exit(f"a profile appears twice: {names}")
    return dumps


def _raws(dump) -> list:
    return [r["raw"] for r in dump["rows"] if r["raw"] is not None]


def fit_window(raws) -> tuple:
    lo, hi = min(raws), max(raws)
    pad = (hi - lo) * MARGIN
    return round(lo - pad, 4), round(hi + pad, 4)


def clipped_share(raws, floor, ceiling) -> float:
    return sum(1 for r in raws if r <= floor or r >= ceiling) / len(raws)


def fit(dumps) -> dict:
    """The window over every dump, and each profile held out against the rest."""
    pooled = [r for d in dumps for r in _raws(d)]
    floor, ceiling = fit_window(pooled)

    profiles = []
    for d in dumps:
        raws = _raws(d)
        others = [r for o in dumps if o is not d for r in _raws(o)]
        f, c = fit_window(others)
        held_out = clipped_share(raws, f, c)
        profiles.append({
            "profile": d["profile"],
            "n": len(raws),
            "min": round(min(raws), 4), "max": round(max(raws), 4),
            "median": round(statistics.median(raws), 4),
            # How much of the 0-100 scale this profile's jobs span: the
            # embedding's pull against keywords on that board.
            "scale_used": round((max(raws) - min(raws)) / (ceiling - floor), 3),
            "loo_window": [f, c],
            "loo_clipped": round(held_out, 3),
            "loo_pass": held_out <= LOO_MAX_CLIPPED,
        })

    return {
        "rule": {"margin": MARGIN, "min_profiles": MIN_PROFILES,
                 "loo_max_clipped": LOO_MAX_CLIPPED},
        "backend": dumps[0]["backend"], "model": dumps[0]["model"],
        "input_sha256": dumps[0]["input_sha256"],
        "pooled": {"n": len(pooled), "min": round(min(pooled), 4),
                   "max": round(max(pooled), 4)},
        "window": [floor, ceiling],
        "profiles": profiles,
        "enough_profiles": len(dumps) >= MIN_PROFILES,
        "loo_pass": all(p["loo_pass"] for p in profiles),
    }


def print_fit(record) -> None:
    floor, ceiling = record["window"]
    _print(f"model     {record['model']}   jobs sha256 {record['input_sha256'][:12]}")
    _print(f"pooled    {record['pooled']['n']} raw values, "
           f"{record['pooled']['min']:.4f} - {record['pooled']['max']:.4f}")
    _print(f"window    {floor:.4f} - {ceiling:.4f}   (margin {MARGIN:.0%} of the range each side)")
    _print()
    _print(f"{'profile':<22} {'n':>3} {'min':>7} {'median':>7} {'max':>7} "
           f"{'scale':>6}   held out: window fit on the others -> clipped")
    for p in record["profiles"]:
        verdict = "pass" if p["loo_pass"] else "FAIL"
        _print(f"{p['profile'][:22]:<22} {p['n']:>3} {p['min']:>7.4f} {p['median']:>7.4f} "
               f"{p['max']:>7.4f} {p['scale_used']:>6.0%}   "
               f"{p['loo_window'][0]:.4f}-{p['loo_window'][1]:.4f} -> "
               f"{p['loo_clipped']:.0%} {verdict}")
    _print()
    if not record["enough_profiles"]:
        _print(f"NOT A FIT: {len(record['profiles'])} profiles, the rule needs "
               f"{MIN_PROFILES}. Printed for inspection; nothing is written.")
    elif not record["loo_pass"]:
        _print(f"NOT SHIPPABLE: a held-out profile clipped more than "
               f"{LOO_MAX_CLIPPED:.0%}. A new resume would not fit this window.")
    else:
        _print("Every held-out profile fits. The window may be proposed.")


def blind_sheets(dumps, record, seed=None) -> tuple:
    """
    Per profile, today's board order and the fitted window's, unlabelled.

    Returns (sheet_text, key, drops). Scores are left off the sheet: today's
    ties at 77.5 would say which list is which. Ties keep input order, which is
    discovery order, as the board's own tiebreak is not in a dump.
    """
    rng = random.Random(seed)
    old = TODAY_WINDOW
    new = tuple(record["window"])

    sheet, key, drops = [], {}, {}
    for d in dumps:
        rows = [r for r in d["rows"] if r["raw"] is not None]

        def top(window):
            ranked = sorted(enumerate(rows), key=lambda t: (
                -_overall(t[1]["raw"], t[1]["hits"], *window), t[0]))
            return [r["label"] for _, r in ranked[:10]]

        today, fitted = top(old), top(new)
        first_is_today = rng.random() < 0.5
        lists = (today, fitted) if first_is_today else (fitted, today)
        key[d["profile"]] = {"List 1": "today" if first_is_today else "fitted",
                             "List 2": "fitted" if first_is_today else "today",
                             "identical": today == fitted}

        sheet.append(f"== {d['profile']}")
        for name, labels in zip(("List 1", "List 2"), lists):
            sheet.append(f"  {name}")
            sheet.extend(f"    {i:>2}. {label}" for i, label in enumerate(labels, 1))
        sheet.append("  Which list would you rather apply from?  1 / 2 / tie")
        sheet.append("")

        drops[d["profile"]] = [
            r["label"] for r in rows
            if _overall(r["raw"], r["hits"], *old) >= 40 > _overall(r["raw"], r["hits"], *new)
        ]
    return "\n".join(sheet), key, drops


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "fit":
        return main_fit(argv[1:])
    if argv and argv[0] == "ab":
        return main_ab(argv[1:])

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", required=True,
                        help="enriched_jobs.json from a run, as --input takes it")
    parser.add_argument("--profile", default="priya_raghunathan")
    parser.add_argument("--backend", choices=("local", "gemini"), default="local")
    parser.add_argument("--dump", help="also write this profile's rows for `fit`")
    parser.add_argument("--json", action="store_true",
                        help="print the summary as JSON after the report")
    args = parser.parse_args(argv)

    rows, info, embedding_report = score_corpus(args.profile, args.input, args.backend)
    summary = report(rows, info, embedding_report)
    if args.dump:
        write_dump(args.dump, args.profile, info, args.input, rows)
        _print(f"\ndump written: {args.dump}")
    if args.json:
        _print(json.dumps(summary, indent=2))
    return 0


def main_fit(argv) -> int:
    parser = argparse.ArgumentParser(prog="calibration_probe.py fit")
    parser.add_argument("dumps", nargs="+")
    parser.add_argument("--write", help="record the fit here (refused unless it passes)")
    args = parser.parse_args(argv)

    record = fit(load_dumps(args.dumps))
    print_fit(record)
    if args.write:
        if not (record["enough_profiles"] and record["loo_pass"]):
            _print(f"\nnot written: {args.write}")
            return 1
        Path(args.write).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        _print(f"\nrecorded: {args.write}")
    return 0 if record["loo_pass"] else 1


def main_ab(argv) -> int:
    parser = argparse.ArgumentParser(prog="calibration_probe.py ab")
    parser.add_argument("dumps", nargs="+")
    parser.add_argument("--record", required=True, help="the fit record from `fit --write`")
    parser.add_argument("--out", required=True, help="directory for the three files")
    args = parser.parse_args(argv)

    if not Path(args.record).is_file():
        sys.exit(f"no fit record at {args.record}: `fit --write` records one only "
                 f"when it passes, so there is no window to compare yet")
    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    dumps = load_dumps(args.dumps)
    if dumps[0]["input_sha256"] != record["input_sha256"]:
        sys.exit("these dumps are not the jobs the window was fit on")

    sheet, key, drops = blind_sheets(dumps, record)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "1-sheet.txt").write_text(sheet + "\n", encoding="utf-8")
    (out / "2-key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    (out / "3-threshold-drops.json").write_text(json.dumps(drops, indent=2) + "\n",
                                                encoding="utf-8")
    _print(f"read {out / '1-sheet.txt'} and record a verdict per profile before")
    _print(f"opening {out / '2-key.json'}. {out / '3-threshold-drops.json'} lists the")
    _print("jobs a threshold of 40 would newly drop; label those fit / not a fit after.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
