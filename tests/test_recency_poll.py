import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from applications.cli import poll_boards
from applications.models import Board, JobPosting
from applications.portals import BoardFetch
from applications.pipeline import recent_posting

class RecencyPollTests(unittest.TestCase):
    def test_boundaries_missing_future_and_naive(self):
        now=datetime(2026,9,26,tzinfo=timezone.utc)
        self.assertTrue(recent_posting(now-timedelta(days=7),now))
        self.assertFalse(recent_posting(now-timedelta(days=7,microseconds=1),now))
        self.assertFalse(recent_posting(None,now))
        self.assertFalse(recent_posting(now+timedelta(seconds=1),now))
        self.assertTrue(recent_posting(now.replace(tzinfo=None),now))

    def test_only_fresh_jobs_use_detail_and_assessment_budget(self):
        now=datetime(2026,9,26,tzinfo=timezone.utc)
        board=Board('ashby','Example','example')
        dates=[now-timedelta(days=1),now-timedelta(days=8),None,now+timedelta(days=1)]
        jobs=tuple(JobPosting('ashby',str(i),'Software Engineer','Example','United States','https://example.com',description_text='Build software',posted_at=date) for i,date in enumerate(dates))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir()
            (data/'tracking.json').write_text(json.dumps({'ashby\t1':{'status':'applied','notes':'Keep me','applied_at':'2026-09-20','updated_at':'2026-09-20'}}))
            original=(data/'tracking.json').read_bytes()
            with patch.dict(os.environ,{'TYPESAFE_API_KEY':'dummy','PROFILE_TEXT':'test profile','APPLICATIONS_HOSTED':'0'}),patch('applications.cli.utc_now',return_value=now),patch('applications.cli.load_boards',return_value=[board]),patch('applications.cli.fetch_board',return_value=BoardFetch(True,'200',jobs,'')),patch('applications.cli._hydrate',side_effect=lambda b,j,g:j) as hydrate,patch('applications.cli.evaluate',return_value=SimpleNamespace(reason='match')) as evaluate:
                self.assertEqual(poll_boards(root,data,None,None),0)
                self.assertEqual(hydrate.call_count,1)
                self.assertEqual(evaluate.call_count,1)
                self.assertEqual(evaluate.call_args.args[3].external_job_id,'0')
            self.assertEqual((data/'tracking.json').read_bytes(),original)
            listings=json.loads((data/'jobs.json').read_text())
            self.assertTrue(listings['ashby\t1']['is_listed'])
