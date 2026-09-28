import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from applications.models import JobPosting, Board, Record
from applications.log import ApplicationLog
from urllib.parse import quote
from applications.listings import save_listings, list_board_jobs, ranking, board_page, board_job_detail
from unittest.mock import patch
from applications.cli import poll_boards
from applications.portals import BoardFetch

class ListingTests(unittest.TestCase):
    def test_experience_range_uses_minimum_not_maximum(self):
        from applications.eligibility import eligibility_reason
        self.assertIsNone(eligibility_reason('You have 1-7 years of experience building production software.'))
        self.assertIsNone(eligibility_reason('You have 2–4 years of software engineering experience.'))
        self.assertIn('years exclude',eligibility_reason('Requires 3-5 years of software engineering experience.'))
    def test_blended_ranking_and_missing_signals(self):
        now=datetime(2026,9,26,tzinfo=timezone.utc)
        reason=lambda value: '; '.join(f'{key} yes ({value})' for key in ('role_family','level','responsibilities','qualifications'))
        older={'posted_at':'2026-09-19T00:00:00Z','assessment':reason(.99)}
        newer={'posted_at':'2026-09-26T00:00:00Z','assessment':reason(.70)}
        self.assertGreater(ranking(older,now)[0],ranking(newer,now)[0])
        self.assertEqual(ranking({'assessment':'','posted_at':''},now),(0,0))

    def test_discovery_without_keys_keeps_older_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=root/'data'
            board=Board('ashby','Example','example')
            job=JobPosting('ashby','123','Software Engineer','Example','USA','https://jobs.ashbyhq.com/example/123','Build software',posted_at=datetime(2020,1,1,tzinfo=timezone.utc))
            with patch('applications.cli.load_boards',return_value=[board]), patch('applications.cli.fetch_board',return_value=BoardFetch(True,'200',(job,),'')), patch.dict('os.environ',{'TYPESAFE_API_KEY':'','OPENAI_API_KEY':''}), patch('applications.cli.evaluate') as jev:
                self.assertEqual(poll_boards(root,data,None,None),0)
            jev.assert_not_called()
            self.assertEqual(len(list_board_jobs(data)),1)

    def test_open_engineer_titles_poll_hourly_until_they_are_gone(self):
        from applications.schedule import load_schedule
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        board = Board('ashby', 'Example', 'example')
        engineer = JobPosting('ashby', '1', 'Software Engineer', 'Example', 'United States', 'https://jobs.ashbyhq.com/example/1', 'Build software', posted_at=now)
        sales = JobPosting('ashby', '2', 'Account Executive', 'Example', 'United States', 'https://jobs.ashbyhq.com/example/2', 'Sell software', posted_at=now)
        abroad = JobPosting('ashby', '3', 'Software Engineer', 'Example', 'London', 'https://jobs.ashbyhq.com/example/3', 'Build software', posted_at=now)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'data'
            with patch('applications.cli.utc_now', return_value=now), patch('applications.cli.load_boards', return_value=[board]), patch('applications.cli.fetch_board', return_value=BoardFetch(True, '200', (engineer, sales), '')), patch.dict('os.environ', {'TYPESAFE_API_KEY': '', 'OPENAI_API_KEY': ''}):
                self.assertEqual(poll_boards(root, data, None, None), 0)
            state = load_schedule(data / 'board-schedule.json')[board.key]
            self.assertTrue(state.hiring_engineers)
            self.assertEqual(state.next_check, '2026-09-26T01:00:00Z')
            later = now.replace(hour=1)
            with patch('applications.cli.utc_now', return_value=later), patch('applications.cli.load_boards', return_value=[board]), patch('applications.cli.fetch_board', return_value=BoardFetch(True, '200', (sales, abroad), '')), patch.dict('os.environ', {'TYPESAFE_API_KEY': '', 'OPENAI_API_KEY': ''}):
                self.assertEqual(poll_boards(root, data, None, None), 0)
            state = load_schedule(data / 'board-schedule.json')[board.key]
            self.assertFalse(state.hiring_engineers)
            self.assertEqual(state.next_check, '2026-09-26T07:00:00Z')

    def test_failed_board_does_not_close_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=root/'data'
            board=Board('ashby','Example','example')
            job=JobPosting('ashby','123','Software Engineer','Example','USA','https://jobs.ashbyhq.com/example/123','Build software')
            save_listings(data,[job],'now',board=board)
            with patch('applications.cli.load_boards',return_value=[board]), patch('applications.cli.fetch_board',return_value=BoardFetch(False,'timeout',(),'')):
                poll_boards(root,data,None,None)
            self.assertTrue(list_board_jobs(data)[0]['is_listed'])
    def test_older_jobs_and_scoped_scans(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            board = Board('ashby','Example','example')
            jobs = [JobPosting('ashby',str(i),'Software Engineer','Example','USA',f'https://jobs.ashbyhq.com/example/{i}','Build software',posted_at=datetime(2020,1,1,tzinfo=timezone.utc)) for i in (1,2)]
            save_listings(data,jobs,'now',board=board)
            self.assertEqual(len(list_board_jobs(data)),2)
            save_listings(data,jobs[:1],'later',board=board,complete=False)
            self.assertTrue(all(j['is_listed'] for j in list_board_jobs(data)))
            save_listings(data,jobs[:1],'later',board=board)
            self.assertFalse(next(j for j in list_board_jobs(data) if j['job_id']=='2')['is_listed'])

    def test_ambral_defaults_to_needs_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            ApplicationLog(data/'applications.csv').append(Record('now','ashby','123','Engineer','Ambral','https://jobs.ashbyhq.com/Ambral/123','blocked','No explicit employer confirmation; manual review required'))
            self.assertEqual(list_board_jobs(data)[0]['status'],'needs_verification')

    def test_page_keeps_descriptions_off_the_list(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        posted = datetime(2026, 9, 28, 6, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            board = Board('ashby', 'Example', 'example')
            jobs = [JobPosting('ashby', str(i), f'Software Engineer {i}', 'Example', 'USA', f'https://jobs.ashbyhq.com/example/{i}', 'SECRET DESCRIPTION', posted_at=posted) for i in range(45)]
            save_listings(data, jobs, 'now', board=board)
            page = board_page(data, 'status=new&limit=40', now)
            self.assertEqual((len(page['jobs']), page['total'], page['counts']['new']), (40, 45, 45))
            self.assertNotIn('description', page['jobs'][0])
            self.assertNotIn('SECRET', json.dumps(page))
            self.assertEqual(len(board_page(data, 'status=new&offset=40', now)['jobs']), 5)
            self.assertEqual(board_page(data, 'status=new&q=missing', now)['total'], 0)
            self.assertEqual(board_page(data, 'status=new', now.replace(day=6, month=10))['counts']['new'], 0)
            detail = board_job_detail(data, 'identity=' + quote(page['jobs'][0]['identity']))
            self.assertEqual(detail['description'], 'SECRET DESCRIPTION')
            with self.assertRaises(ValueError):
                board_page(data, 'status=new&limit=41', now)
            with self.assertRaises(LookupError):
                board_job_detail(data, 'identity=' + quote('ashby\tmissing'))
