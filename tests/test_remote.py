import json
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from applications.remote import make_remote_server

TOKEN='test-token-'+'x'*40
class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.data=Path(self.tmp.name)
        (self.data/'jobs.json').write_text(json.dumps({'ashby\t1':{'identity':'ashby\t1','company':'Example','title':'Engineer','portal':'ashby','job_id':'1','location':'US','link':'https://example.com','is_listed':True}}))
        self.server=make_remote_server(self.data,TOKEN,0,'127.0.0.1')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,token=TOKEN,body=None,origin=None):
        headers={'Authorization':f'Bearer {token}'} if token else {}
        if origin:headers['Origin']=origin
        if body is not None:headers['Content-Type']='application/json'
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req) as response:return response.status,response.read()
        except urllib.error.HTTPError as error:
            with error:return error.code,error.read()
    def test_auth_and_origin(self):
        self.assertEqual(self.request('/api/v1/jobs',token='')[0],401)
        self.assertEqual(self.request('/api/v1/jobs',token='bad')[0],401)
        self.assertEqual(self.request('/api/v1/jobs',origin='https://evil.example')[0],403)
        self.assertEqual(self.request('/api/v1/jobs')[0],200)
    def test_health_and_private_paths(self):
        self.assertEqual(self.request('/healthz',token=''),(200,b'{"ok": true}'))
        for path in ['/','/profile.md','/.env']:
            self.assertEqual(self.request(path)[0],404)
    def test_tracking_and_export(self):
        body={'identity':'ashby\t1','status':'applied','notes':'private test note'}
        self.assertEqual(self.request('/api/v1/tracking',body=body)[0],200)
        self.assertEqual(json.loads((self.data/'tracking.json').read_text())['ashby\t1']['status'],'applied')
        self.assertIn(b'private test note',self.request('/api/v1/export')[1])
        body['identity']='unknown';self.assertEqual(self.request('/api/v1/tracking',body=body)[0],400)
    def test_paged_jobs_leave_descriptions_for_detail(self):
        posted = datetime.now(timezone.utc).isoformat()
        (self.data/'jobs.json').write_text(json.dumps({'ashby\t1':{'identity':'ashby\t1','company':'Example','title':'Engineer','portal':'ashby','job_id':'1','location':'US','link':'https://example.com','is_listed':True,'description':'SECRET DESCRIPTION','posted_at':posted}}))
        status, body = self.request('/api/v1/jobs?status=new&limit=40')
        self.assertEqual(status, 200)
        page = json.loads(body)
        self.assertEqual(page['total'], 1)
        self.assertNotIn('description', page['jobs'][0])
        self.assertNotIn(b'SECRET', body)
        status, body = self.request('/api/v1/jobs/detail?identity=' + quote('ashby\t1'))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['description'], 'SECRET DESCRIPTION')
        self.assertEqual(self.request('/api/v1/jobs?status=nope')[0], 400)
    def test_corruption_is_sanitized(self):
        (self.data/'jobs.json').write_text('PRIVATE invalid json')
        status,body=self.request('/api/v1/jobs')
        self.assertEqual(status,503);self.assertNotIn(b'PRIVATE',body)
