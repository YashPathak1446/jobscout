"""
Priya's top 10 on two embedding backends, side by side (pilot-plan A7).

    python compare_embeddings.py outputs/<date>/enriched_jobs.json

Each backend scores in its own process under its own throwaway JOBSCOUT_HOME:
the backend is a process-global in embedding_scorer, and the resume cache is
labelled gemini-embedding-001 whichever backend wrote it, so sharing either
would let one column contaminate the other. Scores every job, bypassing the
threshold of 40, so nothing is hidden. Prints only titles, companies and
numbers -- never the key, never an error message.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path.cwd()
RESUME = REPO / "data" / "master_resumes" / "priya_raghunathan.tex"
TOP = 10


def score(backend, enriched, out):
    sys.path.insert(0, str(REPO))
    errors = []

    class Count(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                errors.append(1)

    logging.getLogger().addHandler(Count())
    logging.getLogger().setLevel(logging.WARNING)

    from tools.resume import embedding_scorer as es
    es.EMBEDDING_BACKEND = backend
    es._BACKEND = None
    name, model, dims = es.active_backend()
    if name != backend:
        sys.exit(f"asked for {backend}, resolved {name}")

    from tools.resume.resume_parser import ResumeParser
    parser = ResumeParser(str(RESUME), user_id=None)
    if parser.using_mock_embeddings:
        sys.exit(f"{backend}: resume embeddings fell back to MOCK -- not a measurement")

    data = json.loads(Path(enriched).read_text(encoding="utf-8"))
    jobs = data["enriched_jobs"] if isinstance(data, dict) else data
    rows = []
    for i, job in enumerate(jobs):
        jd = job.get("full_jd") or job.get("short_description") or ""
        s = parser.score_job(jd, job_id=job.get("id", f"job_{i}"),
                             title=job.get("title", "?"), company=job.get("company", "?"))
        rows.append({
            "key": job.get("url") or job.get("id") or f"job_{i}",
            "label": f"{job.get('company', '?')} -- {job.get('title', '?')}",
            "readable": job.get("scraped_successfully", True) is not False,
            "overall": s.overall_score if s else None,
            "emb": s.embedding_score if s else None,
            "kw": s.keyword_score if s else None,
        })
    Path(out).write_text(json.dumps({"backend": name, "model": model, "dims": dims,
                                     "errors": len(errors), "rows": rows}),
                         encoding="utf-8")


def ranks(rows, field):
    scored = sorted((r for r in rows if r[field] is not None),
                    key=lambda r: -r[field])
    return {r["key"]: i + 1 for i, r in enumerate(scored)}, scored


def spearman(a, b):
    common = [k for k in a if k in b]
    n = len(common)
    if n < 3:
        return float("nan"), n
    # re-rank within the common set so both sides are 1..n
    ra = {k: i + 1 for i, k in enumerate(sorted(common, key=a.get))}
    rb = {k: i + 1 for i, k in enumerate(sorted(common, key=b.get))}
    d2 = sum((ra[k] - rb[k]) ** 2 for k in common)
    return 1 - 6 * d2 / (n * (n * n - 1)), n


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # R81
    enriched = str(Path(sys.argv[1]).resolve())
    sys.path.insert(0, str(REPO))
    from config import resolve_api_key
    if not resolve_api_key():
        sys.exit("No GOOGLE_API_KEY: the gemini column would not be Gemini.")

    results = {}
    with tempfile.TemporaryDirectory() as scratch:
        for backend in ("local", "gemini"):
            home = Path(scratch) / backend
            home.mkdir()
            out = Path(scratch) / f"{backend}.json"
            env = {**os.environ, "JOBSCOUT_HOME": str(home), "PYTHONIOENCODING": "utf-8"}
            subprocess.run([sys.executable, __file__, "--score", backend, enriched, str(out)],
                           env=env, cwd=REPO, check=True)
            results[backend] = json.loads(out.read_text(encoding="utf-8"))

    L, G = results["local"], results["gemini"]
    for r in (L, G):
        missing = sum(1 for row in r["rows"] if row["overall"] is None)
        print(f"{r['backend']:6} {r['model']} ({r['dims']}d): {len(r['rows'])} jobs, "
              f"{missing} unscored, {r['errors']} logged errors")
    print()

    lr, ltop = ranks(L["rows"], "overall")
    gr, gtop = ranks(G["rows"], "overall")
    print(f"{'#':>2}  {'LOCAL (potion)':<52} {'sc':>5} {'G#':>3}   "
          f"{'GEMINI':<52} {'sc':>5} {'L#':>3}")
    for i in range(TOP):
        def cell(top, other):
            if i >= len(top):
                return f"{'':<52} {'':>5} {'':>3}"
            r = top[i]
            mark = "" if r["readable"] else " [unreadable]"
            return (f"{(r['label'] + mark)[:52]:<52} {r['overall']:>5.1f} "
                    f"{other.get(r['key'], '-'):>3}")
        print(f"{i + 1:>2}  {cell(ltop, gr)}   {cell(gtop, lr)}")

    overlap = len({r["key"] for r in ltop[:TOP]} & {r["key"] for r in gtop[:TOP]})
    rho, n = spearman(lr, gr)
    le, _ = ranks(L["rows"], "emb")
    ge, _ = ranks(G["rows"], "emb")
    rho_emb, _ = spearman(le, ge)
    print()
    print(f"top-{TOP} overlap: {overlap}/{TOP}")
    print(f"Spearman rho, overall score:        {rho:.2f}  (n={n})")
    print(f"Spearman rho, embedding half only:  {rho_emb:.2f}  "
          "(the 30% keyword half is identical on both, so this isolates the model)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--score":
        score(*sys.argv[2:5])
    else:
        main()