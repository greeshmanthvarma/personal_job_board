import tempfile
import unittest
from pathlib import Path
from applications.log import ApplicationLog
from applications.models import Record
from applications.tracking import update_tracking, load_tracking, export_tracking

class TrackingTests(unittest.TestCase):
    def test_tracking_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            ApplicationLog(data/'applications.csv').append(Record('now','ashby','123','=Company','Engineer','https://jobs.ashbyhq.com/company/123','drafted','ready'))
            first = update_tracking(data, 'ashby\t123', 'applied', '=note')
            second = update_tracking(data, 'ashby\t123', 'interviewing', '=note')
            self.assertEqual(first['applied_at'], second['applied_at'])
            self.assertEqual(load_tracking(data)['ashby\t123']['status'], 'interviewing')
            self.assertIn(b"'=note", export_tracking(data))
            with self.assertRaises(ValueError):
                update_tracking(data, 'ashby\t123', 'submitted', '')
            with self.assertRaises(ValueError):
                update_tracking(data, 'ashby\tunknown', 'saved', '')
