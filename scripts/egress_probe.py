"""
Do the ATS boards answer a datacenter IP the way they answer a home one?

Stage A0 of the friends pilot. If Greenhouse, Lever or Ashby block Fly's
egress ranges, hosting there is in question, and everything built before
finding out was built on sand.

**Why this needs status codes and not counts.** `ats_search._fetch` returns
`None` for a 403, a 429, a 404 and a Cloudflare challenge served as HTML with
status 200 — four different facts flattened into one. Every reader turns that
`None` into `[]`, and `search_ats` then counts it as `failed` alongside a board
that simply has no open roles. Nothing raises, so Sentry sees nothing. From a
datacenter IP a block is therefore indistinguishable from an empty board, and
the run reports "0 discovered" with no way to say why (Q32).

**This deliberately does not call `_fetch`.** A probe built on the function
whose lossiness it exists to measure measures nothing — it would report `None`
for every interesting case, which is the bug. It re-derives the URLs from
`ats_search`'s board list so the templates cannot drift apart silently
(`test_egress_probe.py` fails if they do), then does its own `urlopen` and
keeps the status line, the content type, the body size and whether a 200
actually parsed as JSON.

**Run it twice and diff.** A single leg proves nothing: a 403 from Fly is only
evidence if the same slug answers 200 from a home connection in the same hour,
because these boards also 404 for companies that left the ATS and rate-limit
by volume rather than by origin.

    python scripts/egress_probe.py --label home --out probe-home.json
    # ...then, on a Fly machine:
    python scripts/egress_probe.py --label fly-ord --out probe-fly.json
    python scripts/egress_probe.py --compare probe-home.json probe-fly.json

Sampling: `--sample N` takes N slugs per board, seeded, so both legs hit the
same slugs. The default is every slug, which is ~98 requests.

Location: jobscout/scripts/egress_probe.py
"""

import argparse
import json
import random
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.search.ats_search import (  # noqa: E402
    TIMEOUT_SECONDS,
    USER_AGENT,
    load_companies,
)

# The listing URL each board reader fetches, kept here as the one place this
# script knows about the network. These mirror `_greenhouse`, `_lever`,
# `_ashby`, `_workable` and `_smartrecruiters`. Probing a URL the pipeline no
# longer uses would measure the wrong network, so a test asserts each template
# still appears in `ats_search.py` verbatim.
BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{slug}"
                        "/postings?limit=100"),
}

# Codes that mean "this origin is not welcome" rather than "this board is
# empty or gone". A 404 is the normal signal that a company left the ATS and
# says nothing about the IP; a 403/429/503 is the signal A0 exists to find.
BLOCKING_CODES = {401, 403, 405, 429, 451, 502, 503}

# A challenge page is the case that looks like success. Cloudflare and friends
# answer 200 with HTML, `json.loads` raises ValueError, and `_fetch` swallows
# it as `None` — identical to an empty board from every caller's point of view.
CHALLENGE_MARKERS = ("cf-mitigated", "cf-chl", "just a moment", "captcha",
                     "attention required", "access denied", "enable javascript")


def _console_print(*args, **kwargs) -> None:
    """
    print(), but a console that cannot encode a character loses the character
    rather than the run.

    Copied from `agents.orchestrator` rather than imported: a probe meant to
    run inside a throwaway container should not drag the orchestrator's import
    graph — the agents, the model clients, numpy — in behind it. R81 is why
    this exists at all. A measurement tool that dies while printing its first
    real finding reports success on exactly the cases it cannot render, and
    those correlate with the interesting ones.
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        cleaned = [str(a).encode(encoding, errors="replace").decode(encoding)
                   for a in args]
        print(*cleaned, **kwargs)


def probe_one(url: str, timeout: int = TIMEOUT_SECONDS) -> dict:
    """
    One GET, reported as what actually happened.

    Every field here exists because `_fetch` throws it away. `status` is the
    point; `json_ok` separates a real 200 from a challenge page wearing one;
    `body_bytes` distinguishes an empty board from a truncated response;
    `server` and `cf_ray` identify an edge network deciding about the origin
    rather than the account.

    Never raises. An exception is a result — a probe that stops at the first
    refused connection tells you about one slug.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    started = time.monotonic()
    result = {
        "url": url, "status": None, "error": None, "error_kind": None,
        "json_ok": None, "records": None, "body_bytes": None,
        "content_type": None, "server": None, "cf_ray": None,
        "challenge": False, "seconds": None,
    }

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result["status"] = response.status
            _record_body(result, response.headers, response.read())
    except urllib.error.HTTPError as exc:
        # An HTTPError carries the status and usually a body. Both matter: a
        # 403 whose body names Cloudflare is a different conversation with the
        # vendor than a 403 from the API itself.
        result["status"] = exc.code
        result["error_kind"] = "http"
        result["error"] = str(exc.reason)
        try:
            _record_body(result, exc.headers, exc.read())
        except Exception:
            pass
    except urllib.error.URLError as exc:
        # DNS and TLS failures have no status at all, and a datacenter egress
        # problem can present as either. Unknown is never a value (R64/R69):
        # this is recorded as a missing status, not as a zero.
        reason = exc.reason
        result["error_kind"] = ("dns" if isinstance(reason, socket.gaierror)
                                else "tls" if isinstance(reason, ssl.SSLError)
                                else "timeout" if isinstance(reason, socket.timeout)
                                else "network")
        result["error"] = str(reason)
    except (socket.timeout, TimeoutError) as exc:
        result["error_kind"] = "timeout"
        result["error"] = str(exc) or "timed out"
    except Exception as exc:  # pragma: no cover - the unclassified case
        result["error_kind"] = type(exc).__name__
        result["error"] = str(exc)

    result["seconds"] = round(time.monotonic() - started, 2)
    return result


