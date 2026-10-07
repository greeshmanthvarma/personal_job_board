import json
import tempfile
import unittest
import importlib.util
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from applications.answers import model_prompt, plan_answer
from applications.browser import questions_from_rendered_page
from applications.eligibility import eligibility_reason
from applications.keywords import location_decision
from applications.log import ApplicationLog
from applications.models import Question, Record, JobPosting
from applications.models import Board
from applications.portals import parse_ashby_jobs
from applications.pipeline import keyword_stage
from applications.page import _document
from applications.http import get_bytes, post_json, NetworkError
from applications.cli import poll_boards
from applications.portals import BoardFetch


class RegressionTests(unittest.TestCase):
    def test_scan_continues_after_failed_board_and_records_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'data'
            boards = [Board('ashby','One','one'), Board('ashby','Two','two')]
            with patch('applications.cli.load_boards', return_value=boards), patch('applications.cli.fetch_board', side_effect=[NetworkError('read timed out'), BoardFetch(True,'200',(), '')]) as fetch:
                self.assertEqual(poll_boards(root, data, None, None), 0)
                self.assertEqual(fetch.call_count, 2)
            state = json.loads((data/'scan-state.json').read_text())
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['processed_boards'], 2)
            self.assertIn('Jobs screened', (data/'applications.html').read_text())

    def test_unexpected_failure_updates_dashboard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root/'data'
            with patch('applications.cli.load_boards', return_value=[Board('ashby','One','one')]), patch('applications.cli.fetch_board', side_effect=ValueError('fixture failure')):
                with self.assertRaises(ValueError):
                    poll_boards(root,data,None,None)
            self.assertEqual(json.loads((data/'scan-state.json').read_text())['status'], 'failed')
            self.assertIn('Scan: Failed', (data/'applications.html').read_text())

    def test_read_timeouts_are_network_errors(self):
        for call in (lambda: get_bytes('https://example.test'), lambda: post_json('https://example.test', {}, {})):
            response = MagicMock()
            response.__enter__.return_value.read.side_effect = TimeoutError('read timed out')
            with patch('urllib.request.urlopen', return_value=response):
                with self.assertRaises(NetworkError):
                    call()

    def test_dashboard_shows_progress_without_matching_jobs(self):
        page = _document([], {}, summary={'screened': 100, 'rejected': 100, 'boards': 10, 'evaluated': 0}, run={'status': 'failed', 'message': 'Read timeout', 'processed_boards': 10, 'target_boards': 100})
        self.assertIn('Jobs screened', page)
        self.assertIn('Rejected', page)
        self.assertIn('Read timeout', page)
        self.assertIn('Failed', page)

    def test_ashby_structured_location_and_secondary_us(self):
        board = Board('ashby', 'Example', 'example')
        for country, expected in [('USA', 'pass'), ('DEU', 'reject')]:
            item = {'title': 'Software Engineer', 'location': 'Office', 'jobUrl': 'https://jobs.ashbyhq.com/example/1', 'address': {'postalAddress': {'addressCountry': country}}}
            posting = parse_ashby_jobs({'jobs': [item]}, board)[0]
            self.assertEqual(location_decision(posting.location).action, expected)
        item['secondaryLocations'] = [{'location': 'SF Office', 'address': {'postalAddress': {'addressCountry': 'USA'}}}]
        self.assertEqual(location_decision(parse_ashby_jobs({'jobs': [item]}, board)[0].location).action, 'pass')

    def test_targeted_location_recheck_preserves_other_skips(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'applications.csv'
            log = ApplicationLog(path)
            for job_id, stage, reason, model in [('1', 'jev_no', "uncertain: location does not state United States eligibility ('SF Office')", ''), ('2', 'drafted', 'done', ''), ('3', 'jev_no', 'uncertain: level', 'jev-1.13.0'), ('4', 'submitted', 'done', '')]:
                log.append(Record('now', 'ashby', job_id, 'Engineer', 'Example', f'https://jobs.ashbyhq.com/example/{job_id}', stage, reason, model))
            retry = ApplicationLog(path, recheck_location=True)
            self.assertFalse(retry.contains('ashby', '1'))
            self.assertFalse(retry.retryable('ashby', '1'))  # age cutoff still enforced
            self.assertTrue(retry.recheck_board(Board('ashby', 'Example', 'example')))
            for job_id in ('2', '3', '4'):
                self.assertTrue(retry.contains('ashby', job_id))
            retry.append(Record('later', 'ashby', '1', 'Engineer', 'Example', 'url', 'keyword_reject', 'stale'))
            self.assertTrue(retry.contains('ashby', '1'))
            self.assertFalse(retry.recheck_board(Board('ashby', 'Example', 'example')))

    def test_location_aliases_through_screening(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        for location in ('SF Office', 'San Francisco Office', 'SF Bay Area', 'Sunnyvale', 'Palo Alto'):
            job = JobPosting('ashby', 'fixture', 'Junior Software Engineer', 'Example', location, 'url', posted_at=now)
            self.assertIsNone(keyword_stage(job, now), location)
        for location in ('Indonesia', 'Thailand', 'Vietnam', 'Philippines', 'Hong Kong', 'Austria', 'Malaysia', 'Taipei, Taiwan', 'Remote AUS'):
            self.assertEqual(location_decision(location).action, 'reject', location)

    def test_unknown_location_still_checks_posting_age(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        job = JobPosting('ashby', 'fixture', 'Software Engineer', 'Example', 'Remote', 'url', posted_at=now-timedelta(days=3))
        self.assertEqual(keyword_stage(job, now)[0], 'keyword_reject')

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
        self.assertIsNone(eligibility_reason('Candidates must be based in London.'))
        self.assertIsNotNone(eligibility_reason('Candidates must be based in London, United Kingdom.'))

    def test_uploads_are_distinct(self):
        self.assertEqual(plan_answer(Question('Resume', True, kind='file')).answer, 'resume.pdf')
        self.assertEqual(plan_answer(Question('Cover letter', True, kind='file')).kind, 'blocked')
        self.assertEqual(plan_answer(Question('Portfolio document', False, kind='file')).kind, 'omitted')

    def test_authorization_and_expiration_are_not_guessed(self):
        for label in ('Are you eligible for STEM OPT?', 'Describe your visa status and expiration date', 'Are you authorized to work and when does your authorization expire?'):
            self.assertEqual(plan_answer(Question(label, True)).kind, 'blocked')
        for label in ('Are you currently authorized to work in the US?', 'Are you legally authorised to work for any employer?'):
            self.assertEqual(plan_answer(Question(label, True, ('Yes', 'No'))).answer, 'Yes')
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
                page.set_content('''<div class="ashby-application-form-autofill-input-root"><input type="file" style="clip-path:inset(50%);width:1px;height:1px"></div>
                  <div class="ashby-application-form-field-entry"><label>Resume</label><input type="file" style="clip-path:inset(50%);width:1px;height:1px"></div>
                  <div class="ashby-application-form-field-entry"><label>Pronouns</label><label><input type="checkbox">He/him</label><label><input type="checkbox">They/them</label></div>
                  <div class="ashby-application-form-field-entry"><label>Sponsorship<span>*</span></label><button type="button">Yes</button><button type="button">No</button></div>''')
                fields = questions_from_rendered_page(page)
                self.assertEqual([q.label for q in fields], ['Resume', 'Pronouns', 'Sponsorship'])
                self.assertEqual(fields[0].kind, 'file')
                self.assertEqual(fields[1].options, ('He/him', 'They/them'))
                self.assertEqual(fields[1].kind, 'multiselect')
                self.assertEqual(fields[2].options, ('Yes', 'No'))
                self.assertTrue(fields[2].required)
                page.set_content('''<div class="ashby-application-form-field-entry"><label for="state">State</label><input id="state" role="combobox" aria-controls="states" onclick="document.getElementById('states').hidden=false" onkeydown="if(event.key==='Escape')document.getElementById('states').hidden=true"><div id="states" role="listbox" hidden><div role="option">California</div><div role="option">New York</div></div></div>''')
                fields = questions_from_rendered_page(page)
                self.assertEqual(fields[0].options, ('California', 'New York'))
                self.assertEqual(page.locator('#state').input_value(), '')
                page.set_content('<div class="ashby-application-form-field-entry"><label class="_required_label">State</label><input role="combobox" aria-autocomplete="list"></div>')
                fields = questions_from_rendered_page(page)
                self.assertEqual(fields[0].kind, 'autocomplete')
                self.assertTrue(fields[0].required)
                self.assertEqual(fields[0].options, ())
                page.set_content('''<div class="ashby-application-form-field-entry"><label>Phone</label><input type="tel" required><div class="ashby-application-form-texting-consent-description"><label><input name="consent" type="radio">Yes</label><label><input name="consent" type="radio">No</label></div></div><fieldset class="ashby-application-form-input-radio-group"><label>Source</label><label><input type="radio" name="source">LinkedIn</label><label><input type="radio" name="source">Other</label></fieldset>''')
                fields = questions_from_rendered_page(page)
                self.assertEqual(fields[0].label, 'Phone')
                self.assertEqual(fields[0].options, ())
                self.assertEqual(next(q for q in fields if q.label=='Source').options, ('LinkedIn', 'Other'))
                consent = next(q for q in fields if 'Consent' in q.label)
                self.assertEqual(plan_answer(consent).kind, 'omitted')
                rows = [Record('now','ashby','1','AI Engineer','Example','url','drafted','retrieval'), Record('now','ashby','2','Frontend Engineer','Other','url','drafted','UI')]
                page.set_content(_document(rows, {}))
                page.get_by_role('button', name='Drafted (2)', exact=True).click()
                page.get_by_label('Search company, role, portal, or reason').fill('retrieval')
                self.assertEqual(page.locator('tbody tr:visible').count(), 1)
                page.locator('#search').fill('no match')
                self.assertEqual(page.locator('tbody tr:visible').count(), 0)
                self.assertIn('No matches', page.locator('#empty').inner_text())
                page.locator('#search').fill('')
                self.assertEqual(page.locator('tbody tr:visible').count(), 2)
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
