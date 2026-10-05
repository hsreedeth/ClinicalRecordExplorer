"""Local offline UI server. Binds only to loopback; no external services."""
import argparse
import hashlib
import os
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs,urlparse
from pipeline import ROOT,REPORT_SCHEMA_VERSION,LINEAGE_SCHEMA_VERSION,build_database,build_report

LOADED_PIPELINE_SHA256=hashlib.sha256((ROOT/'pipeline.py').read_bytes()).hexdigest()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url=urlparse(self.path)
        try:
            if url.path=='/api/health':
                body=json.dumps({'process_id':os.getpid(),'project_root':str(ROOT.resolve()),
                                 'report_schema_version':REPORT_SCHEMA_VERSION,'lineage_schema_version':LINEAGE_SCHEMA_VERSION,
                                 'loaded_pipeline_sha256':LOADED_PIPELINE_SHA256}).encode()
                mime='application/json'
            elif url.path=='/api/report':
                params=parse_qs(url.query)
                threshold=float(params.get('threshold',['8'])[0]); days=int(params.get('days',['180'])[0])
                db,run=build_database()
                try: body=json.dumps(build_report(db,run,threshold,days),allow_nan=False).encode()
                finally: db.close()
                mime='application/json'
            elif url.path in ('/','/index.html','/style.css','/ui.js','/fonts/InterVariable.woff2','/fonts/InterVariable-Italic.woff2','/fonts/OFL.txt'):
                file=ROOT/'web'/('index.html' if url.path=='/' else url.path[1:])
                body=file.read_bytes(); mime=mimetypes.guess_type(file)[0] or 'text/plain'
            else:
                self.send_error(404); return
            self.send_response(200); self.send_header('Content-Type',mime+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(body)
        except (ValueError,KeyError) as exc:
            body=json.dumps({'error':str(exc)}).encode()
            self.send_response(400); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args()
    print('Clinical Record Explorer: http://127.0.0.1:'+str(args.port),flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
