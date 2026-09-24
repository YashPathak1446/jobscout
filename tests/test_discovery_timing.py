"""
Discovery stays fast at the size of a real board (R130).

The live freeze after 2,259 ATS listings, at "Searching GitHub new grad
repos...", was blamed on R127, which added a key per listing to dedup and a
store lookup per discovered job. Those paths are timed here at about 2,500
listings and are milliseconds.

The freeze was the GitHub parser. Its table regex, run over a whole README,
backtracked across line ends. On speedyapply's list, which moved to HTML
tables, it did not finish in 90 seconds, holding the interpreter lock, so the
server could not even handle SIGTERM. The parser now matches line by line;
the synthetic HTML README below reproduces that list's shape.

The parser check runs in a subprocess with a timeout, so a regression fails
the test rather than hanging the suite.
"""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.search.job_listing import JobListing  # noqa: E402

N = 2500
BUDGET = 1.0  # seconds


def listing(i: int, cased: bool = False) -> JobListing:
    slug = "Experian" if cased else "experian"
    url = f"https://jobs.smartrecruiters.com/{slug}/{i}-software-engineer?id={i}"
    return JobListing(id=url, title="Software Engineer", company="Experian",
                      location="Remote", description="d", apply_url=url,
                      salary_min=None, salary_max=None, created="",
                      source="ats_smartrecruiters", full_jd="A posting. " * 30)


class TestDedupAtBoardSize(unittest.TestCase):

    def test_discovery_dedup_of_2500_listings_is_under_a_second(self):
        from agents.discovery_agent import DiscoveryAgent

        agent = DiscoveryAgent.__new__(DiscoveryAgent)
        agent.seen_urls, agent.all_jobs = set(), []
        jobs = [listing(i) for i in range(N)] + [listing(i, cased=True) for i in range(N)]
        start = time.perf_counter()
        added = agent._deduplicate_and_add(jobs)
        elapsed = time.perf_counter() - start
        self.assertEqual(added, N, "case variants are one posting (R127)")
        self.assertLess(elapsed, BUDGET, f"dedup of {len(jobs)} took {elapsed:.2f}s")

    def test_the_store_side_of_dedup_is_under_a_second(self):
        """R127's per-job lookups, against a board already holding them."""
        from tools.jobs.job_store import JobStore

        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.db")
            try:
                store.record([listing(i) for i in range(N)])
                cased = [listing(i, cased=True) for i in range(N)]
                start = time.perf_counter()
                store.record(cased)
                for job in cased:
                    store.stored_url(job.apply_url)
                elapsed = time.perf_counter() - start
                total = store._db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            finally:
                store.close()
        self.assertEqual(total, N)
        self.assertLess(elapsed, BUDGET, f"record + lookup of {N} took {elapsed:.2f}s")


# A list in speedyapply's current shape: HTML anchors, no markdown links.
HTML_ROW = ('| <a href="https://www.example.com/{i}"><strong>Company {i}</strong></a> '
            '| New Grad Software Engineer {i} - Platform, Infrastructure & Tools '
            '| San Francisco, CA | $168k/yr | <a href="https://jobs.example.com/'
            + "x" * 200 + '/{i}"><img src="https://i.imgur.com/x.png" alt="Apply" '
            'width="70"/></a> | 3d |')
MARKDOWN = ("| Company | Job Title | Location | Work Model | Date Posted |\n"
            "| ----- | --------- | --------- | ---- | ------- |\n"
            "| **[Acme](https://acme.example)** | **[Software Engineer](https://jobs.example/1)** "
            "| Boston, MA, United States | On Site | Sep 24 |\n"
            "| **[Beta](https://beta.example)** | **[Backend Engineer](https://jobs.example/2)** "
            "| Austin, TX, United States | Remote | Sep 24 |\n")

PROBE = r"""
import sys, time, logging
sys.path.insert(0, {root!r})
logging.disable(logging.CRITICAL)
from unittest import mock
from tools.search import github_search as g
html = "| Company | Position | Location | Salary | Posting | Age |\n|---|---|---|---|---|---|\n"
html += "\n".join({row!r}.format(i=i) for i in range(500)) + "\n"
class R:
    def __init__(self, text): self.status_code, self.text = 200, text
with mock.patch.object(g.requests, "get", side_effect=[R({markdown!r}), R(html)]):
    start = time.perf_counter()
    jobs = g.search_github_newgrad(max_results=200)
    print(len(jobs), round(time.perf_counter() - start, 3),
          "|".join(j.company for j in jobs))
"""


class TestTheGitHubParser(unittest.TestCase):

    def test_an_html_table_readme_parses_quickly_and_markdown_rows_still_read(self):
        code = PROBE.format(root=str(ROOT), row=HTML_ROW, markdown=MARKDOWN)
        try:
            done = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                  text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("the GitHub parser did not finish in 30s on an HTML-table "
                      "README: the backtracking freeze is back")
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        count, seconds, companies = done.stdout.strip().split(" ", 2)
        self.assertLess(float(seconds), BUDGET)
        # Both markdown rows, including the first after the header, which the
        # whole-document match used to swallow into a match from the header.
        self.assertEqual(companies.split("|"), ["Acme", "Beta"])
        self.assertEqual(int(count), 2)


if __name__ == "__main__":
    unittest.main()
