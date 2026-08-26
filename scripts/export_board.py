"""
Write the public board's data as static JSON.

The board is the half of JobScout with no auth, no key and no personal data in
it (R60), and this is the seam: the store is personal and this export is not.
What crosses the line is what a posting says about itself — the role, the
employer, where it is, how much experience it asks for — plus a link back to
the original.

**What does not cross, and why it matters more than what does:**

  full_jd       the employer's own prose. R60's redistribution answer is that
                the board links out rather than mirroring, because the JD text
                is the employer's copyright and no ATS could license it away.
  score         computed against one person's resume; meaningless to a reader
  selection     which of that person's projects a resume used
  status        what that person decided about a job
  resume_tex    paths on that person's disk
  resume_pdf
  gate_reason   whether the job rules *that* person out

`FORBIDDEN_FIELDS` is checked at export time rather than trusted, because the
list that matters is the one nothing enforces.

    python scripts/export_board.py --dry-run
    python scripts/export_board.py --out data/board/jobs.json

Location: jobscout_v3/scripts/export_board.py
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "data" / "board" / "jobs.json"

# Belt and braces. `build_row` emits an allow-list, so none of these can appear
# by construction — but "by construction" is exactly what was true of
# `scraped_successfully` before R61, so it is asserted rather than assumed.
FORBIDDEN_FIELDS = (
    "full_jd", "score", "selection", "status", "scored_at",
    "resume_tex", "resume_pdf", "gate_reason", "gate_checked",
)


def build_payload(rows) -> dict:
    from tools.jobs.board_export import (
        DEFAULT_PRESET,
        SCHEMA_VERSION,
        build_rows,
        summarise_facets,
    )

    jobs = build_rows(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "default_preset": DEFAULT_PRESET,
        "facet_summary": summarise_facets(jobs),
        "jobs": jobs,
    }


def check_no_personal_data(payload: dict) -> list:
    """Field names that must not be here. Empty means clean."""
    leaked = set()
    for job in payload.get("jobs") or []:
        leaked |= {field for field in FORBIDDEN_FIELDS if field in job}
    return sorted(leaked)


def _report(payload: dict) -> None:
    summary = payload["facet_summary"]
    print(f"Jobs exported            : {summary['total']}")
    print(f"Schema version           : {payload['schema_version']}")
    print()
    print("How much each facet knows")
    print(f"  years basis            : {summary['years_basis']}")
    print(f"  years stated           : {summary['years_distribution']}")
    print(f"  demands basis          : {summary['demands_basis']}")
    print(f"  demands                : {summary['demands']}")
    print(f"  excludes entry level   : {summary['excludes_entry_level']}")
    print(f"  level                  : {summary['level']}")
    print(f"  country known          : {summary['with_country']} / {summary['total']}")
    print(f"  state known            : {summary['with_state']} / {summary['total']}")
    print(f"  remote                 : {summary['remote']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the public board data.")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help=f"where to write (default: {DEFAULT_OUT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the facet summary and write nothing")
    args = parser.parse_args()

    from agents.orchestrator import board_export_rows

    rows = board_export_rows()
    if not rows:
        print("No jobs in the store. Run the pipeline first.")
        return 1

    payload = build_payload(rows)

    leaked = check_no_personal_data(payload)
    if leaked:
        print(f"REFUSING TO WRITE — personal fields in the payload: {leaked}",
              file=sys.stderr)
        return 2

    _report(payload)

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
