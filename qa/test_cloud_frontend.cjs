const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const output = process.argv[2];
assert(output, 'Pass generated OSS output');
const manifest = JSON.parse(fs.readFileSync(path.join(output, 'upload-manifest.json')));
const crypto = require('node:crypto');
for (const e of manifest.entries) {
  const data = fs.readFileSync(path.join(output, e.file));
  assert.equal(crypto.createHash('sha256').update(data).digest('hex'), e.sha256);
  assert(e.key.startsWith('daming/'));
  assert(!/(?:^|\/)(?:private|production|\.env)(?:\/|$)/.test(e.key));
}
for (const edition of ['original', 'storm']) {
  const calls = [];
  const context = {window:{fetch:(...a)=>calls.push(a)}};
  vm.createContext(context); vm.runInContext(fs.readFileSync(path.join(output, edition, 'config.js'), 'utf8'), context);
  context.window.DAMING_API_FETCH('/original/api/bootstrap');
  context.window.DAMING_API_FETCH('/api/runs');
  context.window.DAMING_API_FETCH('https://provider.example/chat');
  assert.equal(calls[0][0], manifest.apiBase+'/original/api/bootstrap');
  assert.equal(calls[1][0], manifest.apiBase+'/api/runs');
  assert.equal(calls[2][0], 'https://provider.example/chat');
  const mapped = context.window.DAMING_MAP_ASSETS({portrait:'/assets/p.png', scene:{background:'/original/assets/anchors/a.png'}, text:'话语不变'});
  assert.equal(mapped.portrait, '/daming/assets/p.png');
  assert.equal(mapped.scene.background, '/daming/original/assets/anchors/a.png');
  assert.equal(mapped.text, '话语不变');
  const app = fs.readFileSync(path.join(output, edition, 'app.js'), 'utf8');
  assert(!/["'`]\/assets\//.test(app));
  assert(app.includes('/daming/'+edition+'"+asset.file'));
  assert(!app.includes('file:BASE+asset.file'));
  new vm.Script(app);
}
const css = fs.readFileSync(path.join(output, 'classic/style.css'), 'utf8');
assert(!css.includes('"./assets/')); assert(css.includes('../assets/'));

async function saveToolsTest() {
  const namespace = 'echo.ming1566.original.v2';
  const checkpoint = {id:'old-id', contentVersion:'2.0.0', revision:1, actionLog:[{type:'advance'}]};
  const storage = new Map([[namespace+'.run', JSON.stringify('old-id')], [namespace+'.checkpoint.old-id', JSON.stringify(checkpoint)], ['dm1566-demo-connection-config', JSON.stringify({apiKey:'DO-NOT-EXPORT'})]]);
  const localStorage = {getItem:k=>storage.get(k)??null, setItem:(k,v)=>storage.set(k,v)};
  const elements = new Map(), blobs = [], requests = [];
  class Element {
    constructor(tag) { this.tag=tag; this.style={}; this.dataset={}; this.children=[]; }
    querySelector(key) { if (!elements.has(key)) elements.set(key, new Element(key)); return elements.get(key); }
    querySelectorAll() { return []; }
    append(e) { this.children.push(e); }
    click() { this.clicked=true; }
    showModal() {} close() {} remove() {}
  }
  const parent = new Element('parent');
  // mount must initially see no previously inserted control.
  parent.querySelector = () => null;
  let dialog;
  const document = {body:new Element('body'), querySelector:q=>q==='.cover-links'?parent:null,
    createElement:tag=>{ const e=new Element(tag); if(tag==='dialog')dialog=e; return e; }};
  const context = {document, localStorage, Blob, TextEncoder, URL:{createObjectURL:b=>{blobs.push(b);return 'blob:local';},revokeObjectURL:()=>{}},
    setTimeout:()=>{}, MutationObserver:class{observe(){}}, location:{origin:'https://app.echodrama.cn',reload(){this.reloaded=true;}}, alert:()=>{},
    window:{DAMING_CONFIG:{namespace,apiPath:'/original'},DAMING_API_FETCH:async(u,o)=>{
      requests.push([u,JSON.parse(o.body)]);
      return {ok:true,json:async()=>({id:'restored-id',contentVersion:'2.0.0',revision:1,actionLog:[{type:'advance'}]})};
    }}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(output,'original/save-tools.js'),'utf8'),context);
  assert.equal(parent.children[0].textContent, '存档迁移'); parent.children[0].onclick();
  elements.get('#save-export').onclick();
  const exported = JSON.parse(await blobs[0].text());
  assert.equal(exported.namespace, namespace); assert(!JSON.stringify(exported).includes('DO-NOT-EXPORT'));
  const input = elements.get('#save-file');
  input.files=[{size:100,text:async()=>JSON.stringify(exported)}]; input.onchange();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests[0][0], '/original/api/runs/restore');
  assert.deepEqual(Object.keys(requests[0][1]).sort(), ['actionLog','contentVersion']);
  assert.equal(storage.get(namespace+'.before-import'), JSON.stringify('old-id'));
  assert.equal(storage.get(namespace+'.run'), JSON.stringify('restored-id'));
  assert.equal(context.location.reloaded, true);
  input.files=[{size:100,text:async()=>JSON.stringify({...exported,namespace:'wrong-edition'})}];input.onchange();
  await new Promise(resolve=>setImmediate(resolve));assert.equal(requests.length,1);
  // The optional bookmark is self-contained, old-origin only, and exports no connection credentials.
  context.location.origin='https://daming-1566.onrender.com';
  storage.set(namespace+'.run', JSON.stringify('old-id'));
  vm.runInContext(decodeURIComponent(elements.get('#old-export').href.slice('javascript:'.length)),context);
  const old = JSON.parse(await blobs.at(-1).text());
  assert.equal(old.format, 'echo-daming-all-saves-v1');assert.equal(old.saves.length,1);
  assert(!JSON.stringify(old).includes('DO-NOT-EXPORT'));
}
saveToolsTest().then(()=>console.log(JSON.stringify({passed:true,verifiedFiles:manifest.fileCount,configAndAssets:'passed',saveImportExportAndBookmark:'passed'}))).catch(e=>{console.error(e);process.exitCode=1;});
