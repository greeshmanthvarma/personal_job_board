import unittest
from datetime import datetime, timedelta, timezone
from applications.schedule import BoardState, advance, stamp


class AdaptiveScheduleTests(unittest.TestCase):
    def test_engineer_hiring_is_hourly_only_while_it_lasts(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        state = advance(None, ok=True, job_count=10, now=now, status='200', hiring_engineers=True)
        self.assertTrue(state.hiring_engineers)
        self.assertEqual(state.next_check, stamp(now + timedelta(hours=1)))
        state = advance(state, ok=True, job_count=1, now=now, status='200', hiring_engineers=True)
        self.assertEqual(state.next_check, stamp(now + timedelta(hours=1)))
        cooled = advance(state, ok=True, job_count=4, now=now, status='200', hiring_engineers=False)
        self.assertFalse(cooled.hiring_engineers)
        self.assertEqual(cooled.next_check, stamp(now + timedelta(hours=6)))

    def test_empty_and_failure_backoff_override_priority(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        hiring = BoardState(hiring_engineers=True)
        empty = advance(hiring, ok=True, job_count=0, now=now, status='200', hiring_engineers=True)
        self.assertEqual(empty.next_check, stamp(now + timedelta(days=1)))
        self.assertFalse(empty.hiring_engineers)
        failed = advance(hiring, ok=False, job_count=0, now=now, status='timeout')
        self.assertEqual(failed.next_check, stamp(now + timedelta(hours=6)))
        for _ in range(2):
            failed = advance(failed, ok=False, job_count=0, now=now, status='timeout')
        self.assertEqual(failed.next_check, stamp(now + timedelta(days=7)))
        self.assertTrue(failed.hiring_engineers)

    def test_other_active_boards_keep_six_hours(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        state = advance(None, ok=True, job_count=10, now=now, status='200')
        self.assertFalse(state.hiring_engineers)
        self.assertEqual(state.next_check, stamp(now + timedelta(hours=6)))
