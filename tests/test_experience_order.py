"""
A resume is read down the left edge, and the dates have to descend.

Priya Raghunathan's tailored resume opened with the job she left in 2020 and
buried the one she currently holds three inches below it. Nothing was wrong
with the content: selection ranks components by how well they match the
posting, that ranking is the order they arrive in, and it reached the page
untouched. Relevance is the right way to choose *which* roles appear and the
wrong way to order them once chosen.

The rule lives in `tex_renderer` because that module is the one place that
decides what this template looks like, and because both renderers go through
it — the `.tex` a stranger imports and the tailored file the pipeline writes.
Putting it anywhere else would recreate the fork that has produced five bugs
in this repo, most recently the field transposition (R70) and the escape table
(R69), both fixed in one renderer and left standing in the other.

**Unknown is not the year zero.** If any one entry's dates cannot be read,
nothing moves. Sorting the rest around an unparseable date would state a
sequence the data does not support, and a resume asserting the wrong career
order is worse than one asserting none.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.resume import tex_renderer  # noqa: E402


def job(company, dates):
    return {"company": company, "title": "Software Engineer",
            "dates": dates, "location": "Boston, MA",
            "bullets": ["Shipped the thing."]}


def companies(entries):
    return [e["company"] for e in tex_renderer.reverse_chronological(entries)]


class TestNewestFirst(unittest.TestCase):

    def test_priyas_three_jobs_come_out_in_the_order_she_worked_them(self):
        self.assertEqual(
            companies([job("Vistaprint", "Jul 2018 - May 2020"),
                       job("Wayfair", "Mar 2023 - Present"),
                       job("Toast", "Jun 2020 - Feb 2023")]),
            ["Wayfair", "Toast", "Vistaprint"])

    def test_an_ongoing_role_does_not_jump_the_queue(self):
        """
        Ordered on when a role *began*, which is the convention and also the
        only thing that separates a job still running from one that started
        later. The author's own master lists them this way: Sorenson began in
        June 2025 and comes first, above the contract work he has held since
        June 2024.
        """
        self.assertEqual(
            companies([job("Outlier AI", "June 2024 - Current"),
                       job("Sorenson", "June 2025 - Oct. 2025")]),
            ["Sorenson", "Outlier AI"])

    def test_the_month_matters_within_a_year(self):
        self.assertEqual(
            companies([job("Early", "Jan 2024 - Mar 2024"),
                       job("Late", "Sept. 2024 - Dec 2024")]),
            ["Late", "Early"])

    def test_a_bare_year_is_still_a_year(self):
        self.assertEqual(
            companies([job("Older", "2019 - 2021"), job("Newer", "2022 - 2024")]),
            ["Newer", "Older"])

    def test_the_dashes_a_resume_actually_uses(self):
        """Hyphen, en dash and LaTeX's double hyphen all appear in the wild."""
        for dash in ("-", "–", "—", "--"):
            with self.subTest(dash=dash):
                self.assertEqual(
                    companies([job("Old", f"Jan 2020 {dash} Jan 2021"),
                               job("New", f"Jan 2024 {dash} Jan 2025")]),
                    ["New", "Old"])


class TestWhatCannotBeReadIsNotGuessedAt(unittest.TestCase):

    def test_one_unreadable_date_leaves_every_entry_where_it_was(self):
        """
        Not "sort the ones you can and put the rest at the end" — that files
        an unknown date under 'oldest', which is the mistake this codebase has
        now made eight times in other fields.
        """
        given = [job("Vistaprint", "Jul 2018 - May 2020"),
                 job("Consulting", "on and off"),
                 job("Wayfair", "Mar 2023 - Present")]
        self.assertEqual(companies(given),
                         ["Vistaprint", "Consulting", "Wayfair"])

    def test_a_missing_dates_field_is_the_same_case(self):
        given = [job("A", "Jan 2020 - Jan 2021"), {"company": "B",
                                                   "bullets": []}]
        self.assertEqual(companies(given), ["A", "B"])

    def test_entries_starting_the_same_month_keep_selection_order(self):
        """The tie-break is the ranking they arrived in, which is the best
        answer available and, more importantly, a stable one."""
        self.assertEqual(
            companies([job("Ranked first", "Jan 2024 - Present"),
                       job("Ranked second", "Jan 2024 - Present")]),
            ["Ranked first", "Ranked second"])


class TestBothRenderersOrderTheSameWay(unittest.TestCase):
    """
    The comparison that would have caught R69 and R70. One rule, one module,
    and a check that says so from the outside.
    """

    JOBS = [job("Vistaprint", "Jul 2018 - May 2020"),
            job("Wayfair", "Mar 2023 - Present"),
            job("Toast", "Jun 2020 - Feb 2023")]

    def _order(self, latex):
        seen = []
        for company in ("Wayfair", "Toast", "Vistaprint"):
            seen.append((latex.index(company), company))
        return [company for _, company in sorted(seen)]

    def test_the_generated_section_is_newest_first(self):
        self.assertEqual(
            self._order(tex_renderer.experience_block(self.JOBS)),
            ["Wayfair", "Toast", "Vistaprint"])

    def test_the_imported_document_is_newest_first(self):
        document = tex_renderer.render({
            "contact": {"name": "Priya Raghunathan"},
            "education": [], "projects": [], "skills": {},
            "experiences": self.JOBS,
        })
        self.assertEqual(self._order(document),
                         ["Wayfair", "Toast", "Vistaprint"])

    def test_nothing_is_lost_on_the_way_through(self):
        """Reordering is not an excuse to drop one."""
        block = tex_renderer.experience_block(self.JOBS)
        for entry in self.JOBS:
            self.assertIn(entry["company"], block)


if __name__ == "__main__":
    unittest.main()
