"""
The egress probe measures the network the pipeline actually uses.

A probe pointed at a URL `ats_search` no longer fetches measures the wrong
network and reports it as the right one — which is R81's rule applied to the
instrument: check the instrument before trusting the reading. These tests keep
the two in sync and pin the vocabulary the probe exists to provide.

No network. Every response is synthesised, including the ones that are the
whole reason the probe does not call `_fetch`.
"""

import io
import json
import sys
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.egress_probe import (  # noqa: E402
    BOARD_URLS,
    compare,
    probe_one,
    select_slugs,
    summarise,
    verdict,
)
from tools.search import ats_search  # noqa: E402


def _headers(**pairs):
    """An email.message.Message, which is what urllib hands back as headers."""
    message = Message()
    for key, value in pairs.items():
        message[key.replace("_", "-")] = value
    return message


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or _headers(Content_Type="application/json")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _urlopen_returning(response):
    return mock.patch("urllib.request.urlopen", return_value=response)


def _urlopen_raising(exc):
    return mock.patch("urllib.request.urlopen", side_effect=exc)


class TestTheProbeMeasuresTheRealBoards(unittest.TestCase):
    """The instrument check: same URLs, same headers, same timeout."""

    def setUp(self):
        self.source = (ROOT / "tools" / "search" / "ats_search.py").read_text(
            encoding="utf-8")

    def test_every_board_url_still_appears_in_ats_search(self):
        """
        The drift guard. If `_greenhouse` moves to a v2 endpoint and this table
        does not, the probe keeps reporting 200 from an endpoint discovery no
        longer calls, and A0's conclusion is about a URL nobody fetches.

        A reformat of the URL in `ats_search.py` trips this too, since the
        check is verbatim. That is the intended trade: a loud false positive
        costs one line to fix, and the alternative is a probe that quietly
        measures the wrong endpoint. Update the table - do not delete this.
        """
        missing = [board for board, template in BOARD_URLS.items()
                   if template not in self.source]
        self.assertEqual(
            missing, [],
            f"egress_probe.BOARD_URLS has drifted from ats_search.py: {missing}")

    def test_it_covers_every_board_the_pipeline_reads(self):
        """
        Fails on board #6. R80's counting rule: the closing move is a test that
        fails when a source is added, because the count in mind is reliably
        lower than the count in the code.
        """
        self.assertEqual(sorted(BOARD_URLS), sorted(ats_search.BOARDS))

    def test_it_sends_the_same_user_agent(self):
        """
        A probe with a different UA measures a different client. Several of
        these boards vary behaviour on it, so a bare urllib default could
        manufacture the block A0 is looking for.
        """
        captured = {}

        def fake_urlopen(request, **kwargs):
            captured["ua"] = request.get_header("User-agent")
            captured["timeout"] = kwargs.get("timeout")
            return _FakeResponse(b"[]")

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            probe_one("https://example.test/board")

        self.assertEqual(captured["ua"], ats_search.USER_AGENT)
        self.assertEqual(captured["timeout"], ats_search.TIMEOUT_SECONDS)

    def test_it_does_not_route_through_the_lossy_fetch(self):
        """
        `_fetch` returns None for every failure, which is the defect being
        measured. If the probe ever calls it, every interesting case reads as
        `unreachable` and the comparison is worthless.
        """
        with mock.patch.object(ats_search, "_fetch",
                              side_effect=AssertionError("probe called _fetch")):
            with _urlopen_returning(_FakeResponse(b"[]")):
                self.assertEqual(probe_one("https://example.test/b")["status"], 200)


