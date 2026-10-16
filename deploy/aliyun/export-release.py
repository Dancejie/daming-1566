#!/usr/bin/env python3
"""Write a separate OSS runtime and a secret-free backend archive, never source edits."""
import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.m4a', '.wav', '.mp3', '.vtt', '.mp4'}

def digest(data): return hashlib.sha256(data).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--api-base', required=True)
    parser.add_argument('--site-prefix', default='/daming')
    parser.add_argument('--backend-out', required=True)
    args = parser.parse_args()
    api = args.api_base.rstrip('/')
    parsed = urlsplit(api)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('API base must be an HTTPS origin/path without credentials, query or fragment')
    prefix = args.site_prefix.rstrip('/')
    if not re.fullmatch(r'/[a-z][a-z0-9-]*', prefix): raise ValueError('Use one safe, non-root OSS prefix')
    out, archive = Path(args.output).resolve(), Path(args.backend_out).resolve()
    if out.exists() or archive.exists(): raise ValueError('Refuse to overwrite an existing release or archive')
    if not ('tmp' in out.parts or any(p.startswith('.work-') for p in out.parts)): raise ValueError('Use /tmp or a .work- output directory')
    archive.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True)
    entries = []
    seen = set()
    def emit(key, data, source=None):
        if key.startswith('/') or '..' in Path(key).parts or key in seen: raise ValueError('Unsafe or duplicate key: ' + key)
        seen.add(key)
        dest = out / key; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
        mime = {'.m4a':'audio/mp4', '.vtt':'text/vtt; charset=utf-8', '.js':'application/javascript; charset=utf-8', '.html':'text/html; charset=utf-8', '.css':'text/css; charset=utf-8'}.get(dest.suffix, mimetypes.guess_type(key)[0] or 'application/octet-stream')
        entries.append({'key':prefix.lstrip('/')+'/'+key, 'file':key, 'bytes':len(data), 'sha256':digest(data), 'source':source,
            'headers':{'Content-Type':mime, 'Cache-Control':'no-cache' if dest.suffix in {'.js','.html','.css'} else 'public,max-age=86400'}})
    def copy(source, key):
        path = ROOT / source
        if path.is_symlink() or not path.is_file(): raise ValueError('Missing/unsafe runtime source: ' + source)
        emit(key, path.read_bytes(), source)
    # Root assets are also used by both cinema editions; there is no duplicated film/assets copy.
    for directory, target in [('assets','assets'), ('original/assets','original/assets')]:
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file() and path.suffix.lower() in EXTENSIONS and 'generated_voice' not in path.parts:
                copy(path.relative_to(ROOT).as_posix(), target + '/' + path.relative_to(ROOT / directory).as_posix())
    for source in ['assets/classic_voice/manifest.json', 'assets/characters/manifest.json']:
        copy(source, source)
    media_count = {}
    for edition, target in [('original','original'), ('film','storm')]:
        manifest = json.loads((ROOT / edition / 'media/runtime-manifest.json').read_text())
        copied = set(); ready = 0
        for asset in manifest['assets'].values():
            if asset.get('status') != 'ready': continue
            ready += 1
            for field, hash_field in [('file','sha256'), ('subtitleFile','subtitleSha256')]:
                file = asset.get(field)
                if not file: continue
                if not file.startswith('/media/') or '..' in Path(file).parts: raise ValueError('Unsafe manifest media path')
                source = edition + file
                path = ROOT / source
                if asset.get(hash_field) and digest(path.read_bytes()) != asset[hash_field]: raise ValueError('Media hash mismatch: ' + source)
                if source not in copied: copy(source, target + file); copied.add(source)
        media_count[target] = ready
    if media_count != {'original':12, 'storm':9}: raise ValueError('Unexpected full-edition media coverage')
    save_tools = (ROOT / 'deploy/aliyun/save-tools.js').read_bytes()
    for edition, target, ns, api_path in [('original','original','echo.ming1566.original.v2','/original'), ('film','storm','echo.ming1566.cinema.v1','')]:
        config = {'apiBase':api, 'sitePrefix':prefix, 'apiPath':api_path, 'namespace':ns}
        config_js = 'window.DAMING_CONFIG=' + json.dumps(config) + ';\n' + r'''
window.DAMING_MAP_ASSETS = function map(v) {
  if (Array.isArray(v)) return v.map(map);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,map(x)]));
  return typeof v === 'string' && (v.startsWith('/assets/') || v.startsWith('/original/assets/')) ? window.DAMING_CONFIG.sitePrefix+v : v;
};
window.DAMING_API_FETCH = (input, options) => {
  const url = typeof input === 'string' && (input.startsWith('/api/') || input.startsWith('/original/api/')) ? window.DAMING_CONFIG.apiBase+input : input;
  return window.fetch(url, options);
};
'''
        emit(target+'/config.js', config_js.encode())
        emit(target+'/save-tools.js', save_tools)
        js = (ROOT / edition / 'frontend/app.js').read_text()
        js = js.replace('fetch(BASE+url,', 'window.DAMING_API_FETCH(BASE+url,').replace('fetch(url,', 'window.DAMING_API_FETCH(url,')
        js = js.replace('return data;}', 'return window.DAMING_MAP_ASSETS(data);}')
        js = js.replace('/assets/', prefix + '/assets/')
        if edition == 'original':
            js = js.replace('file:BASE+asset.file', 'file:'+json.dumps(prefix+'/original')+'+asset.file').replace('BASE+asset.subtitleFile', json.dumps(prefix+'/original')+'+asset.subtitleFile')
        else:
            js = js.replace('return {...asset,shotId:shot};', 'return {...asset,file:'+json.dumps(prefix+'/storm')+'+asset.file,subtitleFile:asset.subtitleFile?'+json.dumps(prefix+'/storm')+'+asset.subtitleFile:null,shotId:shot};')
        js = js.replace('href="/storm/"', 'href="'+prefix+'/storm/index.html"').replace('href="/classic/"', 'href="'+prefix+'/classic/index.html"')
        html = (ROOT / edition / 'frontend/index.html').read_text()
        html = re.sub(r'href="/(?:original/)?style.css"', 'href="./style.css"', html)
        html = re.sub(r'<script type="module" src="/(?:original/)?app.js"></script>', '<script src="./config.js"></script><script type="module" src="./app.js"></script><script defer src="./save-tools.js"></script>', html)
        emit(target+'/index.html', html.encode()); emit(target+'/app.js', js.encode())
        copy(edition+'/frontend/style.css', target+'/style.css')
    # Preserve the classic edition, including user-configured external providers.
    classic_js = (ROOT/'app.js').read_text().replace('fetch(', 'window.DAMING_API_FETCH(')
    classic_js = classic_js.replace('./assets/', '../assets/')
    classic_config = 'window.DAMING_API_FETCH=(u,o)=>fetch(typeof u==="string"&&u.startsWith("/api/")?'+json.dumps(api)+'+u:u,o);'
    classic_html = (ROOT/'index.html').read_text().replace('./assets/', '../assets/').replace('<script src="./app.js', '<script src="./config.js"></script><script src="./app.js')
    emit('classic/index.html', classic_html.encode()); emit('classic/app.js', classic_js.encode()); emit('classic/config.js', classic_config.encode())
    emit('classic/style.css', (ROOT/'style.css').read_text().replace('./assets/', '../assets/').encode())
    emit('index.html', ('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=./original/index.html"><a href="./original/index.html">大明1566 · 无雪之冬</a>').encode())
    backend = ['server.py','legacy_server.py','requirements.txt','deploy/aliyun/Dockerfile','assets/classic_voice/manifest.json']
    backend += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'film/backend').glob('*.py'))]
    for edition in ['film','original']:
        backend += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/edition/'content').glob('*.json'))]
        backend += [edition+'/media/runtime-manifest.json']
    with tarfile.open(archive, 'w:gz') as tar:
        for name in backend:
            if (ROOT/name).is_symlink(): raise ValueError('Refuse backend symlink')
            tar.add(ROOT/name, arcname='Dockerfile' if name.endswith('/Dockerfile') else name, recursive=False)
    report = {'schemaVersion':1,'prefix':prefix.lstrip('/')+'/', 'apiBase':api,
        'sourceRevision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'originalScenes':6,'originalNodes':51,'readyVideos':media_count,'fileCount':len(entries),
        'totalBytes':sum(e['bytes'] for e in entries),'entries':entries,
        'backend':{'file':str(archive),'sha256':digest(archive.read_bytes()),'bytes':archive.stat().st_size,'files':backend}}
    (out/'upload-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['entries','backend']},ensure_ascii=False))
    print(json.dumps(report['backend'],ensure_ascii=False))

if __name__ == '__main__': main()
