"""Single-origin local server; only explicit runtime folders are public."""
import argparse
import hashlib
import json
import mimetypes
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
from engine import Engine, StoryError, RevisionConflict

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT/'private/runs.sqlite3'


def read(path): return json.loads(path.read_text())


def connect():
    con = sqlite3.connect(DB,timeout=10)
    con.execute('PRAGMA journal_mode=WAL')
    return con


def initialize():
    DB.parent.mkdir(exist_ok=True)
    with connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS requests (run_id TEXT, request_id TEXT, payload_hash TEXT, result TEXT, PRIMARY KEY(run_id,request_id))')
    DB.chmod(0o600)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        # Private request bodies, inputs and credentials never enter access logs.
        pass

    def engine(self):
        chars=read(ROOT/'content/characters.json')
        if isinstance(chars,dict): chars=chars['characters']
        return Engine(read(ROOT/'content/story.json'),chars)

    def json(self,value,code=200):
        data=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def media(self):
        manifest=read(ROOT/'media/runtime-manifest.json')
        manifest['assets']={k:v for k,v in manifest.get('assets',{}).items()
                            if v.get('status')=='ready' and (ROOT/str(v.get('file','')).lstrip('/')).is_file()}
        return manifest

    def do_GET(self):
        path=unquote(urlsplit(self.path).path)
        try:
            if path in ('/health','/api/health'):
                return self.json({'status':'ok','worldId':'ming1566-film','agentMode':'authored-rules',
                                  'readyVideoCount':len(self.media()['assets'])})
            if path=='/api/bootstrap':
                e=self.engine()
                public={k:v for k,v in e.story.items() if k not in ('scenes','endings')}
                public['scenes']=[{k:v for k,v in s.items() if k!='beats'} for s in e.story['scenes']]
                return self.json({'story':public,'characters':e.characters,'media':self.media(),
                                  'agent':{'mode':'authored-rules','selectionOnly':True,'stateOwner':'deterministic-story-engine'}})
            match=re.fullmatch(r'/api/runs/([a-f0-9]{32})',path)
            if match:
                with connect() as con: row=con.execute('SELECT data FROM runs WHERE id=?',(match[1],)).fetchone()
                if not row:return self.json({'error':'找不到这份存档'},404)
                return self.json(self.engine().public(json.loads(row[0])))
            if path=='/api/media':return self.json(self.media())
            if path=='/' or path in ('/index.html','/app.js','/style.css','/styles.css'):
                file=ROOT/'frontend'/('index.html' if path=='/' else path[1:])
            elif path.startswith('/assets/'):
                file=ROOT/path[1:]
                if not file.resolve().is_relative_to((ROOT/'assets').resolve()):return self.send_error(404)
            elif path.startswith('/media/'):
                assets=self.media()['assets'].values()
                media_root=(ROOT/'media').resolve()
                allowed={v['file'] for v in assets}
                for asset in assets:
                    subtitle=asset.get('subtitleFile')
                    if (isinstance(subtitle,str) and subtitle.startswith('/media/')
                            and Path(subtitle).suffix.lower()=='.vtt'
                            and (ROOT/subtitle.lstrip('/')).resolve().is_relative_to(media_root)):
                        allowed.add(subtitle)
                if path not in allowed:return self.send_error(404)
                file=ROOT/path[1:]
                if not file.resolve().is_relative_to(media_root):return self.send_error(404)
            else:return self.send_error(404)
            if not file.is_file():return self.send_error(404)
            size=file.stat().st_size;start=0;end=size-1;code=200
            range_header=self.headers.get('Range')
            if range_header:
                match=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
                if not match:return self.send_error(416)
                if match[1]:
                    start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
                elif match[2]:start=max(0,size-int(match[2]))
                if start>end or start>=size:return self.send_error(416)
                code=206
            self.send_response(code)
            media_type={'.m4a':'audio/mp4','.vtt':'text/vtt; charset=utf-8'}.get(
                file.suffix.lower(),mimetypes.guess_type(str(file))[0])
            self.send_header('Content-Type',media_type or 'application/octet-stream')
            self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
            self.send_header('Cache-Control','no-cache' if file.suffix in ('.js','.html','.css') else 'private,max-age=3600')
            if code==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with file.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    data=f.read(min(65536,remaining))
                    if not data:break
                    self.wfile.write(data);remaining-=len(data)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as exc:
            self.json({'error':'读取失败','type':type(exc).__name__},500)

    def do_POST(self):
        path=urlsplit(self.path).path
        try:
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.json({'error':'无效请求长度'},400)
            if length<0:return self.json({'error':'无效请求长度'},400)
            if length>20000:return self.json({'error':'输入过长，最多 20KB'},413)
            payload=json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(payload,dict):raise StoryError('无效请求')
            e=self.engine()
            if path=='/api/runs':
                run=e.create()
                with connect() as con:con.execute('INSERT INTO runs VALUES (?,?)',(run['id'],json.dumps(run,ensure_ascii=False)))
                return self.json(e.public(run),201)
            if path=='/api/runs/restore':
                run=e.restore(payload)
                # The entire sequence must validate before any database write occurs.
                with connect() as con:con.execute('INSERT INTO runs VALUES (?,?)',(run['id'],json.dumps(run,ensure_ascii=False)))
                return self.json(e.public(run),201)
            match=re.fullmatch(r'/api/runs/([a-f0-9]{32})/act',path)
            if not match:return self.json({'error':'不存在的接口'},404)
            request_id=payload.get('requestId')
            if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id):
                raise StoryError('请求缺少有效去重标识')
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            with connect() as con:
                con.execute('BEGIN IMMEDIATE')
                previous=con.execute('SELECT payload_hash,result FROM requests WHERE run_id=? AND request_id=?',(match[1],request_id)).fetchone()
                if previous:
                    if previous[0]!=digest:raise StoryError('去重标识不能用于另一个行动')
                    result=json.loads(previous[1])
                else:
                    row=con.execute('SELECT data FROM runs WHERE id=?',(match[1],)).fetchone()
                    if not row:raise StoryError('找不到这份存档')
                    run=e.act(json.loads(row[0]),payload);result=e.public(run)
                    con.execute('UPDATE runs SET data=? WHERE id=?',(json.dumps(run,ensure_ascii=False),match[1]))
                    con.execute('INSERT INTO requests VALUES (?,?,?,?)',(match[1],request_id,digest,json.dumps(result,ensure_ascii=False)))
            return self.json(result)
        except RevisionConflict as exc:self.json({'error':str(exc)},409)
        except (StoryError,json.JSONDecodeError) as exc:self.json({'error':str(exc)},400)
        except Exception as exc:self.json({'error':'操作未完成','type':type(exc).__name__},500)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8156);parser.add_argument('--host',default='127.0.0.1')
    args=parser.parse_args();initialize()
    print(f'Ming1566 listening http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
