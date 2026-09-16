/** Run only after M01–M09 are ready. Uses one newly created, isolated API run.
 * PLAYWRIGHT_MODULE may name a module or its absolute installation path.
 * Optional: BASE_URL, PLAYWRIGHT_CHANNEL, FFPROBE_BIN.
 * One temporary player screenshot is left for review; no videos are copied.
 */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const {spawnSync} = require('node:child_process');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8156';
const ROOT = path.resolve(__dirname, '..');
const NS = 'echo.ming1566.cinema.v1';
const SHOTS = Array.from({length:9}, (_, i) => `M${String(i + 1).padStart(2, '0')}`);
const publicRoute = {
  'S000.04':'promise.evidence', 'S001.05':'ledger.public',
  'S002.04':'grain.audit', 'S004.05':'army.separate', 'S005.06':'final.public'
};
const report = {
  checkedAt:new Date().toISOString(), baseUrl:BASE, passed:false,
  scope:'Six scenes and the public ending in the real game; nine standalone native-video samples are reported separately.',
  viewport:{width:390,height:844}, isolatedRunId:null,
  gameContexts:[], standaloneMedia:[], legalActions:[], errors:[], failedRequests:[],
  limits:['No word-for-word human listening or identity approval is claimed.',
    'M08 and M09 standalone samples are not proof of reaching their ending contexts.'],
  temporaryScreenshots:[],
  retainedArtifacts:'This script plus compact JSON/Markdown reports; one /tmp screenshot for review, no media copies.'
};
let browser;

