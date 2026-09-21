from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import tempfile
import unittest

from app import make_server


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = make_server(Path(self.temp.name)/'test.sqlite',0)
        self.thread = Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:'+str(self.server.server_port)
        self.token = self.call('/api/session')[1]['token']

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def call(self,path,body=None,token=True):
        headers = {'Content-Type':'application/json'}
        if token and hasattr(self,'token'): headers['X-Nexus-Token']=self.token
        req = Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urlopen(req) as r: return r.status,json.loads(r.read())
        except HTTPError as e: return e.code,json.loads(e.read())

    def test_end_to_end_and_bypass_rejected(self):
        data = self.call('/api/demo')[1]
        code,run = self.call('/api/plan',data)
        self.assertEqual(code,201)
        self.assertEqual(self.call('/api/export',{'run_id':run['id']})[0],409)
        decision = {'run_id':run['id'],'action':'APPROVED','actor':'Demo reviewer','reason':'Reviewed constraints','snapshot_hash':run['result']['snapshot_hash']}
        self.assertEqual(self.call('/api/decision',decision)[0],200)
        code,payload = self.call('/api/export',{'run_id':run['id']})
        self.assertEqual(code,200)
        self.assertEqual(payload['status'],'DRAFT_NOT_SENT')

    def test_token_required(self):
        self.assertEqual(self.call('/api/plan',{},token=False)[0],403)

    def test_malformed_shape_is_400(self):
        self.assertEqual(self.call('/api/plan',{'products':[]})[0],400)

    def test_static_ui_is_served(self):
        with urlopen(self.base+'/') as r:
            self.assertIn(b'NEXUS',r.read())
            self.assertIn('frame-ancestors',r.headers['Content-Security-Policy'])


if __name__ == '__main__': unittest.main()
