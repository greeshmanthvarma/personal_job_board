import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from applications.hosting import config_from_env, PollWorker

class HostingTests(unittest.TestCase):
    def test_config_requires_secrets_and_mount(self):
        with tempfile.TemporaryDirectory() as tmp:
            env={'BOARD_API_TOKEN':'x'*40,'DATA_DIR':tmp,'RAILWAY_VOLUME_MOUNT_PATH':tmp,'PORT':'8080'}
            self.assertEqual(config_from_env(env).data,Path(tmp))
            for key in ('BOARD_API_TOKEN','DATA_DIR','RAILWAY_VOLUME_MOUNT_PATH'):
                bad=dict(env);bad.pop(key)
                with self.assertRaises(ValueError):config_from_env(bad)
            env['TYPESAFE_API_KEY']='private'
            with self.assertRaises(ValueError):config_from_env(env)
    def test_worker_no_overlap_and_immediate_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=config_from_env({'BOARD_API_TOKEN':'x'*40,'DATA_DIR':tmp,'RAILWAY_VOLUME_MOUNT_PATH':tmp})
            clock=[0];child=Mock();child.poll.return_value=None;spawn=Mock(return_value=child)
            worker=PollWorker(Path(tmp),config,spawn,lambda:clock[0])
            worker.tick();worker.tick();self.assertEqual(spawn.call_count,1)
            clock[0]=1201;worker.tick();child.send_signal.assert_called_once()
            child.poll.return_value=1;worker.tick();self.assertEqual(worker.state['last_error'],'scan_failed')
            worker.tick();self.assertEqual(spawn.call_count,2)
