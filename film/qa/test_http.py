#!/usr/bin/env python3
"""HTTP smoke tests against the local game using only fresh QA-created runs.

Does not access provider APIs, modify existing saves, or publish media. Reports
contain status codes and identifiers, never private response bodies.
"""
from __future__ import annotations
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('MING_HTTP_TEST_BASE', 'http://127.0.0.1:8156').rstrip('/')
REPORT = {'schemaVersion': 1, 'baseUrl': BASE, 'testedAt': datetime.now(timezone.utc).isoformat(),
          'scope': 'local server only; fresh QA saves; no provider calls or existing-save writes',
          'createdRunIds': [], 'checks': [], 'privatePathStatus': {}, 'rangeChecks': [],
          'cleanup': {'earlierProviderInspectionReclaimedBytes': 12966351,
                      'earlierProviderInspectionReclaimedMiB': 12.37,
                      'scope': 'temporary public provider JavaScript and own Python bytecode only'}}


def http(method, path, payload=None, headers=None, read_body=True):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=data,
        headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=12)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        # Private-route probes never read returned bytes, including unexpected 200s.
        body = response.read(100000) if read_body else b''
        return response.status, dict(response.headers), body


def api(method, path, payload=None):
    status, headers, body = http(method, path, payload)
    value = json.loads(body)
    return status, value


def new_run():
    status, run = api('POST', '/api/runs', {})
    if status != 201 or not re.fullmatch(r'[a-f0-9]{32}', run.get('id', '')):
        raise AssertionError('Fresh test run creation failed')
    REPORT['createdRunIds'].append(run['id'])
    return run


def act(run, **payload):
    payload.setdefault('revision', run['revision'])
    payload.setdefault('requestId', 'qa_' + uuid.uuid4().hex)
    return api('POST', '/api/runs/' + run['id'] + '/act', payload)


def get_run(run):
    status, saved = api('GET', '/api/runs/' + run['id'])
    if status != 200: raise AssertionError('Fresh test save read failed')
    return saved


def first_choice():
    run = new_run()
    for _ in range(50):
        if run['beat']['type'] == 'choice': return run
        if run['beat']['type'] not in ('narration', 'dialogue'):
            raise AssertionError('Unexpected interactive node before first choice')
        status, run = act(run, type='advance')
        if status != 200: raise AssertionError('Could not advance fresh QA save')
    raise AssertionError('No first choice reached')