class TestTheVerdictsAreDistinguishable(unittest.TestCase):
    """
    Q32's four cases, which `_fetch` returns `None` for all of. Each must read
    back as itself — that separation *is* the deliverable.
    """

    def test_a_200_with_json_is_ok(self):
        with _urlopen_returning(_FakeResponse(b'[{"id": 1}]')):
            result = probe_one("https://example.test/b")
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["json_ok"])
        self.assertEqual(result["records"], 1)
        self.assertEqual(verdict(result), "ok")

    def test_a_404_is_absent_not_blocked(self):
        """
        The distinction that keeps the probe honest. A company that left an ATS
        404s from every IP on earth; reading that as a block would find a
        datacenter problem on a home connection.
        """
        error = urllib.error.HTTPError(
            "https://example.test/b", 404, "Not Found",
            _headers(Content_Type="application/json"), io.BytesIO(b"{}"))
        with _urlopen_raising(error):
            result = probe_one("https://example.test/b")
        self.assertEqual(result["status"], 404)
        self.assertEqual(verdict(result), "absent")

    def test_a_403_is_blocked(self):
        error = urllib.error.HTTPError(
            "https://example.test/b", 403, "Forbidden",
            _headers(Content_Type="text/html", Server="cloudflare"),
            io.BytesIO(b"<html>Access denied</html>"))
        with _urlopen_raising(error):
            result = probe_one("https://example.test/b")
        self.assertEqual(result["status"], 403)
        self.assertEqual(result["server"], "cloudflare")
        # Challenge wins over blocked when the body says so: both are hostile,
        # and which vendor surface refused is the actionable half.
        self.assertIn(verdict(result), {"blocked", "challenged"})

    def test_a_429_is_blocked(self):
        error = urllib.error.HTTPError(
            "https://example.test/b", 429, "Too Many Requests",
            _headers(Content_Type="application/json"), io.BytesIO(b"{}"))
        with _urlopen_raising(error):
            result = probe_one("https://example.test/b")
        self.assertEqual(verdict(result), "blocked")

    def test_a_challenge_page_served_as_200_is_not_ok(self):
        """
        The case that looks like success and is the reason counts are not
        enough. Cloudflare answers 200 with HTML, `json.loads` raises, and
        every existing reader sees an empty board.
        """
        body = b"<html><title>Just a moment...</title></html>"
        with _urlopen_returning(_FakeResponse(
                body, 200, _headers(Content_Type="text/html", CF_Ray="abc-ORD"))):
            result = probe_one("https://example.test/b")
        self.assertEqual(result["status"], 200)
        self.assertFalse(result["json_ok"])
        self.assertTrue(result["challenge"])
        self.assertEqual(result["cf_ray"], "abc-ORD")
        self.assertEqual(verdict(result), "challenged")

    def test_an_empty_board_is_ok_and_not_a_block(self):
        """
        A real 200 carrying zero roles. The other half of the same confusion:
        `search_ats` counts this as `failed` today, which is why "0 discovered"
        cannot say why.
        """
        with _urlopen_returning(_FakeResponse(b"[]")):
            result = probe_one("https://example.test/b")
        self.assertEqual(verdict(result), "ok")
        self.assertEqual(result["records"], 0)

    def test_a_dns_failure_has_no_status_rather_than_a_zero(self):
        """
        Unknown is never a value (R64/R69). A status of 0 would sort and
        compare as a number, and a histogram would read it as a real code.
        """
        import socket
        with _urlopen_raising(urllib.error.URLError(socket.gaierror("no such host"))):
            result = probe_one("https://example.test/b")
        self.assertIsNone(result["status"])
        self.assertEqual(result["error_kind"], "dns")
        self.assertEqual(verdict(result), "unreachable")

    def test_a_tls_failure_is_distinguished_from_dns(self):
        import ssl
        with _urlopen_raising(urllib.error.URLError(ssl.SSLError("handshake"))):
            result = probe_one("https://example.test/b")
        self.assertEqual(result["error_kind"], "tls")
        self.assertEqual(verdict(result), "unreachable")

    def test_no_response_shape_raises(self):
        """
        A probe that stops at the first refused connection reports on one slug.
        """
        with _urlopen_raising(RuntimeError("something nobody predicted")):
            result = probe_one("https://example.test/b")
        self.assertEqual(result["error_kind"], "RuntimeError")
        self.assertIsNone(result["status"])


