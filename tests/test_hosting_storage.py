import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from applications.storage import atomic_json
from applications.snapshots import create_snapshot,restore_snapshot,daily_snapshot
from applications.schedule import BoardState,select_due
from applications.models import Board

class HostingStorageTests(unittest.TestCase):
    def test_crash_before_replace_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'jobs.json';atomic_json(path,{'old':True})
            with patch('applications.storage.os.replace',side_effect=OSError('crash')):
                with self.assertRaises(OSError):atomic_json(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'old':True})
            self.assertEqual([p.name for p in Path(tmp).iterdir()],['jobs.json'])
    def test_snapshot_restore_and_secret_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir()
            atomic_json(data/'tracking.json',{'ashby\t1':{'status':'applied','notes':'remember','applied_at':'2026-09-26T00:00:00Z'}})
            (data/'profile.md').write_text('SECRET PROFILE')
            target=root/'backup.tar.gz'
            manifest=create_snapshot(data,target)
            self.assertNotIn('profile.md',manifest['files'])
            restore_snapshot(target,root/'restored')
            self.assertEqual((root/'restored/tracking.json').read_text(),(data/'tracking.json').read_text())
            with self.assertRaises(ValueError):restore_snapshot(target,root/'restored')
    def test_daily_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            for day in range(1,10):daily_snapshot(data,f'2026-09-{day:02}')
            self.assertEqual(len(list((data/'backups').iterdir())),7)
    def test_fair_selection_borrows_unused_slots(self):
        now=datetime(2026,9,26,tzinfo=timezone.utc)
        boards=[Board('ashby',str(n),str(n)) for n in range(8)]
        states={b.key:BoardState(next_check='2026-09-01T00:00:00Z',hiring_engineers=i<4) for i,b in enumerate(boards)}
        selected=select_due(boards,states,now,4)
        self.assertEqual(sum(states[b.key].hiring_engineers for b in selected),2)
        self.assertEqual(len(select_due(boards[:3],states,now,4)),3)
