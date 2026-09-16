"""Restore contracts use a temporary database and a private ephemeral HTTP server."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import server as film_server


class RestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='ming-restore-qa-')
        cls.previous_db=film_server.DB
        film_server.DB=Path(cls.tmp.name)/'runs.sqlite3'
        film_server.initialize()
        cls.httpd=film_server.ThreadingHTTPServer(('127.0.0.1',0),film_server.Handler)
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.httpd.server_port}'
        cls.e=film_server.Handler.engine(None)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown();cls.httpd.server_close();cls.thread.join()
        film_server.DB=cls.previous_db
        cls.tmp.cleanup()

    def setUp(self):
        with film_server.connect() as con:
            con.execute('DELETE FROM requests');con.execute('DELETE FROM runs')

    def api(self,path,payload=None):
        request=urllib.request.Request(self.base+path,
            data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,
            headers={'Content-Type':'application/json'})
        try:response=urllib.request.urlopen(request,timeout=10)
        except urllib.error.HTTPError as exc:response=exc
        with response:return response.status,json.loads(response.read())

    def count(self):
        with film_server.connect() as con:return con.execute('SELECT count(*) FROM runs').fetchone()[0]

    def checkpoint(self,run):
        return {key:copy.deepcopy(run[key]) for key in ('contentVersion','actionLog')}

    def route(self):
        run=self.e.create();snapshots=[run]
        for _ in range(100):
            if run['status']=='ending':return snapshots
            _,beat=self.e.current(run)
            if beat['type']=='choice':
                option=next(o for o in beat['options'] if self.e.eligible(o.get('requires'),run['state']))
                action={'type':'choose','optionId':option['id']}
            elif beat['type']=='free_input':
                if run['proposal']:action={'type':'choose','optionId':run['proposal']['ruleId']}
                else:action={'type':'free_input','text':'原账留下，核验经手收据。'}
            elif beat['type']=='qte':action={'type':'qte','outcome':'success'}
            else:action={'type':'advance'}
            run=self.e.act(run,{**action,'revision':run['revision']});snapshots.append(run)
        self.fail('Route did not end')

    def test_legal_restore_preserves_state_history_receipt_and_preview(self):
        snapshots=self.route()
        targets=[snapshots[0],next(r for r in snapshots if r['receipt']),
                 next(r for r in snapshots if r['proposal']),snapshots[-1]]
        for original in targets:
            code,restored=self.api('/api/runs/restore',self.checkpoint(original))
            self.assertEqual(code,201)
            expected=self.e.public(original)
            self.assertNotEqual(restored.pop('id'),expected.pop('id'))
            self.assertEqual(restored,expected)
        self.assertEqual(self.count(),len(targets))

    def test_compatible_versions_replay_to_current_version(self):
        original=self.route()[-1]
        for version in self.e.story.get('compatibleSaveVersions',[]):
            checkpoint=self.checkpoint(original);checkpoint['contentVersion']=version
            code,restored=self.api('/api/runs/restore',checkpoint)
            self.assertEqual(code,201)
            self.assertEqual(restored['contentVersion'],self.e.story['version'])
            self.assertEqual(restored['state'],original['state'])

    def test_tampered_state_and_action_fields_are_rejected_without_insert(self):
        checkpoint=self.checkpoint(self.e.create())
        for payload in ({**checkpoint,'state':{'stats':{'evidence':100}}},
                        {**checkpoint,'actionLog':[{'type':'advance','stats':{'evidence':100}}]},
                        {**checkpoint,'revision':99}):
            self.assertEqual(self.api('/api/runs/restore',payload)[0],400)
            self.assertEqual(self.count(),0)

    def test_late_invalid_action_never_inserts_partial_run(self):
        checkpoint=self.checkpoint(self.route()[-1])
        checkpoint['actionLog'].append({'type':'advance'})
        self.assertEqual(self.api('/api/runs/restore',checkpoint)[0],400)
        self.assertEqual(self.count(),0)

    def test_limits_missing_log_and_bad_version_are_rejected(self):
        checkpoint=self.checkpoint(self.e.create())
        payloads=[({},400),({**checkpoint,'contentVersion':'999.bad'},400),
                  ({**checkpoint,'actionLog':None},400),
                  ({**checkpoint,'actionLog':[{'type':'advance'}]*101},400),
                  ({**checkpoint,'actionLog':[{'type':'free_input','text':'账'*7000}]},413)]
        for payload,status in payloads:
            self.assertEqual(self.api('/api/runs/restore',payload)[0],status)
            self.assertEqual(self.count(),0)

    def test_request_id_retry_records_only_one_canonical_action(self):
        _,run=self.api('/api/runs',{})
        payload={'type':'advance','revision':0,'requestId':'qa_same_request_01','stats':{'evidence':100}}
        endpoint=f"/api/runs/{run['id']}/act"
        first=self.api(endpoint,payload);second=self.api(endpoint,payload)
        self.assertEqual(first,second)
        self.assertEqual(first[1]['actionLog'],[{'type':'advance'}])
        self.assertEqual(first[1]['state'],run['state'])
        self.assertEqual(self.api(f"/api/runs/{run['id']}")[1]['revision'],1)

    @unittest.skipUnless(os.environ.get('MING_RESTORE_BROWSER')=='1','Enable with MING_RESTORE_BROWSER=1 and Playwright installed')
    def test_browser_404_restore_and_network_failure(self):
        result=subprocess.run(['node',str(ROOT/'qa/browser-restore.cjs')],
            env={**os.environ,'BASE_URL':self.base},capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)


if __name__=='__main__':unittest.main(verbosity=2)
