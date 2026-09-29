import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch
from applications.server import make_server
from applications.proxy import ProxyError
from applications.snapshots import create_snapshot
from applications.hosted_http import hosted_post
from applications.http import NetworkError
from applications.jev import ENDPOINT

class FinishTests(unittest.TestCase):
    def test_failed_snapshot_is_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();target=root/'backup.tar.gz'
            with patch('applications.snapshots.tarfile.open',side_effect=OSError('disk error')):
                with self.assertRaises(OSError):create_snapshot(data,target)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()),[data])

    def test_assessment_redirect_is_rejected(self):
        opener=Mock();opener.open.side_effect=urllib.error.HTTPError(ENDPOINT,302,'redirect',{},None)
        with patch('applications.hosted_http.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(NetworkError):hosted_post(ENDPOINT,{}, {'Authorization':'private-token'})

    def test_local_proxy_origin_and_no_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);client=Mock();client.request.side_effect=ProxyError(504,'Remote timeout')
            server=make_server(data,0,remote_client=client)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            try:
                for supplied,expected in [('https://evil.example',403),(origin,504)]:
                    req=urllib.request.Request(origin+'/api/tracking',data=json.dumps({'identity':'ashby\t1','status':'applied','notes':''}).encode(),headers={'Origin':supplied,'Content-Type':'application/json'})
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
                    self.assertEqual(error.exception.code,expected);error.exception.close()
                self.assertEqual(client.request.call_count,1)
                client.request.side_effect=None
                client.request.return_value=(200, json.dumps({'description':'<p>Build <strong>software</strong>.</p><script>bad()</script>','assessment':''}).encode(), 'application/json; charset=utf-8')
                with urllib.request.urlopen(urllib.request.Request(origin+'/api/jobs/detail?identity=greenhouse%099')) as response:
                    description=json.loads(response.read())['description']
                self.assertEqual(description,'Build software.')
                self.assertNotIn('bad()', description)
                self.assertFalse((data/'tracking.json').exists())
            finally:
                server.shutdown();server.server_close();thread.join()
