"""Loopback-only local UI. This is not an internet-facing application server."""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .cases import Cases
from .sources import load_dotenv

ASSETS=Path(__file__).with_name('static')


def make_server(root,port=8765):
    cases=Cases(root); token=secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self,*args): pass

        def _allowed_host(self):
            return self.headers.get('Host','') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}

        def send(self,status,payload,kind='application/json',filename=None,report_script=False):
            if kind=='application/json': payload=json.dumps(payload,ensure_ascii=False).encode('utf-8')
            elif isinstance(payload,str): payload=payload.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            from .report import SCRIPT_HASH
            scripts="'self'" + (" '"+SCRIPT_HASH+"'" if report_script else '')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src "+scripts+"; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
            self.end_headers(); self.wfile.write(payload)

        def do_GET(self):
            if not self._allowed_host(): self.send(403,{'error':'Local host required'}); return
            path=urlsplit(self.path).path
            try:
                if path in ('/','/app.js','/app.css'):
                    name={'/':'index.html','/app.js':'app.js','/app.css':'app.css'}[path]
                    kind={'/':'text/html','/app.js':'text/javascript','/app.css':'text/css'}[path]
                    self.send(200,(ASSETS/name).read_bytes(),kind); return
                if path=='/api/session':
                    self.send(200,{'token':token,'credentials':{'x':bool(os.environ.get('X_BEARER_TOKEN')),'bluesky':bool(os.environ.get('BSKY_HANDLE') and os.environ.get('BSKY_APP_PASSWORD')),'mastodon':True}}); return
                if path=='/api/cases': self.send(200,cases.list()); return
                parts=path.strip('/').split('/')
                if len(parts)>=3 and parts[:2]==['api','cases']:
                    case_id=parts[2]
                    if len(parts)==3: self.send(200,cases.detail(case_id)); return
                    if len(parts)==5 and parts[3]=='groups': self.send(200,cases.evidence(case_id,parts[4])); return
                    if len(parts)==4 and parts[3]=='export': self.send(200,cases.export(case_id),filename='topicstream-case.json'); return
                    if len(parts)==4 and parts[3]=='report':
                        report=cases.folder(case_id)/'report.html'
                        self.send(200,report.read_bytes(),'text/html',report_script=True); return
                self.send(404,{'error':'Not found'})
            except FileNotFoundError as exc: self.send(404,{'error':str(exc)})
            except (ValueError,KeyError) as exc: self.send(400,{'error':str(exc)})
            except Exception: self.send(500,{'error':'Unable to read this case'})

        def do_POST(self):
            # Consume bounded bodies even on a rejected session; closing a socket
            # with unread bytes can reset the connection before the client sees 403.
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>12*1024*1024: self.send(413,{'error':'Request exceeds 12 MB'}); return
                raw=self.rfile.read(length)
            except (ValueError,TimeoutError): self.send(400,{'error':'Invalid request body'}); return
            origin=self.headers.get('Origin')
            valid_origins={f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
            if not self._allowed_host() or self.headers.get('X-TopicStream-Token')!=token or (origin and origin not in valid_origins):
                self.send(403,{'error':'Invalid local session'}); return
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': self.send(415,{'error':'Use application/json'}); return
            try:
                body=json.loads(raw or b'{}')
                if not isinstance(body,dict): raise ValueError('JSON object required')
                path=urlsplit(self.path).path
                if path=='/api/plan':
                    from .cases import plan_topic
                    self.send(200,plan_topic(str(body.get('topic','')))); return
                if path=='/api/cases': self.send(201,cases.create(body)); return
                if path=='/api/demo': self.send(201,cases.demo()); return
                parts=path.strip('/').split('/')
                if len(parts)==4 and parts[:2]==['api','cases']:
                    case_id,action=parts[2:]
                    if action in ('collect','analyze'): self.send(202,cases.submit(case_id,action)); return
                    if action=='cancel': self.send(200,cases.cancel(case_id)); return
                    if action=='review': self.send(201,cases.review(case_id,body)); return
                    if action=='import': self.send(202,cases.import_text(case_id,body.get('csv',''),body.get('source','import'),body.get('profiles'))); return
                self.send(404,{'error':'Not found'})
            except FileNotFoundError as exc: self.send(404,{'error':str(exc)})
            except (ValueError,KeyError,TypeError) as exc: self.send(400,{'error':str(exc)})
            except Exception: self.send(500,{'error':'Operation failed; check the case job log'})

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.cases=cases
    return server


def serve(root='topicstream-cases',port=8765):
    load_dotenv([Path('.env')])
    server=make_server(root,port)
    print(f'TopicStream: http://127.0.0.1:{server.server_port} (local only)')
    try: server.serve_forever()
    finally: server.server_close(); server.cases.close()
