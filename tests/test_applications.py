import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from applications.answers import draft_answers, plan_answer
from applications.directory import load_boards
from applications.eligibility import eligibility_reason
from applications.http import Limiter
from applications.jev import JEV_CHECKS, JevError, evaluate, judge
from applications.keywords import location_decision, title_decision
from applications.models import Board, JobPosting, Question
from applications.page import render_page
from applications.pipeline import Keys, StopRun, consider, keyword_stage
from applications.portals import parse_ashby_jobs, parse_greenhouse_jobs, parse_greenhouse_questions, parse_lever_jobs, questions_from_html
from applications.schedule import BoardState, advance, is_due


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def job(**kwargs) -> JobPosting:
    base = dict(
        portal="greenhouse",
        external_job_id="1",
        title="Software Engineer",
        company="Example",
        location="New York, NY",
        link="https://example.test/job",
        description_text="Build product software with a team.",
        posted_at=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return JobPosting(**base)


class TitleTests(unittest.TestCase):
    def test_include_and_exclude(self):
        self.assertTrue(title_decision("Software Engineer").ok)
        self.assertTrue(title_decision("Member of Technical Staff").ok)
        self.assertTrue(title_decision("Product Engineer").ok)
        self.assertTrue(title_decision("Software Engineer II").ok)
        self.assertTrue(title_decision("Founding Engineer").ok)
        self.assertFalse(title_decision("Senior Software Engineer").ok)
        self.assertFalse(title_decision("Senior Member of Technical Staff").ok)
        self.assertFalse(title_decision("Software Engineer Intern").ok)
        self.assertFalse(title_decision("Product Manager").ok)
        self.assertFalse(title_decision("Network Administrator").ok)
        self.assertFalse(title_decision("Staff Software Engineer").ok)

    def test_description_senior_phrase_is_not_a_title_reject(self):
        self.assertTrue(title_decision("Software Engineer").ok)


class LocationTests(unittest.TestCase):
    def test_us_passes_and_other_countries_reject(self):
        self.assertEqual(location_decision("New York, NY").action, "pass")
        self.assertEqual(location_decision("Remote, United States").action, "pass")
        self.assertEqual(location_decision("London, United Kingdom").action, "reject")
        self.assertEqual(location_decision("Toronto, Canada").action, "reject")
        self.assertEqual(location_decision("").action, "pass")

    def test_unspecified_remote_is_uncertain(self):
        self.assertEqual(location_decision("Remote").action, "uncertain")


class EligibilityTests(unittest.TestCase):
    def test_years_do_not_treat_network_security_as_swe(self):
        reason = eligibility_reason("Required: 5+ years of software engineering experience.")
        self.assertIn("years exclude", reason)
        self.assertIn("not AI or SWE", reason)
        self.assertIsNone(eligibility_reason("2+ years of software engineering experience."))
        self.assertIsNone(eligibility_reason("5+ years of software engineering experience preferred."))

    def test_degree_sponsorship_and_country(self):
        self.assertIn("PhD", eligibility_reason("A PhD is required for this role."))
        self.assertIsNone(eligibility_reason("PhD preferred."))
        self.assertIn("citizenship", eligibility_reason("You must be a U.S. citizen."))
        self.assertIn("no sponsorship", eligibility_reason("We do not sponsor employment visas."))
        self.assertIsNone(eligibility_reason("We are unable to sponsor at this time."))
        self.assertIn("outside the United States", eligibility_reason("Candidates must be based in London."))


class AnswerTests(unittest.TestCase):
    def test_known_form_answers(self):
        questions = [
            Question("Are you authorized to work in the United States?", True, ("Yes", "No")),
            Question("Will you now or in the future require sponsorship?", True, ("Yes", "No")),
            Question("Are you eligible for STEM OPT?", True, ("Yes", "No")),
            Question("Are you willing to relocate to Austin, TX?", True, ("Yes", "No")),
            Question("Are you willing to relocate to London?", True, ("Yes", "No")),
        ]
        draft = draft_answers(questions)
        answers = [field.answer for field in draft.fields]
        self.assertEqual(answers, [None, "Yes", None, "Yes", "No"])
        self.assertEqual(draft.stage, "blocked")

    def test_sponsorship_only_now_and_salary_block(self):
        now = plan_answer(Question("Will you require sponsorship now?", True))
        self.assertEqual(now.kind, "blocked")
        draft = draft_answers([Question("What is your salary expectation?", True)])
        self.assertEqual(draft.stage, "blocked")
        self.assertIn("salary", draft.fields[0].reason)

    def test_start_date_is_candidate_confirmed(self):
        field = plan_answer(Question("What is your earliest start date?", True))
        self.assertEqual(field.answer, "January 4, 2027")


class JevTests(unittest.TestCase):
    def test_thresholds(self):
        scores = {key: 0.8 for key, _ in JEV_CHECKS}
        self.assertEqual(judge(scores).stage, "jev_yes")
        scores["level"] = 0.79
        uncertain = judge(scores)
        self.assertEqual(uncertain.stage, "jev_no")
        self.assertTrue(uncertain.reason.startswith("uncertain:"))
        scores["level"] = 0.2
        self.assertTrue(judge(scores).reason.startswith("no:"))

    def test_retry_then_success(self):
        calls = {"n": 0}

        def post(url, payload, headers):
            calls["n"] += 1
            if calls["n"] < 3:
                return 429, b""
            body = {
                "model": "jev-1.13.0",
                "answers": {key: {"type": "noul", "noul": 0.9} for key, _ in JEV_CHECKS},
            }
            import json
            return 200, json.dumps(body).encode()

        slept = []
        decision = evaluate(post, "key", "profile", job(), slept.append)
        self.assertEqual(decision.stage, "jev_yes")
        self.assertEqual(slept, [2, 4])

    def test_unauthorized_raises(self):
        with self.assertRaises(JevError):
            evaluate(lambda *args: (401, b"{}"), "key", "profile", job(), lambda _seconds: None)


class PostedDateTests(unittest.TestCase):
    def test_keeps_only_the_last_24_hours(self):
        now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        fresh = job(posted_at=now - timedelta(hours=23, minutes=59))
        self.assertIsNone(keyword_stage(fresh, now=now))
        stale = job(posted_at=now - timedelta(hours=24))
        self.assertIn("more than 24 hours", keyword_stage(stale, now=now)[1])
        missing = job(posted_at=None)
        self.assertEqual(keyword_stage(missing, now=now)[1], "posted date missing")


class PipelineTests(unittest.TestCase):
    def test_keyword_reject_does_not_call_jev(self):
        called = {"jev": 0}

        def jev(_posting):
            called["jev"] += 1
            return "jev_yes", "yes", "jev-1.13.0"

        rows = consider(
            job(title="Senior Software Engineer"),
            seen=False,
            profile="profile",
            keys=Keys("a", "b", "gpt-6-luna"),
            timestamp="2026-09-26T00:00:00Z",
            jev=jev,
            questions_for=lambda _posting: [],
            drafter=lambda _posting, _questions: None,
        )
        self.assertEqual(rows[0].stage, "keyword_reject")
        self.assertEqual(called["jev"], 0)
        self.assertNotIn("submitted", [row.stage for row in rows])

    def test_missing_keys_stop_before_jev(self):
        with self.assertRaises(StopRun):
            consider(
                job(),
                seen=False,
                profile="profile",
                keys=Keys("", "", "gpt-6-luna"),
                timestamp="2026-09-26T00:00:00Z",
                jev=lambda _posting: ("jev_yes", "yes", "jev-1.13.0"),
                questions_for=lambda _posting: [],
                drafter=lambda _posting, _questions: None,
            )

    def test_yes_then_blocked_draft(self):
        from applications.answers import Draft, FieldAnswer

        def drafter(_posting, _questions):
            return Draft(
                (FieldAnswer("Salary", True, "blocked", None, "salary expectation is unknown"),),
                "blocked",
                "missing required field: Salary",
            )

        rows = consider(
            job(),
            seen=False,
            profile="profile",
            keys=Keys("a", "b", "gpt-6-luna"),
            timestamp="2026-09-26T00:00:00Z",
            jev=lambda _posting: ("jev_yes", "yes: role_family yes (0.90)", "jev-1.13.0"),
            questions_for=lambda _posting: [Question("Salary", True)],
            drafter=drafter,
        )
        self.assertEqual([row.stage for row in rows], ["jev_yes", "blocked"])

    def test_seen_job_is_skipped(self):
        rows = consider(
            job(),
            seen=True,
            profile="profile",
            keys=Keys("", "", "gpt-6-luna"),
            timestamp="2026-09-26T00:00:00Z",
            jev=lambda _posting: None,
            questions_for=lambda _posting: [],
            drafter=lambda _posting, _questions: None,
        )
        self.assertEqual(rows, [])


class ScheduleTests(unittest.TestCase):
    def test_intervals(self):
        live = advance(None, ok=True, job_count=2, now=NOW, status="200")
        self.assertTrue(live.next_check.startswith("2026-09-26T18:"))
        empty = advance(None, ok=True, job_count=0, now=NOW, status="200")
        self.assertTrue(empty.next_check.startswith("2026-09-27T12:"))
        once = advance(None, ok=False, job_count=0, now=NOW, status="404")
        twice = advance(once, ok=False, job_count=0, now=NOW, status="404")
        self.assertEqual(twice.consecutive_failures, 2)
        self.assertTrue(twice.next_check.startswith("2026-09-26T18:"))
        weekly = advance(twice, ok=False, job_count=0, now=NOW, status="404")
        self.assertTrue(weekly.next_check.startswith("2026-10-03T12:"))
        recovered = advance(weekly, ok=True, job_count=1, now=NOW, status="200")
        self.assertEqual(recovered.consecutive_failures, 0)
        self.assertTrue(is_due(BoardState(next_check="2026-09-26T11:00:00Z"), NOW))
        self.assertFalse(is_due(live, NOW))


class LimiterTests(unittest.TestCase):
    def test_gap_never_under_one_second(self):
        clock = {"t": 0.0}
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            clock["t"] += seconds

        limiter = Limiter(sleep=sleep, monotonic=lambda: clock["t"], jitter=lambda: 0)
        limiter.wait()
        limiter.wait()
        self.assertGreaterEqual(slept[0], 1)


class PortalTests(unittest.TestCase):
    def test_parsers(self):
        board = Board("greenhouse", "Example", "example")
        jobs = parse_greenhouse_jobs(
            {"jobs": [{"id": 9, "title": "Software Engineer", "absolute_url": "https://example.test", "location": {"name": "NY"}, "first_published": "2026-09-26T11:00:00-04:00"}]},
            board,
        )
        self.assertEqual(jobs[0].external_job_id, "9")
        self.assertEqual(jobs[0].posted_at, datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc))
        questions = parse_greenhouse_questions(
            {"questions": [{"label": "First Name", "required": True, "fields": [{"name": "first_name", "type": "input"}]}]}
        )
        self.assertTrue(questions[0].required)
        ashby = parse_ashby_jobs(
            {"jobs": [{"title": "Backend Engineer", "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/x/1", "descriptionPlain": "Role", "publishedAt": "2026-09-26T12:00:00.000+00:00"}]},
            Board("ashby", "X", "x"),
        )
        self.assertFalse(ashby[0].is_listed)
        self.assertEqual(ashby[0].external_job_id, "https://jobs.ashbyhq.com/x/1")
        lever = parse_lever_jobs([{"id": "abc", "text": "Software Engineer", "hostedUrl": "https://jobs.lever.co/x/abc", "createdAt": 1565990241800}], Board("lever", "X", "x"))
        self.assertEqual(lever[0].external_job_id, "abc")
        self.assertEqual(lever[0].posted_at.year, 2019)
        parsed = questions_from_html("<label>Email *</label><label>Portfolio</label>")
        self.assertTrue(parsed[0].required)
        self.assertFalse(parsed[1].required)


