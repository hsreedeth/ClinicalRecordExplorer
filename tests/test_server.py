import json
import sys
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Handler

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls): cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def get(self,path):
        with urllib.request.urlopen(self.base+path) as response: return response.status,response.read()
    def test_assets_and_default_report(self):
        for path in ('/','/style.css','/ui.js'): self.assertEqual(self.get(path)[0],200)
        report=json.loads(self.get('/api/report')[1]);self.assertEqual(report['counts']['meets_threshold'],2)
    def test_parameter_recalculation_and_invalid_input(self):
        expanded=json.loads(self.get('/api/report?days=181')[1]);self.assertEqual(expanded['counts']['meets_threshold'],3)
        with self.assertRaises(urllib.error.HTTPError) as error: self.get('/api/report?days=-1')
        self.assertEqual(error.exception.code,400)

if __name__=='__main__': unittest.main()
