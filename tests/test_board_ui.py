import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from applications.models import JobPosting, Board
from applications.listings import save_listings
from applications.server import make_server
from applications.tracking import load_tracking

class BoardTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.data=Path(self.folder.name)
        save_listings(self.data,[JobPosting('ashby','123','Software Engineer','Example','USA','https://jobs.ashbyhq.com/example/123','Build software')],'2026-09-26T00:00:00Z',board=Board('ashby','Example','example'))
        self.server=make_server(self.data,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()
    def request(self,path,body=None,origin=None):
        headers={'Content-Type':'application/json','Origin':origin or self.url}
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        return urllib.request.urlopen(req)
    def test_cross_origin_tracking_write_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/tracking',{'identity':'ashby\t123','status':'applied','notes':''},origin='https://evil.example')
        self.assertEqual(error.exception.code,403)
        self.assertEqual(load_tracking(self.data),{})
    def test_server_does_not_expose_private_files(self):
        for path in ('/.env','/profile.md','/data/tracking.json','/../resume.pdf'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code,404)
    def test_status_note_reload_and_export(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as runtime:
            browser=runtime.chromium.launch()
            try:
                page=browser.new_page(viewport={'width':1200,'height':900})
                page.goto(self.url)
                page.locator('article').wait_for()
                page.get_by_label('Tracking status').select_option('applied')
                page.get_by_label('Notes',exact=True).fill('Phone screen Friday')
                page.get_by_role('button',name='Save tracking').click()
                page.get_by_role('status').filter(has_text='Saved').wait_for()
                page.reload()
                page.locator('article').wait_for()
                self.assertEqual(page.get_by_label('Tracking status').input_value(),'applied')
                self.assertEqual(page.get_by_label('Notes',exact=True).input_value(),'Phone screen Friday')
                with self.request('/api/export') as response:
                    self.assertIn(b'Phone screen Friday',response.read())
                page.screenshot(path='/private/tmp/job-board-desktop.png',full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                page.screenshot(path='/private/tmp/job-board-mobile.png',full_page=True)
            finally:
                browser.close()
    def test_open_link_does_not_mark_applied(self):
        with self.request('/') as response:
            self.assertIn(b'Open application',response.read())
        self.assertEqual(load_tracking(self.data),{})
