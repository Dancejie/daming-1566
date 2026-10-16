/* Local-only save transport. Story validity remains owned by the restore API. */
(() => {
  'use strict';
  const c = window.DAMING_CONFIG;
  if (!c || !c.namespace) return;
  const read = (key, fallback = null) => { try { return JSON.parse(localStorage.getItem(`${c.namespace}.${key}`)) ?? fallback; } catch { return fallback; } };
  const download = (value, filename) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(value)], {type:'application/json'}));
    a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  const snapshot = () => {
    const id = read('run'); const checkpoint = read(`checkpoint.${id}`);
    if (!checkpoint || !Array.isArray(checkpoint.actionLog)) throw new Error('本设备尚没有可导出的完整存档。');
    return {format:'echo-daming-save-v1', namespace:c.namespace, checkpoint,
      played:read(`played.${id}`, []), preferences:read('preferences', {})};
  };
  async function importSave(file) {
    if (file.size > 40000) throw new Error('存档文件过大，请使用本游戏导出的 JSON。');
    const data = JSON.parse(await file.text());
    const selected = data.format === 'echo-daming-all-saves-v1' ? data.saves.find(s => s.namespace === c.namespace) : data;
    if (!selected || selected.format !== 'echo-daming-save-v1' || selected.namespace !== c.namespace) throw new Error('这份存档不属于当前篇章，请在原著篇或风暴初夜的对应入口导入。');
    const cp = selected.checkpoint;
    if (!cp || typeof cp.contentVersion !== 'string' || !Number.isInteger(cp.revision) || !Array.isArray(cp.actionLog) || cp.actionLog.length !== cp.revision) throw new Error('存档记录不完整，没有替换现有进度。');
    const payload = JSON.stringify({contentVersion:cp.contentVersion, actionLog:cp.actionLog});
    if (new TextEncoder().encode(payload).length > 20000) throw new Error('存档超出恢复接口的大小限制。');
    const res = await window.DAMING_API_FETCH(c.apiPath + '/api/runs/restore', {method:'POST', headers:{'Content-Type':'application/json'}, body:payload});
    const run = await res.json();
    if (!res.ok) throw new Error(run.error || '存档校验失败，没有替换现有进度。');
    // Keep the previous pointer and checkpoint; import creates a different server run.
    const previous = read('run');
    if (previous) localStorage.setItem(`${c.namespace}.before-import`, JSON.stringify(previous));
    localStorage.setItem(`${c.namespace}.run`, JSON.stringify(run.id));
    localStorage.setItem(`${c.namespace}.checkpoint.${run.id}`, JSON.stringify({id:run.id, contentVersion:run.contentVersion, revision:run.revision, actionLog:run.actionLog}));
    const played = Array.isArray(selected.played) ? selected.played.filter(s => typeof s === 'string' && /^[A-Z0-9]{1,20}$/.test(s)) : [];
    localStorage.setItem(`${c.namespace}.played.${run.id}`, JSON.stringify(played));
    if (selected.preferences && typeof selected.preferences === 'object') {
      const prefs = {}; for (const key of ['sound','media','accessible']) if (typeof selected.preferences[key] === 'boolean') prefs[key] = selected.preferences[key];
      localStorage.setItem(`${c.namespace}.preferences`, JSON.stringify(prefs));
    }
    location.reload();
  }
  function open() {
    if (document.querySelector('#daming-save-dialog')) return;
    const dialog = document.createElement('dialog'); dialog.id = 'daming-save-dialog';
    dialog.style.cssText = 'max-width:min(90vw,440px);padding:24px;color:#eee5d6;background:#211c16;border:1px solid #8d7851;border-radius:14px;line-height:1.6';
    dialog.innerHTML = '<h2>存档与迁移</h2><p>新站和旧站不会自动共享此浏览器的存档。导入会创建新档，原有进度保留备份；只有剧情验证通过后才切换。</p><p><button id="save-export">导出当前存档</button> <button id="save-import">导入存档文件</button></p><input id="save-file" type="file" accept=".json,application/json" hidden><p>旧 Render 的存档仍可在旧站继续。电脑上可将下方“导出旧档”拖到书签栏，然后打开旧站，在旧站点击该书签，保存 JSON 后回到这里导入。此工具只读取大明的剧情记录，不读取密钥或连接配置，也不会上传数据。</p><p><a id="old-site" target="_blank" rel="noopener">打开旧 Render</a> · <a id="old-export">导出旧档（拖到书签栏）</a></p><p id="save-message" role="status"></p><button id="save-close">关闭</button>';
    document.body.append(dialog);
    dialog.querySelectorAll('button').forEach(b => { b.style.cssText = 'padding:10px 12px;min-height:44px;margin:4px;border-radius:6px;cursor:pointer'; });
    dialog.querySelector('#old-site').href = 'https://daming-1566.onrender.com' + (c.apiPath ? '/original/' : '/storm/');
    // Fixed-origin, exact-key bookmarklet: no remote code, no network, no connection settings.
    const exportOld = function () {
      if (location.origin !== 'https://daming-1566.onrender.com') return alert('请先打开旧 Render 大明页面，再点击此书签。');
      const saves = [];
      for (const namespace of ['echo.ming1566.original.v2','echo.ming1566.cinema.v1']) {
        const read = (k, fallback = null) => { try { return JSON.parse(localStorage.getItem(namespace + '.' + k)) ?? fallback; } catch { return fallback; } };
        const id = read('run'), checkpoint = read('checkpoint.' + id);
        if (checkpoint && Array.isArray(checkpoint.actionLog)) saves.push({format:'echo-daming-save-v1',namespace,checkpoint,played:read('played.' + id, []),preferences:read('preferences', {})});
      }
      if (!saves.length) return alert('这个浏览器未找到完整大明存档。请使用之前游玩的同一浏览器和设备。');
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify({format:'echo-daming-all-saves-v1', saves})], {type:'application/json'})); a.download = '大明1566-旧站存档.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
    dialog.querySelector('#old-export').href = 'javascript:(' + encodeURIComponent(exportOld.toString()) + ')()';
    const message = error => { dialog.querySelector('#save-message').textContent = error.message || String(error); };
    dialog.querySelector('#save-export').onclick = () => { try { download(snapshot(), '大明1566-存档.json'); } catch (e) { message(e); } };
    const input = dialog.querySelector('#save-file');
    dialog.querySelector('#save-import').onclick = () => input.click();
    input.onchange = () => { if (input.files[0]) importSave(input.files[0]).catch(message); };
    dialog.querySelector('#save-close').onclick = () => dialog.close();
    dialog.onclose = () => dialog.remove(); dialog.showModal();
  }
  const mount = () => {
    const parent = document.querySelector('.cover-links') || document.querySelector('.sheet[aria-label="演出设置"]');
    if (!parent || parent.querySelector('[data-save-tools]')) return;
    const b = document.createElement('button'); b.type = 'button'; b.className = 'plain'; b.dataset.saveTools = 'true'; b.textContent = '存档迁移'; b.onclick = open; parent.append(b);
  };
  new MutationObserver(mount).observe(document.body, {childList:true, subtree:true}); mount();
})();
