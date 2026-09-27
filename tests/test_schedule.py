import unittest
from datetime import datetime, timedelta, timezone
from applications.schedule import BoardState, advance, stamp


class AdaptiveScheduleTests(unittest.TestCase):
    def test_strong_matches_promote_and_remain_hourly(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        state = advance(None, ok=True, job_count=10, now=now, status='200', strong_match=True)
        self.assertTrue(state.proven_source)
        self.assertEqual(state.next_check, stamp(now + timedelta(hours=1)))
        state = advance(state, ok=True, job_count=1, now=now, status='200')
        self.assertEqual(state.next_check, stamp(now + timedelta(hours=1)))

    def test_empty_and_failure_backoff_override_priority(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        proven = BoardState(proven_source=True)
        empty = advance(proven, ok=True, job_count=0, now=now, status='200')
        self.assertEqual(empty.next_check, stamp(now + timedelta(days=1)))
        failed = advance(proven, ok=False, job_count=0, now=now, status='timeout')
        self.assertEqual(failed.next_check, stamp(now + timedelta(hours=6)))
        for _ in range(2):
            failed = advance(failed, ok=False, job_count=0, now=now, status='timeout')
        self.assertEqual(failed.next_check, stamp(now + timedelta(days=7)))
        self.assertTrue(failed.proven_source)

    def test_unproven_active_boards_keep_six_hours(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        state = advance(None, ok=True, job_count=10, now=now, status='200')
        self.assertEqual(state.next_check, stamp(now + timedelta(hours=6)))
