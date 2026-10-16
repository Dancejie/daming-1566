"""Cloud routing and persistent-save checks; only temporary local data and no paid API."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

class AliyunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='daming-cloud-qa-')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.env = {**os.environ, 'PORT':str(cls.port), 'DAMING_DATA_DIR':cls.tmp.name,
            'DAMING_ALLOWED_ORIGIN':'https://app.echodrama.cn',
            'DAMING_STATIC_BASE':'https://app.echodrama.cn/daming',
            'DAMING_EXTERNAL_MEDIA':'verified-oss-release', 'DEEPSEEK_API_KEY':''}
        cls.start()

    @classmethod
    def start(cls):
        cls.proc = subprocess.Popen([sys.executable, str(ROOT/'server.py')], cwd=ROOT, env=cls.env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                with urllib.request.urlopen(cls.base+'/api/health', timeout=.5) as response:
                    if response.status == 200: return
            except (OSError, urllib.error.URLError): time.sleep(.1)
        raise RuntimeError('Local test server did not start')

    @classmethod
    def stop(cls):
        cls.proc.terminate(); cls.proc.wait(timeout=10)

    @classmethod
    def tearDownClass(cls):
        cls.stop(); cls.tmp.cleanup()

    def request(self, path, body=None, origin='https://app.echodrama.cn', method=None):
        req = urllib.request.Request(self.base+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Origin':origin, 'Content-Type':'application/json'}, method=method)
        try: response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e: response = e
        with response: return response.status, dict(response.headers), response.read()

    def test_cors_exact_origin_and_options(self):
        status, headers, _ = self.request('/api/health')
        self.assertEqual(status, 200); self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://app.echodrama.cn')
        for origin in ['https://evil.example', 'https://app.echodrama.cn.evil.example']:
            self.assertNotIn('Access-Control-Allow-Origin', self.request('/api/health', origin=origin)[1])
            self.assertEqual(self.request('/original/api/runs', origin=origin, method='OPTIONS')[0], 403)
        self.assertEqual(self.request('/original/api/runs', method='OPTIONS')[0], 204)

    def test_both_editions_persist_after_process_restart(self):
        expected = {}
        for path, version in [('/original','2.0.0'), ('','1.1.0')]:
            status, _, raw = self.request(path+'/api/runs', {})
            self.assertEqual(status, 201); run = json.loads(raw)
            self.assertEqual(run['contentVersion'], version)
            status, _, raw = self.request(path+'/api/runs/'+run['id']+'/act', {'type':'advance','revision':run['revision'],'requestId':'aliyun-save-test-01'})
            self.assertEqual(status, 200); expected[path] = json.loads(raw)
        self.stop(); self.start()
        for path, run in expected.items():
            status, _, raw = self.request(path+'/api/runs/'+run['id'])
            self.assertEqual(status, 200); self.assertEqual(json.loads(raw), run)
            checkpoint = {'contentVersion':run['contentVersion'], 'actionLog':run['actionLog']}
            status, _, raw = self.request(path+'/api/runs/restore', checkpoint)
            self.assertEqual(status, 201)
            restored = json.loads(raw); self.assertNotEqual(restored.pop('id'), run['id'])
            self.assertEqual(restored, {k:v for k,v in run.items() if k != 'id'})

    def test_runtime_coverage_and_private_files(self):
        for path, videos, scenes in [('/original',12,6), ('',9,6)]:
            code, _, raw = self.request(path+'/api/bootstrap'); bootstrap = json.loads(raw)
            self.assertEqual(code, 200); self.assertEqual(len(bootstrap['media']['assets']), videos)
            self.assertEqual(len(bootstrap['story']['scenes']), scenes)
        for path in ['/.env','/original/private/runs.sqlite3','/film/private/runs.sqlite3','/classic/server.py']:
            self.assertEqual(self.request(path)[0],404)
        rss = subprocess.check_output(['ps','-o','rss=','-p',str(self.proc.pid)],text=True).strip()
        print(json.dumps({'testServerRssKiB':int(rss)}))

if __name__ == '__main__': unittest.main()
