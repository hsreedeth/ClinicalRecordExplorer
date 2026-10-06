"""Check the deployable API entry points against the local report contract."""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.report import handler as ReportHandler
from api.health import handler as HealthHandler
from pipeline import build_database, build_report


class VercelTests(unittest.TestCase):
    def get(self, handler, path):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f'http://127.0.0.1:{server.server_port}{path}'
            ) as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                return json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_report_parity_and_recalculation(self):
        db, run = build_database()
        try:
            expected = build_report(db, run)
        finally:
            db.close()
        self.assertEqual(self.get(ReportHandler, '/api/report'), expected)
        expanded = self.get(ReportHandler, '/api/report?threshold=8&days=181')
        self.assertEqual(expanded['counts']['meets_threshold'], 3)
        raised = self.get(ReportHandler, '/api/report?threshold=10&days=181')
        self.assertEqual(raised['counts']['meets_threshold'], 0)

    def test_invalid_parameters_and_health(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get(ReportHandler, '/api/report?days=-1')
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(
            self.get(HealthHandler, '/api/health')['report_schema_version'], 2
        )


if __name__ == '__main__':
    unittest.main()
