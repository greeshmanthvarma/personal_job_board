import json
import tempfile
import unittest
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from applications.answers import model_prompt, plan_answer
from applications.browser import questions_from_rendered_page
from applications.eligibility import eligibility_reason
from applications.keywords import location_decision
from applications.log import ApplicationLog
from applications.models import Question, Record, JobPosting
from applications.pipeline import keyword_stage
from applications.page import _document


class RegressionTests(unittest.TestCase):
    def test_address_and_start_date(self):
        for label, expected in [('Street address', '1118 Tripoli'), ('Address line 1', '1118 Tripoli'), ('ZIP code', '92507'), ('City', 'Riverside'), ('State', 'California'), ('Full address', '1118 Tripoli, Riverside, CA 92507, United States'), ('What month can you start?', 'January 2027'), ('Earliest start date', 'January 4, 2027')]:
            self.assertEqual(plan_answer(Question(label, True)).answer, expected)
        self.assertEqual(plan_answer(Question('Start date', True, kind='date')).answer, '2027-01-04')
        self.assertEqual(plan_answer(Question('Address line 2', False)).kind, 'omitted')

    def test_each_entry_has_escaped_saved_responses(self):
        rows = [Record('2026-09-26', 'ashby', '1', 'Engineer', 'Example', 'url', 'blocked', 'Missing salary'), Record('2026-09-26', 'ashby', '2', 'Engineer', 'Other', 'url', 'failed', 'Form unavailable')]
        page = _document(rows, {'ashby\t1': {'fields': [
            {'label': 'Why us?', 'required': True, 'kind': 'answered', 'answer': '<script>bad()</script>\nSecond line'},
            {'label': 'Salary', 'required': True, 'kind': 'blocked', 'answer': None, 'reason': 'Unknown salary'},
            {'label': 'Cover letter', 'required': False, 'kind': 'omitted', 'answer': None, 'reason': 'No document supplied'},
            {'label': 'Resume', 'required': True, 'kind': 'attach', 'answer': 'resume.pdf'},
        ]}})
        self.assertEqual(page.count('<details class="responses">'), 2)
        self.assertIn('View responses (4)', page)
        self.assertIn('&lt;script&gt;bad()&lt;/script&gt;', page)
        self.assertNotIn('<script>bad()', page)
        self.assertIn('(blocked, required)', page)
        self.assertIn('(omitted, optional)', page)
        self.assertIn('resume.pdf', page)
        self.assertIn('No saved responses for this entry.', page)

    def test_submitted_entries_keep_responses(self):
        row = Record('2026-09-26', 'ashby', '3', 'Engineer', 'Sent', 'url', 'submitted', 'Submission confirmed')
        page = _document([row], {'ashby\t3': {'fields': [{'label': 'Why us?', 'required': True, 'kind': 'answered', 'answer': 'My saved response'}]}})
        self.assertIn('data-stage="submitted"', page)
        self.assertIn('View responses (1)', page)
        self.assertIn('My saved response', page)

    def test_us_city_requirement(self):
        for city in ('San Francisco', 'New York, NY', 'Austin, TX'):
            self.assertEqual(location_decision(city).action, 'pass')
            self.assertIsNone(eligibility_reason(f'Candidates must be based in {city}.'))
        self.assertIsNotNone(eligibility_reason('Candidates must be based in London.'))

    def test_uploads_are_distinct(self):
        self.assertEqual(plan_answer(Question('Resume', True, kind='file')).answer, 'resume.pdf')
        self.assertEqual(plan_answer(Question('Cover letter', True, kind='file')).kind, 'blocked')
        self.assertEqual(plan_answer(Question('Portfolio document', False, kind='file')).kind, 'omitted')

    def test_authorization_and_expiration_are_not_guessed(self):
        for label in ('Are you authorized to work in the United States?', 'Are you eligible for STEM OPT?', 'Describe your visa status and expiration date'):
            self.assertEqual(plan_answer(Question(label, True)).kind, 'blocked')
        self.assertEqual(plan_answer(Question('Will you require sponsorship in the future?', True)).answer, 'Yes')

    def test_context_in_answer_prompt(self):
        payload = json.loads(model_prompt('Profile', 'Engineer', [(0, Question('Why us?', True))], company='Example', description='Build search')[1]['content'])
        self.assertEqual(payload['company'], 'Example')
        self.assertEqual(payload['job_description'], 'Build search')

    def test_latest_stage_controls_retry_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'applications.csv'
            log = ApplicationLog(path)
            def append(stage):
                log.append(Record('now', 'ashby', '1', 'Engineer', 'Example', 'url', stage, 'reason'))
            append('jev_yes')
            append('blocked')
            self.assertFalse(log.contains('ashby', '1'))
            self.assertTrue(ApplicationLog(path).retryable('ashby', '1'))
            append('drafted')
            self.assertTrue(ApplicationLog(path).contains('ashby', '1'))
            self.assertFalse(log.retryable('ashby', '1'))

    def test_retry_bypasses_age_only(self):
        now = datetime.now(timezone.utc)
        posting = JobPosting('ashby', '1', 'Software Engineer', 'Example', 'San Francisco', 'url', posted_at=now-timedelta(days=3))
        self.assertIsNotNone(keyword_stage(posting, now))
        self.assertIsNone(keyword_stage(posting, now, retry=True))
        posting.title = 'Senior Software Engineer'
        self.assertIsNotNone(keyword_stage(posting, now, retry=True))

    def test_rendered_metadata_preserved(self):
        class Page:
            def evaluate(self, script):
                return [{'label': 'Resume', 'required': True, 'options': [], 'kind': 'file'}, {'label': 'Sponsorship', 'required': True, 'options': ['Yes', 'No'], 'kind': 'text'}]
        fields = questions_from_rendered_page(Page())
        self.assertEqual(fields[0].kind, 'file')
        self.assertTrue(fields[1].required)
        self.assertEqual(fields[1].options, ('Yes', 'No'))

    @unittest.skipUnless(importlib.util.find_spec('playwright'), 'optional browser dependency not installed')
    def test_real_rendered_form(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content('''<form>
                    <label for="email">Email</label><input id="email" required>
                    <label for="letter">Cover letter</label><input type="file" id="letter" required>
                    <label for="source">Source</label><select id="source" required><option value="">Choose</option><option value="li">LinkedIn</option></select>
                    <fieldset><legend>Sponsorship</legend><label><input type="radio" name="sponsor" required>Yes</label><label><input type="radio" name="sponsor">No</label></fieldset>
                    <input type="hidden" name="token"><button type="submit">Submit</button>
                    </form>''')
                fields = questions_from_rendered_page(page)
                self.assertEqual([q.label for q in fields], ['Email', 'Cover letter', 'Source', 'Sponsorship'])
                self.assertTrue(all(q.required for q in fields))
                self.assertEqual(fields[1].kind, 'file')
                self.assertEqual(fields[2].options, ('LinkedIn',))
                self.assertEqual(fields[3].options, ('Yes', 'No'))
                page.set_content('<input required>')
                with self.assertRaises(Exception):
                    questions_from_rendered_page(page)
                page.set_content('<label for="custom">Location</label><input id="custom" role="combobox">')
                with self.assertRaises(Exception):
                    questions_from_rendered_page(page)
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