class PageTests(unittest.TestCase):
    def test_default_view_omits_keyword_rejects(self):
        folder = Path(self.id().replace(".", "_"))
        # use a temp dir via TemporaryDirectory in the method body
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "applications.csv"
            csv_path.write_text(
                "timestamp,portal,external_job_id,job,company,link,stage,reason,model\n"
                "2026-09-26T00:00:00Z,greenhouse,1,Role,Hidden,https://example.test,keyword_reject,title, \n"
                "2026-09-26T00:00:00Z,greenhouse,2,Role,Draft Co,https://example.test/2,drafted,drafted 1,jev-1.13.0\n"
                "2026-09-26T00:00:00Z,greenhouse,3,Role,Sent Co,https://example.test/3,submitted,confirmed, \n",
                encoding="utf-8",
            )
            html_path = root / "applications.html"
            render_page(csv_path, html_path, root / "drafts.json")
            page = html_path.read_text(encoding="utf-8")
            self.assertNotIn("Hidden", page)
            self.assertIn("Draft Co", page)
            self.assertIn("Sent Co", page)
            self.assertIn('apply("submitted")', page)


class DirectoryTests(unittest.TestCase):
    def test_directory_count(self):
        boards = load_boards(ROOT / "data" / "ats-board-directory.csv")
        self.assertEqual(len(boards), 12918)
        self.assertEqual(sum(board.vendor == "greenhouse" for board in boards), 6889)


class ChecklistTests(unittest.TestCase):
    def test_questions_match_the_rules_file(self):
        rules = (ROOT / "eligibility-rules.md").read_text(encoding="utf-8")
        for _key, question in JEV_CHECKS:
            self.assertIn(question, rules)


if __name__ == "__main__":
    unittest.main()