class HttpSmoke(unittest.TestCase):
    def run(self, result=None):
        started = time.monotonic()
        before_failures = len(result.failures) + len(result.errors) if result else 0
        answer = super().run(result)
        after_failures = len(answer.failures) + len(answer.errors)
        REPORT['checks'].append({'name': self._testMethodName,
            'passed': after_failures == before_failures,
            'elapsedMs': round((time.monotonic() - started) * 1000)})
        return answer

    def test_01_concurrent_idempotency_settles_once(self):
        before = first_choice()
        option = next(o['id'] for o in before['beat']['options'] if not o.get('disabled'))
        payload = {'type': 'choose', 'optionId': option, 'revision': before['revision'],
                   'requestId': 'qa_duplicate_' + uuid.uuid4().hex}
        endpoint = '/api/runs/' + before['id'] + '/act'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: api('POST', endpoint, payload), range(2)))
        self.assertEqual([r[0] for r in replies], [200, 200])
        self.assertEqual(replies[0][1], replies[1][1], 'Same request must replay the same response')
        saved = get_run(before)
        self.assertEqual(saved['revision'], before['revision'] + 1)
        self.assertEqual(len(saved['history']), len(before['history']) + 1)
        self.assertEqual(saved['state'], replies[0][1]['state'])
        self.assertEqual(saved['receipt'], replies[0][1]['receipt'])
        # Reusing an idempotency key for a different action must fail, even after commit.
        changed = {**payload, 'optionId': 'qa_invented_option'}
        code, _ = api('POST', endpoint, changed)
        self.assertEqual(code, 400)
        self.assertEqual(get_run(before), saved)

    def test_02_stale_revision_returns_409_without_mutation(self):
        before = new_run()
        self.assertIn(before['beat']['type'], ('narration', 'dialogue'))
        code, current = act(before, type='advance')
        self.assertEqual(code, 200)
        code, body = act(before, type='advance', requestId='qa_stale_' + uuid.uuid4().hex)
        self.assertEqual(code, 409)
        self.assertIn('error', body)
        self.assertEqual(get_run(before), current)

    def test_03_invalid_choice_and_media_callback_do_not_mutate(self):
        before = first_choice()
        for payload in ({'type': 'choose', 'optionId': 'qa_invented_option'},
                        {'type': 'advance'}, {'type': 'media_finished'}):
            with self.subTest(action=payload['type']):
                code, _ = act(before, **payload)
                self.assertEqual(code, 400)
                self.assertEqual(get_run(before), before)

    def test_04_private_files_and_traversal_are_not_served(self):
        paths = ['/private/fumin.env', '/private/runs.sqlite3', '/private/seedance/uploads.json',
                 '/production/state/M01.json', '/production/generation-status.json',
                 '/content/story.json', '/tools/seedance_pipeline.py',
                 '/assets/%2e%2e/private/fumin.env', '/assets/../private/runs.sqlite3',
                 '/media/%2e%2e/private/fumin.env', '/media/M99.mp4']
        for path in paths:
            with self.subTest(path=path):
                code, _, _ = http('GET', path, read_body=False)
                REPORT['privatePathStatus'][path] = code
                self.assertEqual(code, 404)

    def test_05_real_video_range_bytes_match_runtime_master(self):
        code, media = api('GET', '/api/media')
        self.assertEqual(code, 200)
        asset = next((a for a in media.get('assets', {}).values() if a.get('status') == 'ready'), None)
        self.assertIsNotNone(asset, 'At least one approved runtime video is required')
        path = asset['file']
        local = (ROOT / path.lstrip('/')).resolve()
        self.assertTrue(local.is_relative_to((ROOT / 'media').resolve()))
        size = local.stat().st_size
        self.assertGreater(size, 64)
        probes = [('bytes=0-63', 0, 63), ('bytes=-16', size - 16, size - 1),
                  (f'bytes={size-16}-', size - 16, size - 1)]
        for value, start, end in probes:
            with self.subTest(range=value):
                code, headers, body = http('GET', path, headers={'Range': value})
                self.assertEqual(code, 206)
                self.assertEqual(headers.get('Content-Type'), 'video/mp4')
                self.assertEqual(headers.get('Accept-Ranges'), 'bytes')
                self.assertEqual(headers.get('Content-Range'), f'bytes {start}-{end}/{size}')
                self.assertEqual(int(headers['Content-Length']), end - start + 1)
                with local.open('rb') as source:
                    source.seek(start)
                    self.assertEqual(body, source.read(end - start + 1))
                REPORT['rangeChecks'].append({'path': path, 'requestRange': value,
                    'status': code, 'contentRange': headers['Content-Range'],
                    'length': len(body), 'matchesLocalMaster': True})
        code, _, _ = http('GET', path, headers={'Range': f'bytes={size}-'}, read_body=False)
        self.assertEqual(code, 416)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HttpSmoke)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    REPORT.update(passed=result.wasSuccessful(), testsRun=result.testsRun,
                  failures=len(result.failures), errors=len(result.errors),
                  testSavePolicy='Only the newly created IDs listed above were modified; no existing saves were touched.')
    target = ROOT / 'qa/http-smoke.json'
    fd, temporary = tempfile.mkstemp(prefix='.http-smoke.', dir=target.parent)
    with os.fdopen(fd, 'w') as handle:
        json.dump(REPORT, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    os.replace(temporary, target)
    print(json.dumps({'passed': REPORT['passed'], 'testsRun': result.testsRun,
                      'qaRunCount': len(REPORT['createdRunIds']), 'report': str(target)}, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
