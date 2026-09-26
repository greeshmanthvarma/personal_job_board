import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from applications.cli import main, poll_boards
from applications.log import ApplicationLog
from applications.models import Record

class DiscoveryOnlyTests(unittest.TestCase):
    def test_submission_command_is_removed(self):
        with self.assertRaises(SystemExit) as error:
            main(['submit', '--portal', 'ashby', '--job-id', '123'])
        self.assertEqual(error.exception.code, 2)

    def test_poll_leaves_existing_draft_unsent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root/'data'
            log = ApplicationLog(data/'applications.csv')
            log.append(Record('now','ashby','123','Engineer','Example','https://jobs.ashbyhq.com/example/123','drafted','ready'))
            with patch('applications.cli.load_boards', return_value=[]):
                self.assertEqual(poll_boards(root, data, None, None), 0)
            self.assertEqual(ApplicationLog(data/'applications.csv').rows[-1].stage, 'drafted')
