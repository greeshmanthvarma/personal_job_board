import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from applications.models import Question, Record, Board, JobPosting
from applications.log import ApplicationLog, save_draft, load_records
from applications.submission import begin_attempt, finish_attempt, run_submission, SubmissionBlocked, execution_lock, review_preclick_attempt
from applications.ashby_submit import validate_snapshot, confirmation_text
from applications.ashby_submit import submit_ashby, fill_ashby
from applications.cli import submit_workflow_draft, poll_boards
from applications.portals import BoardFetch
from applications.portals import parse_ashby_jobs

FORM = '''<div class="ashby-application-form-field-entry"><label class="ashby-application-form-question-title">Name*</label><input required></div><button onclick="document.body.innerHTML='<p>Your application has been received</p>'">Submit application</button>'''

def fixture_draft(kind='text'):
    return {'questions': [{'label': 'Name', 'required': True, 'kind': kind, 'options': []}], 'fields': [{'label': 'Name', 'required': True, 'kind': 'answered', 'answer': 'Greeshmanth'}]}


class SubmissionTests(unittest.TestCase):
    def test_review_never_allows_retry_of_unknown_clicked_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            begin_attempt(data, 'ashby\t123', {})
            finish_attempt(data, 'ashby\t123', 'unknown', {'clicking_at': 'now'})
            with self.assertRaises(SubmissionBlocked):
                review_preclick_attempt(data, 'ashby\t123', 'retry')
            with self.assertRaises(SubmissionBlocked):
                begin_attempt(data, 'ashby\t123', {})
    def test_ashby_yesno_buttons_take_precedence_over_hidden_checkbox(self):
        from playwright.sync_api import sync_playwright
        html = '''<div class="ashby-application-form-field-entry"><label class="ashby-application-form-question-title">Authorized*</label><button class="ashby-application-form-input-yesno-option" aria-pressed="false" onclick="this.setAttribute('aria-pressed','true')">Yes</button><button class="ashby-application-form-input-yesno-option" aria-pressed="false">No</button><input type="checkbox" style="display:none"></div>'''
        draft = {'questions': [{'label': 'Authorized', 'required': True, 'kind': 'text', 'options': ['Yes', 'No']}], 'fields': [{'label': 'Authorized', 'required': True, 'kind': 'answered', 'answer': 'Yes'}]}
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html)
                fill_ashby(page, draft, Path('resume.pdf'))
                self.assertEqual(page.get_by_role('button', name='Yes', exact=True).get_attribute('aria-pressed'), 'true')
            finally:
                browser.close()
    def test_ashby_id_and_legacy_log_dedup_use_same_uuid(self):
        job_id = 'bfcfbd07-03b9-4e7c-82b1-b17d7c3a5e90'
        url = f'https://jobs.ashbyhq.com/Ambral/{job_id}'
        job = parse_ashby_jobs({'jobs': [{'jobUrl': url, 'title': 'Software Engineer'}]}, Board('ashby', 'Ambral', 'Ambral'))[0]
        self.assertEqual(job.external_job_id, job_id)
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            log = ApplicationLog(data/'applications.csv')
            log.append(Record('now', 'ashby', url, 'Engineer', 'Ambral', url, 'submitted', 'old record'))
            self.assertTrue(ApplicationLog(data/'applications.csv').contains('ashby', job_id))
    def test_poll_workflow_discovers_drafts_submits_and_stops_at_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root/'data'
            board = Board('ashby', 'Example', 'example')
            jobs = tuple(JobPosting('ashby', str(i), 'Software Engineer', 'Example', 'USA', f'https://jobs.ashbyhq.com/example/{i}', 'Build software') for i in (1, 2))
            draft = {'stage': 'drafted', 'fields': [], 'questions': []}
            def consider(job, *args, **kwargs):
                return [Record('now', 'ashby', job.external_job_id, job.title, job.company, job.link, 'drafted', 'ready')], draft
            def submit(url, draft, resume, before_click, evidence_dir):
                before_click()
                return {'status': 'confirmed', 'confirmation': 'Your application has been received'}
            with patch('applications.cli.load_boards', return_value=[board]), patch('applications.cli.fetch_board', return_value=BoardFetch(True, '200', jobs, '')), patch('applications.cli._consider_one', side_effect=consider) as prepare, patch('applications.ashby_submit.submit_ashby_url', side_effect=submit) as send:
                poll_boards(root, data, None, None, submit_limit=1)
            self.assertEqual(prepare.call_count, 1)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(load_records(data/'applications.csv')[-1].stage, 'submitted')
            self.assertIn('Submission attempt limit', json.loads((data/'scan-state.json').read_text())['message'])

    def test_poll_draft_only_does_not_send(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root/'data'
            self.fixture(data)
            with patch('applications.cli.load_boards', return_value=[]), patch('applications.ashby_submit.submit_ashby_url') as send:
                self.assertEqual(poll_boards(root, data, None, None, draft_only=True), 0)
            send.assert_not_called()
            self.assertEqual(load_records(data/'applications.csv')[-1].stage, 'drafted')

    def test_workflow_submits_complete_draft_and_reloads_latest_status(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)/'data'
            self.fixture(data)
            log = ApplicationLog(data/'applications.csv')
            row = log.rows[-1]
            def submit(url, draft, resume, before_click, evidence_dir):
                before_click()
                return {'status': 'confirmed', 'confirmation': 'Your application has been received'}
            with patch('applications.submission.render_page'), patch('applications.submission.load_run', return_value={'status': 'running'}):
                submit_workflow_draft(Path(folder), data, row, submitter=submit)
            self.assertEqual(load_records(data/'applications.csv')[-1].stage, 'submitted')

    def test_workflow_does_not_submit_unsupported_portal(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)/'data'
            log = ApplicationLog(data/'applications.csv')
            row = Record('now', 'greenhouse', '123', 'Engineer', 'Example', 'https://example.test', 'drafted', 'ready')
            log.append(row)
            self.assertFalse(submit_workflow_draft(Path(folder), data, row))
            self.assertEqual(load_records(data/'applications.csv')[-1].stage, 'drafted')
    def test_execution_lock_excludes_another_command(self):
        with tempfile.TemporaryDirectory() as folder:
            with execution_lock(Path(folder)):
                with self.assertRaises(SubmissionBlocked):
                    with execution_lock(Path(folder)):
                        self.fail('Second lock acquired')

    def test_browser_click_without_confirmation_stays_unknown(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(FORM.replace("document.body.innerHTML='<p>Your application has been received</p>'", "document.body.innerHTML='<p>Please wait</p>'"))
                clicks = []
                clock = iter([0, 1, 40])
                with patch('applications.ashby_submit.time', SimpleNamespace(monotonic=lambda: next(clock))):
                    result = submit_ashby(page, fixture_draft(), Path(folder)/'resume.pdf', lambda: clicks.append(True), Path(folder))
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(clicks, [True])
            finally:
                browser.close()

    def test_local_browser_confirmation_and_unsupported_control(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(FORM)
                clicks = []
                result = submit_ashby(page, fixture_draft(), Path(folder)/'resume.pdf', lambda: clicks.append(True), Path(folder))
                self.assertEqual(result['status'], 'confirmed')
                self.assertEqual(clicks, [True])
                page.set_content(FORM.replace('<input required>', '<input required role="combobox" aria-autocomplete="list">'))
                clicks.clear()
                with self.assertRaises(SubmissionBlocked):
                    submit_ashby(page, fixture_draft('autocomplete'), Path(folder)/'resume.pdf', lambda: clicks.append(True), Path(folder))
                self.assertEqual(clicks, [])
            finally:
                browser.close()
    def test_attempt_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            begin_attempt(data, 'ashby\t123', {'url': 'https://example.test'})
            finish_attempt(data, 'ashby\t123', 'clicking', {})
            with self.assertRaises(SubmissionBlocked):
                begin_attempt(data, 'ashby\t123', {})

    def test_changed_questions_block_submission(self):
        draft = {'questions': [{'label': 'Name', 'required': True, 'kind': 'text', 'options': []}], 'fields': [{'label': 'Name', 'required': True, 'kind': 'answered', 'answer': 'Name'}]}
        validate_snapshot([Question('Name', True)], draft)
        with self.assertRaises(SubmissionBlocked):
            validate_snapshot([Question('New question', True)], draft)
        with self.assertRaises(SubmissionBlocked):
            validate_snapshot([Question('Name', True)], {})

    def test_click_without_confirmation_is_unknown(self):
        self.assertIsNone(confirmation_text('Thank you for your interest. Apply now'))
        self.assertIsNone(confirmation_text('Application submitted'))
        self.assertEqual(confirmation_text('Your application has been received'), 'Your application has been received')

    def fixture(self, data):
        log = ApplicationLog(data/'applications.csv')
        log.append(Record('now', 'ashby', '123', 'Engineer', 'Example', 'https://jobs.ashbyhq.com/example/123', 'drafted', 'ready'))
        save_draft(data/'drafts.json', 'ashby\t123', {'stage': 'drafted', 'fields': [], 'questions': []})

    def test_confirmed_attempt_creates_submitted_record(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            self.fixture(data)
            def submit(url, draft, resume, before_click, evidence_dir):
                before_click()
                return {'status': 'confirmed', 'confirmation': 'Your application has been received', 'url': url}
            with patch('applications.submission.load_run', return_value={}), patch('applications.submission.render_page'):
                self.assertEqual(run_submission(data, data/'resume.pdf', 'ashby', '123', submitter=submit), 0)
            self.assertEqual(load_records(data/'applications.csv')[-1].stage, 'submitted')
            with self.assertRaises(SubmissionBlocked):
                run_submission(data, data/'resume.pdf', 'ashby', '123', submitter=submit)

    def test_unknown_and_blocked_never_become_submitted(self):
        for status in ('unknown', 'blocked'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                data = Path(folder)
                self.fixture(data)
                def submit(url, draft, resume, before_click, evidence_dir):
                    if status == 'unknown':
                        before_click()
                    return {'status': status, 'reason': 'Needs review'}
                with patch('applications.submission.load_run', return_value={}), patch('applications.submission.render_page'):
                    self.assertEqual(run_submission(data, data/'resume.pdf', 'ashby', '123', submitter=submit), 2)
                self.assertEqual(load_records(data/'applications.csv')[-1].stage, 'blocked')

    def test_polling_blocks_submission(self):
        with tempfile.TemporaryDirectory() as folder, patch('applications.submission.load_run', return_value={'status': 'running'}):
            with self.assertRaises(SubmissionBlocked):
                run_submission(Path(folder), Path(folder)/'resume.pdf', 'ashby', '123')