async function api(route, body) {
  const response = await fetch(new URL(route, BASE), {
    method:body === undefined ? 'GET' : 'POST',
    headers:{'Content-Type':'application/json'},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})
  });
  const result = await response.json();
  assert(response.ok, `${route}: ${response.status} ${JSON.stringify(result)}`);
  return result.run || result;
}
const storedState = run => ({
  id:run.id, revision:run.revision, scene:run.scene?.id, beat:run.beat?.id,
  status:run.status, state:run.state, history:run.history,
  receipt:run.receipt, ending:run.ending, proposal:run.proposal
});
async function unchanged(baseline, action) {
  const current = await api(`/api/runs/${baseline.id}`);
  assert.deepEqual(storedState(current), storedState(baseline), `${action} changed the server run`);
}
async function legalAct(run, action) {
  const next = await api(`/api/runs/${run.id}/act`, {
    ...action, revision:run.revision, requestId:randomUUID()
  });
  report.legalActions.push({beat:run.beat?.id,type:action.type,optionId:action.optionId,
    revisionBefore:run.revision,revisionAfter:next.revision});
  return next;
}
async function progress(run) {
  const beat = run.beat;
  if (beat.type === 'choice') {
    const optionId = publicRoute[beat.id];
    assert(optionId, `Missing authored QA route for ${beat.id}`);
    const option = beat.options.find(o => o.id === optionId);
    assert(option && !option.disabled && option.enabled !== false, `QA option unavailable: ${optionId}`);
    return legalAct(run, {type:'choose',optionId});
  }
  if (beat.type === 'free_input') {
    const preview = await legalAct(run, {type:'free_input',text:'先核实原账和经手收据，分别封存证据。'});
    assert.equal(preview.proposal?.ruleId, 'reply.records');
    return legalAct(preview, {type:'choose',optionId:preview.proposal.ruleId});
  }
  if (beat.type === 'qte') return legalAct(run, {type:'qte',outcome:'success'});
  return legalAct(run, {type:'advance'});
}
function collectErrors(page, label) {
  page.on('pageerror', e => report.errors.push({context:label,message:e.message}));
  page.on('response', response => {
    if (response.status() >= 400) report.failedRequests.push({context:label,url:response.url(),status:response.status()});
  });
}
async function measurePlayback(page, selector) {
  await page.locator(selector).waitFor({state:'visible'});
  // Continue/replay is a real click; browsers may still request a second playback gesture.
  for (let i = 0; i < 24; i++) {
    const playing = await page.locator(selector).evaluate(v => !v.paused && v.readyState >= 2 && v.currentTime > 0);
    if (playing) break;
    const retry = page.locator('#film-play');
    if (await retry.isVisible()) await retry.click();
    await page.waitForTimeout(250);
  }
  const read = () => page.locator(selector).evaluate(v => ({
    currentTime:v.currentTime, paused:v.paused, muted:v.muted, volume:v.volume,
    readyState:v.readyState, videoWidth:v.videoWidth, videoHeight:v.videoHeight,
    decodedFrames:v.getVideoPlaybackQuality?.().totalVideoFrames ?? null,
    decodedAudioBytes:typeof v.webkitAudioDecodedByteCount === 'number' ? v.webkitAudioDecodedByteCount : null,
    source:v.currentSrc
  }));
  const before = await read();
  assert(!before.paused && !before.muted && before.volume > 0, `Native video must play with sound enabled: ${JSON.stringify(before)}`);
  assert(before.videoWidth > 0 && before.videoHeight > 0, 'Video dimensions must be decoded');
  await page.waitForTimeout(1000);
  const after = await read();
  assert(after.currentTime > before.currentTime + 0.35, 'Video time did not advance');
  assert(!after.muted && !after.paused, 'Video stopped or became muted during the sample');
  return {before,after,deltaSeconds:Number((after.currentTime-before.currentTime).toFixed(3))};
}
async function measureSubtitles(page) {
  await page.waitForFunction(()=>{
    const element=document.querySelector('video.film track');
    return element?.readyState===2 && element.track.mode==='showing' && element.track.activeCues?.length>0;
  }, null, {timeout:10000});
  const subtitle=await page.locator('video.film track').evaluate(element=>({
    source:element.src,readyState:element.readyState,mode:element.track.mode,
    cueCount:element.track.cues.length,activeCueCount:element.track.activeCues.length,
    cueText:element.track.activeCues[0].text,line:element.track.activeCues[0].line,
    snapToLines:element.track.activeCues[0].snapToLines
  }));
  assert.equal(subtitle.line,65,'Subtitle must clear the lower film controls');
  assert.equal(subtitle.snapToLines,false,'Subtitle line must be a percentage');
  const response=await fetch(subtitle.source);
  assert(response.ok,'Subtitle response failed');
  subtitle.contentType=response.headers.get('content-type');
  assert.match(subtitle.contentType,/^text\/vtt(?:;|$)/i,'Subtitle MIME must be text/vtt');
  assert.match(subtitle.contentType,/charset=utf-8/i,'Subtitle MIME must specify UTF-8');
  assert.match(await response.text(),/^WEBVTT/,'Subtitle must contain a valid VTT header');
  return subtitle;
}
async function testGameContext(page, run, assets) {
  await page.goto(BASE, {waitUntil:'networkidle'});
  await page.locator('[data-action="continue"]').first().click();
  const expectedShot = run.status === 'ending' ? run.ending.shotId : run.scene.shotId;
  const caption = await page.locator('.film-controls small').textContent();
  const soundButton = page.getByRole('button',{name:'关闭声音',exact:true});
  assert(await soundButton.isVisible(), 'Game sound setting is not enabled');
  const first = await measurePlayback(page, 'video.film');
  const subtitle=await measureSubtitles(page);
  assert.equal(first.after.source,new URL(assets[expectedShot].file,BASE).href,'Wrong scene clip');
  if (run.scene.id === 'S004' && run.status !== 'ending') {
    assert.equal(caption, run.scene.mediaCaption);
    assert.equal(caption, '来函所述 · 东南军营');
    assert.notEqual(caption, run.scene.location);
    const screenshot='/tmp/ming1566-subtitles-qa.png';
    await page.screenshot({path:screenshot,fullPage:true});
    report.temporaryScreenshots.push(screenshot);
  }
  await unchanged(run, 'initial playback');

  await page.locator('[data-action="film-skip"]').click();
  await page.locator('video.film').waitFor({state:'detached'});
  await unchanged(run, 'skip');
  await page.locator('[data-action="replay-media"]').click();
  const replay = await measurePlayback(page, 'video.film');
  await unchanged(run, 'replay');
  await page.locator('[data-action="film-text"]').click();
  await page.locator('video.film').waitFor({state:'detached'});
  await unchanged(run, 'switch to text');
  if (run.status !== 'ending') {
    assert.equal(await page.locator('.scene-location > span').textContent(), run.scene.location,
      'Text mode must restore the current player location');
  }
  // Manual replay remains available even when the player's preference is text.
  await page.locator('[data-action="replay-media"]').click();
  const textModeReplay = await measurePlayback(page, 'video.film');
  await page.locator('[data-action="film-skip"]').click();
  await page.locator('video.film').waitFor({state:'detached'});
  await unchanged(run, 'text-mode replay then skip');
  report.gameContexts.push({sceneId:run.scene.id,beatId:run.beat?.id,status:run.status,
    endingId:run.ending?.id,shotId:expectedShot,revision:run.revision,historyLength:run.history.length,
    caption,first,subtitle,replay,textModeReplay,serverStateUnchanged:true});
  console.log(`PASS game ${expectedShot} ${run.scene.id} revision=${run.revision}`);
}
function probeAudio(file) {
  const result = spawnSync(process.env.FFPROBE_BIN || 'ffprobe', [
    '-v','error','-select_streams','a','-show_entries','stream=codec_name,sample_rate,channels',
    '-of','json',new URL(file, BASE).href
  ], {encoding:'utf8',timeout:20000});
  assert.equal(result.status,0,`ffprobe failed: ${result.error?.message || result.stderr}`);
  const streams = JSON.parse(result.stdout).streams || [];
  assert(streams.length > 0, `No audio stream in ${file}`);
  return streams;
}
async function testStandalone(context, assets) {
  const page = await context.newPage();
  collectErrors(page, 'standalone-native-video');
  // Keep the samples on the game's origin; opaque about:blank origins may block local media.
  const sampleUrl=new URL('/__qa__/native-video',BASE).href;
  await page.route(sampleUrl,route=>route.fulfill({status:200,contentType:'text/html',
    body:'<!doctype html><html><body style="margin:0;background:#111;color:#fff"><button id="native-play">播放抽查</button><video id="native-video" playsinline preload="auto" style="display:block;width:300px;height:530px"></video></body></html>'}));
  for (const shotId of SHOTS) {
    const asset = assets[shotId];
    await page.goto(sampleUrl);
    await page.evaluate(url => {
      const video = document.querySelector('video');
      video.src = url; video.muted = false; video.volume = 1;
      document.querySelector('button').onclick = () => video.play();
    }, new URL(asset.file, BASE).href);
    await page.locator('#native-play').click();
    const sample = await measurePlayback(page, '#native-video');
    const audioStreams = probeAudio(asset.file);
    await page.locator('video').evaluate(v => {v.pause();v.removeAttribute('src');v.load();});
    report.standaloneMedia.push({shotId,sample,audioStreams,
      scope:'Standalone native-video decode/play sample; not an additional game route.'});
    console.log(`PASS standalone ${shotId} sound=${audioStreams[0].codec_name}`);
  }
  await page.close();
}
function writeReport() {
  const md = [
    '# 大明1566 · 原生影片浏览器验收', '',
    `- 时间：${report.checkedAt}`, `- 结果：${report.passed?'通过':'未通过'}`,
    `- 地址：${BASE}`, `- 独立测试存档：${report.isolatedRunId || '尚未创建'}`,
    `- 实际游戏情境：${report.gameContexts.length}/7（六场与公开结局）。`,
    `- 独立原生视频抽查：${report.standaloneMedia.length}/9；M08/M09 不计作实际结局路径验证。`,
    '- 每段实际游戏影片均检查播放时间增长、非零画面尺寸、未静音与游戏声音设置；跳过、重播、切换图文后比对服务器 revision/history/state/receipt。',
    '- M05 影片地点须为“来函所述 · 东南军营”；切回图文须恢复玩家当前地点。',
    '- 各真实影片字幕须成功加载、showing 且有活跃 cue；字幕位于 65%，HTTP 类型为 text/vtt; charset=utf-8。',
    '- 原生视频抽查同时用 ffprobe 确认音轨；不宣称已逐句人工听审。',
    '- 使用全新浏览器上下文与合法 API 创建的存档；未操作已有用户存档。',
    '- 仅暂存一张真实播放器截图于 /tmp 供复核后统一清理；无媒体副本或临时编码。',
    '', '| 情境 | 影片 | revision | 播放增量（秒） | 地点说明 | 进度保护 |',
    '|---|---|---:|---:|---|---|',
    ...report.gameContexts.map(c=>`| ${c.endingId || c.sceneId} | ${c.shotId} | ${c.revision} | ${c.first.deltaSeconds} | ${c.caption} | 通过 |`),
    '', `浏览器错误：${report.errors.length}；HTTP 错误：${report.failedRequests.length}。`,
    report.failure ? `失败详情：${report.failure}` : '',
    '', '完整机器结果：`browser-media.json`。', ''
  ].join('\n');
  fs.writeFileSync(path.join(ROOT,'qa/browser-media.json'),JSON.stringify(report,null,2)+'\n');
  fs.writeFileSync(path.join(ROOT,'qa/browser-media-qa.md'),md);
}
(async () => {
  const bootstrap = await api('/api/bootstrap');
  const assets = bootstrap.media?.assets || {};
  const missing = SHOTS.filter(id=>assets[id]?.status !== 'ready' || !assets[id]?.file);
  if (missing.length) {
    console.log(`NOT RUN: waiting for all nine ready clips; missing ${missing.join(', ')}`);
    process.exitCode = 2;
    return;
  }
  if (process.argv.includes('--preflight')) {
    console.log('READY: all nine runtime clips are available. No test run created.');
    return;
  }
  report.storyVersion = bootstrap.story.version;
  browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  const context = await browser.newContext({viewport:report.viewport,reducedMotion:'reduce'});
  let run = await api('/api/runs', {});
  report.isolatedRunId = run.id;
  await context.addInitScript(({ns,id,origin})=>{
    if(location.origin !== origin)return;
    localStorage.setItem(`${ns}.run`,JSON.stringify(id));
    localStorage.setItem(`${ns}.preferences`,JSON.stringify({sound:true,media:true,accessible:true}));
  }, {ns:NS,id:run.id,origin:new URL(BASE).origin});
  const page = await context.newPage();
  collectErrors(page, 'real-game');
  const tested = new Set();
  for (let step=0;step<100;step++) {
    if (run.status === 'ending') {
      assert.equal(run.ending.id,'public');
      await testGameContext(page,run,assets);
      break;
    }
    if (!tested.has(run.scene.id)) {
      assert.equal(run.beat.id,run.scene.firstBeatId,'Scene clip must be tested at its real entry beat');
      await testGameContext(page,run,assets);
      tested.add(run.scene.id);
    }
    run = await progress(run);
  }
  assert.equal(tested.size,6);
  assert.equal(report.gameContexts.length,7);
  await page.close();
  await testStandalone(context,assets);
  assert.equal(report.standaloneMedia.length,9);
  assert.equal(report.errors.length,0,'Browser JavaScript errors');
  assert.equal(report.failedRequests.length,0,'HTTP request failures');
  report.passed = true;
  writeReport();
  console.log(`PASS: seven game contexts, nine native video samples; run=${run.id}`);
})().catch(error=>{
  report.failure = error.stack || error.message;
  writeReport();
  console.error(report.failure);
  process.exitCode = 1;
}).finally(async()=>{if(browser)await browser.close();});