def _record_body(result: dict, headers, body: bytes) -> None:
    """Fill in what the response body says about itself."""
    result["body_bytes"] = len(body)
    result["content_type"] = (headers.get("Content-Type") or "").split(";")[0].strip()
    result["server"] = headers.get("Server")
    result["cf_ray"] = headers.get("CF-Ray")

    text = body.decode("utf-8", errors="replace")
    lowered = text[:4000].lower()
    header_blob = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
    result["challenge"] = any(marker in lowered or marker in header_blob
                              for marker in CHALLENGE_MARKERS)

    try:
        payload = json.loads(text)
    except ValueError:
        result["json_ok"] = False
        return
    result["json_ok"] = True
    # Rough record count, per board shape. Only used to notice a 200 that
    # parses but is empty on one leg and full on the other.
    if isinstance(payload, list):
        result["records"] = len(payload)
    elif isinstance(payload, dict):
        for key in ("jobs", "content", "postings", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                result["records"] = len(value)
                break


def verdict(result: dict) -> str:
    """
    The one-word reading of a probe. This is the vocabulary A0 needed and
    `_fetch` cannot express: `None` collapses `blocked`, `absent`,
    `challenged` and `unreachable` into each other.
    """
    if result["challenge"]:
        return "challenged"
    status = result["status"]
    if status is None:
        return "unreachable"
    if status == 404:
        return "absent"
    if status in BLOCKING_CODES:
        return "blocked"
    if 200 <= status < 300:
        return "ok" if result["json_ok"] else "unparseable"
    return "other"


# Verdicts that mean the board answered usefully. Named rather than inlined
# because `compare` and `report` must agree about it.
FRIENDLY = {"ok", "absent"}
HOSTILE = {"blocked", "challenged", "unreachable", "unparseable"}


def select_slugs(companies: dict, sample: Optional[int], seed: int) -> dict:
    """
    Which slugs to hit, identically on both legs.

    Seeded and sorted before sampling: an unseeded sample hands the two legs
    different slugs, and then every difference between them is the sample
    rather than the network.
    """
    chosen = {}
    for board in sorted(BOARD_URLS):
        slugs = sorted(s for s in companies.get(board, []) if isinstance(s, str))
        if sample and len(slugs) > sample:
            slugs = sorted(random.Random(seed).sample(slugs, sample))
        if slugs:
            chosen[board] = slugs
    return chosen


def run_probe(sample=None, seed=0, boards=None, delay=0.3, label=None) -> dict:
    """Probe every selected slug and return the full record."""
    selected = select_slugs(load_companies(), sample, seed)
    if boards:
        selected = {b: s for b, s in selected.items() if b in boards}

    total = sum(len(s) for s in selected.values())
    _console_print(f"Probing {total} slug(s) across {len(selected)} board(s)")
    _console_print(f"User-Agent: {USER_AGENT}")
    _console_print("")

    probes, done = [], 0
    for board, slugs in selected.items():
        for slug in slugs:
            result = probe_one(BOARD_URLS[board].format(slug=slug))
            result["board"] = board
            result["slug"] = slug
            result["verdict"] = verdict(result)
            probes.append(result)
            done += 1
            shown = (result["status"] if result["status"] is not None
                     else result["error_kind"])
            _console_print(f"  [{done:>3}/{total}] {board:<15} {slug:<28} "
                           f"{str(shown):<9} {result['verdict']}")
            if delay:
                time.sleep(delay)

    return {
        "label": label or "unlabelled",
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "user_agent": USER_AGENT,
        "timeout_seconds": TIMEOUT_SECONDS,
        "hostname": socket.gethostname(),
        "public_ip": _public_ip(),
        "probes": probes,
    }


def _public_ip() -> Optional[str]:
    """
    Which egress this leg actually left from.

    Recorded because the whole comparison rests on the two legs having
    different origins, and a Fly machine reached through a proxy or a home run
    over a VPN would quietly make them the same one.
    """
    for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.read().decode("utf-8", "replace").strip()
        except Exception:
            continue
    return None


def summarise(record: dict) -> dict:
    """Per-board status-code and verdict histograms."""
    by_board = {}
    for probe in record["probes"]:
        board = by_board.setdefault(probe["board"],
                                    {"statuses": Counter(), "verdicts": Counter()})
        key = probe["status"] if probe["status"] is not None else probe["error_kind"]
        board["statuses"][str(key)] += 1
        board["verdicts"][probe["verdict"]] += 1
    return by_board


def report(record: dict) -> None:
    """Print one leg's findings."""
    _console_print("")
    _console_print("=" * 72)
    _console_print(f"EGRESS PROBE - {record['label']}")
    _console_print("=" * 72)
    _console_print(f"  taken at   {record['taken_at']}")
    _console_print(f"  host       {record['hostname']}")
    _console_print(f"  public IP  {record['public_ip'] or 'unknown'}")
    _console_print("")

    for board, counts in sorted(summarise(record).items()):
        statuses = ", ".join(f"{k} x{v}" for k, v in sorted(counts["statuses"].items()))
        verdicts = ", ".join(f"{k}={v}" for k, v in sorted(counts["verdicts"].items()))
        _console_print(f"  {board:<16} {statuses}")
        _console_print(f"  {'':<16} {verdicts}")

    overall = Counter(p["verdict"] for p in record["probes"])
    _console_print("")
    _console_print("  overall: "
                   + ", ".join(f"{k}={v}" for k, v in sorted(overall.items())))
    hostile = sum(overall[v] for v in HOSTILE)
    _console_print(f"  hostile responses: {hostile} of {len(record['probes'])}")


def compare(home: dict, other: dict) -> int:
    """
    The actual A0 question: same slug, different origin, different answer?

    Returns the number of slugs that answer acceptably from the control and
    hostilely from the other leg. Anything non-zero is a reason not to host
    discovery where the second leg ran.
    """
    def index(record):
        return {(p["board"], p["slug"]): p for p in record["probes"]}

    control, test = index(home), index(other)
    shared = sorted(set(control) & set(test))

    _console_print("")
    _console_print("=" * 72)
    _console_print(f"COMPARISON - control '{home['label']}' vs '{other['label']}'")
    _console_print("=" * 72)
    _console_print(f"  control IP  {home['public_ip'] or 'unknown'}")
    _console_print(f"  test IP     {other['public_ip'] or 'unknown'}")
    if home["public_ip"] and home["public_ip"] == other["public_ip"]:
        _console_print("  !! both legs left from the SAME IP - this compares nothing")
    only_one_leg = sorted(set(control) ^ set(test))
    if only_one_leg:
        _console_print(f"  !! {len(only_one_leg)} slug(s) probed on only one "
                       "leg, ignored")
    _console_print(f"  {len(shared)} slug(s) on both legs")
    _console_print("")

    regressions, differing, matched = [], [], 0
    for key in shared:
        before, after = control[key]["verdict"], test[key]["verdict"]
        if before == after:
            matched += 1
        elif before in FRIENDLY and after in HOSTILE:
            regressions.append((key, before, after, test[key]))
        else:
            differing.append((key, before, after))

    _console_print(f"  same verdict on both legs: {matched}")
    if differing:
        _console_print(f"  differing but not hostile: {len(differing)}")
        for (board, slug), before, after in differing[:10]:
            _console_print(f"      {board}:{slug}  {before} -> {after}")

    if regressions:
        _console_print("")
        _console_print(f"  FAIL: {len(regressions)} slug(s) hostile from the "
                       "test leg only:")
        for (board, slug), before, after, probe in regressions:
            _console_print(f"      {board}:{slug:<26} {before} -> {after} "
                           f"(status {probe['status']}, server {probe['server']})")
    else:
        _console_print("")
        _console_print("  PASS: no slug answers the control and refuses the test leg")

    return len(regressions)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare ATS board responses between two egress origins.")
    parser.add_argument("--out", help="write the full record here as JSON")
    parser.add_argument("--label", help="name this leg, e.g. 'home' or 'fly-ord'")
    parser.add_argument("--sample", type=int,
                        help="slugs per board (default: every one)")
    parser.add_argument("--seed", type=int, default=0,
                        help="sampling seed; both legs must use the same one")
    parser.add_argument("--boards", nargs="*", choices=sorted(BOARD_URLS),
                        help="restrict to these boards")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="seconds between requests (default 0.3)")
    parser.add_argument("--compare", nargs=2, metavar=("CONTROL", "TEST"),
                        help="compare two saved records and exit")
    args = parser.parse_args(argv)

    if args.compare:
        control = json.loads(Path(args.compare[0]).read_text(encoding="utf-8"))
        test = json.loads(Path(args.compare[1]).read_text(encoding="utf-8"))
        report(control)
        report(test)
        return 1 if compare(control, test) else 0

    record = run_probe(sample=args.sample, seed=args.seed, boards=args.boards,
                       delay=args.delay, label=args.label)
    report(record)

    if args.out:
        Path(args.out).write_text(json.dumps(record, indent=2), encoding="utf-8")
        _console_print("")
        _console_print(f"  written to {args.out}")

    # Exit 0 for a single leg either way. Whether a block is a failure is the
    # reader's call, and exiting non-zero because a company left an ATS would
    # be R81's mistake of a harness reporting its own bar as a result. Only
    # `--compare`, which has a control to judge against, can fail.
    return 0


if __name__ == "__main__":
    sys.exit(main())
