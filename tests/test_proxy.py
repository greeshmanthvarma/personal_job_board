import io
import unittest
from unittest.mock import Mock
from applications.proxy import RemoteClient, ProxyError, validate_origin

TOKEN='x'*40
def resolver(*_args,**_kwargs):return [(None,None,None,None,('8.8.8.8',443))]
class Response(io.BytesIO):
    code=200
class ProxyTests(unittest.TestCase):
    def test_bad_config(self):
        for url in ['http://example.com','https://user:pw@example.com','https://127.0.0.1','https://example.com/api','https://example.com?token=x','https://test.local']:
            with self.assertRaises(ValueError):validate_origin(url)
    def test_forwarding_has_fixed_destination_and_private_token(self):
        opener=Mock();opener.open.return_value=Response(b'{"jobs":[]}')
        client=RemoteClient('https://board.example.com',TOKEN,opener,resolver)
        status,body,_=client.request('/api/jobs')
        self.assertEqual(status,200);self.assertEqual(body,b'{"jobs":[]}')
        req=opener.open.call_args.args[0]
        self.assertEqual(req.full_url,'https://board.example.com/api/v1/jobs')
        self.assertEqual(req.get_header('Authorization'),'Bearer '+TOKEN)
        self.assertIsNone(req.get_header('Origin'))
        with self.assertRaises(ValueError):client.request('/profile.md')
        opener.open.side_effect = lambda *_args, **_kwargs: Response(b'{"jobs":[]}')
        client.request('/api/jobs?status=new&limit=40')
        self.assertEqual(opener.open.call_args.args[0].full_url,'https://board.example.com/api/v1/jobs?status=new&limit=40')
        client.request('/api/jobs/detail?identity=ashby%091')
        self.assertEqual(opener.open.call_args.args[0].full_url,'https://board.example.com/api/v1/jobs/detail?identity=ashby%091')
    def test_redirect_and_private_resolution_rejected(self):
        opener=Mock();response=Response(b'');response.code=302;opener.open.return_value=response
        with self.assertRaises(ProxyError):RemoteClient('https://board.example.com',TOKEN,opener,resolver).request('/api/jobs')
        private=lambda *_args,**_kwargs:[(None,None,None,None,('127.0.0.1',443))]
        opener.reset_mock()
        with self.assertRaises(ProxyError):RemoteClient('https://board.example.com',TOKEN,opener,private).request('/api/jobs')
        opener.open.assert_not_called()
    def test_timeout_is_sanitized(self):
        opener=Mock();opener.open.side_effect=TimeoutError(TOKEN)
        with self.assertRaises(ProxyError) as found:RemoteClient('https://board.example.com',TOKEN,opener,resolver).request('/api/tracking',{})
        self.assertEqual(found.exception.status,504);self.assertNotIn(TOKEN,str(found.exception))