class TestSamplingIsIdenticalOnBothLegs(unittest.TestCase):

    COMPANIES = {"greenhouse": [f"co{i}" for i in range(20)],
                 "lever": ["alpha", "beta"],
                 "ashby": [], "workable": ["gamma"], "smartrecruiters": ["delta"]}

    def test_the_same_seed_picks_the_same_slugs(self):
        """
        Without this, every difference between the two legs is the sample
        rather than the network — a measurement of the instrument (R81).
        """
        first = select_slugs(self.COMPANIES, sample=5, seed=7)
        second = select_slugs(self.COMPANIES, sample=5, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(len(first["greenhouse"]), 5)

    def test_an_empty_board_list_is_omitted_not_probed(self):
        chosen = select_slugs(self.COMPANIES, sample=None, seed=0)
        self.assertNotIn("ashby", chosen)

    def test_no_sample_takes_everything(self):
        chosen = select_slugs(self.COMPANIES, sample=None, seed=0)
        self.assertEqual(len(chosen["greenhouse"]), 20)

    def test_a_non_string_slug_is_skipped(self):
        """
        `ats_companies.json` carries a `_comment` key and hand-edited files
        carry worse. A crash here would be a probe that fails on the machine
        with the fuller seed list.
        """
        chosen = select_slugs({"lever": ["ok", None, 42, "fine"]},
                              sample=None, seed=0)
        self.assertEqual(chosen["lever"], ["fine", "ok"])


def _record(label, ip, probes):
    return {"label": label, "public_ip": ip, "taken_at": "2026-09-21T00:00:00Z",
            "hostname": "h", "user_agent": "ua", "timeout_seconds": 25,
            "probes": probes}


def _probe(board, slug, status, verdict_name, json_ok=True, challenge=False):
    return {"board": board, "slug": slug, "status": status, "verdict": verdict_name,
            "json_ok": json_ok, "challenge": challenge, "server": None,
            "cf_ray": None, "error_kind": None, "error": None, "records": 0,
            "body_bytes": 2, "content_type": "application/json", "seconds": 0.1,
            "url": f"https://example.test/{board}/{slug}"}


class TestTheComparisonIsTheDeliverable(unittest.TestCase):

    def test_a_slug_that_answers_home_and_refuses_fly_is_a_regression(self):
        home = _record("home", "1.1.1.1", [_probe("greenhouse", "acme", 200, "ok")])
        fly = _record("fly", "2.2.2.2",
                      [_probe("greenhouse", "acme", 403, "blocked", json_ok=False)])
        self.assertEqual(compare(home, fly), 1)

    def test_a_slug_absent_from_both_legs_is_not_a_regression(self):
        """
        A company that left the ATS 404s everywhere. Counting that as a block
        would report a Fly problem that is a Greenhouse fact.
        """
        home = _record("home", "1.1.1.1", [_probe("lever", "gone", 404, "absent")])
        fly = _record("fly", "2.2.2.2", [_probe("lever", "gone", 404, "absent")])
        self.assertEqual(compare(home, fly), 0)

    def test_a_200_that_stops_parsing_counts_as_hostile(self):
        """The challenge-page case, which is the one A0 is most likely to hit."""
        home = _record("home", "1.1.1.1", [_probe("ashby", "acme", 200, "ok")])
        fly = _record("fly", "2.2.2.2",
                      [_probe("ashby", "acme", 200, "challenged",
                              json_ok=False, challenge=True)])
        self.assertEqual(compare(home, fly), 1)

    def test_a_leg_that_improves_is_not_counted_as_a_regression(self):
        home = _record("home", "1.1.1.1", [_probe("lever", "acme", 429, "blocked")])
        fly = _record("fly", "2.2.2.2", [_probe("lever", "acme", 200, "ok")])
        self.assertEqual(compare(home, fly), 0)

    def test_slugs_on_only_one_leg_are_ignored(self):
        """
        Comparing a slug one leg never probed compares a probe to nothing.
        """
        home = _record("home", "1.1.1.1", [_probe("lever", "a", 200, "ok"),
                                           _probe("lever", "b", 200, "ok")])
        fly = _record("fly", "2.2.2.2", [_probe("lever", "a", 403, "blocked")])
        self.assertEqual(compare(home, fly), 1)

    def test_two_legs_from_one_ip_still_report_rather_than_crash(self):
        """
        It compares nothing, and the operator has to be told that in the
        output — a silent pass here is how a VPN turns into a green light.
        """
        probes = [_probe("lever", "acme", 200, "ok")]
        same = _record("home", "1.1.1.1", probes)
        self.assertEqual(compare(same, _record("fly", "1.1.1.1", probes)), 0)

    def test_an_unknown_ip_does_not_read_as_a_match(self):
        """Unknown is never a value: two `None` IPs are not the same origin."""
        probes = [_probe("lever", "acme", 200, "ok")]
        self.assertEqual(compare(_record("home", None, probes),
                                 _record("fly", None, probes)), 0)


class TestTheSummary(unittest.TestCase):

    def test_a_missing_status_is_grouped_by_its_error_kind(self):
        """
        A histogram key of `None` would print as a code. The failure kind is
        the thing a reader can act on.
        """
        probe = _probe("lever", "acme", None, "unreachable")
        probe["error_kind"] = "dns"
        counts = summarise(_record("home", None, [probe]))
        self.assertEqual(counts["lever"]["statuses"]["dns"], 1)

    def test_the_record_round_trips_through_json(self):
        """
        The two legs meet only as files, so anything that will not serialise
        is lost between them.
        """
        with _urlopen_returning(_FakeResponse(b"[]")):
            result = probe_one("https://example.test/b")
        self.assertEqual(json.loads(json.dumps(result))["status"], 200)


if __name__ == "__main__":
    unittest.main()
