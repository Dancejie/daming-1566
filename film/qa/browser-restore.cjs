/** Uses the temporary HTTP server owned by test_restore.py; no existing browser profile. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const BASE=process.env.BASE_URL;
const NS='echo.ming1566.cinema.v1';
const equalState=r=>({revision:r.revision,state:r.state,history:r.history,receipt:r.receipt,
  proposal:r.proposal,position:r.position,actionLog:r.actionLog,status:r.status,ending:r.ending});
let browser;
(async()=>{
 assert(BASE,'Run through test_restore.py with BASE_URL');
 browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});
 const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
 async function api(path,payload){const r=await context.request.fetch(BASE+path,{method:payload?'POST':'GET',data:payload});assert(r.ok(),await r.text());return r.json();}
 let run=await api('/api/runs',{});
 for(let i=0;i<60&&run.beat.type!=='free_input';i++){
  const b=run.beat;
  const action=b.type==='choice'?{type:'choose',optionId:b.options.find(o=>!o.disabled).id}:b.type==='qte'?{type:'qte',outcome:'success'}:{type:'advance'};
  run=await api(`/api/runs/${run.id}/act`,{...action,revision:run.revision,requestId:randomUUID()});
 }
 assert.equal(run.beat.type,'free_input');
 const page=await context.newPage();const errors=[];const posts=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
 await page.goto(BASE);
 await page.evaluate(({ns,id})=>{localStorage.setItem(`${ns}.run`,JSON.stringify(id));localStorage.setItem(`${ns}.preferences`,JSON.stringify({sound:false,media:false,accessible:true}));},{ns:NS,id:run.id});
 await page.reload();await page.locator('[data-action="continue"]').click();
 await page.locator('#free-text').fill('原账留下，核验经手收据。');
 const previewResponse=page.waitForResponse(r=>r.url().endsWith(`/api/runs/${run.id}/act`)&&r.request().method()==='POST');
 await page.locator('[data-action="preview"]').click();
 const preview=await (await previewResponse).json();
 await page.locator('[data-confirm-rule]').waitFor();
 const checkpoint=await page.evaluate(key=>JSON.parse(localStorage.getItem(key)),`${NS}.checkpoint.${run.id}`);
 assert.equal(checkpoint.revision,preview.revision);
 assert.equal(checkpoint.actionLog.at(-1).type,'free_input');
 assert.deepEqual(checkpoint.actionLog,preview.actionLog);
 await page.locator('[data-action="home"]').click();
 const missing=BASE+`/api/runs/${run.id}`;
 await page.route(missing,route=>route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'找不到这份存档'})}));
 const restoredResponse=page.waitForResponse(r=>r.url().endsWith('/api/runs/restore'));
 await page.locator('[data-action="continue"]').click();
 const restored=await (await restoredResponse).json();
 await page.locator('[data-confirm-rule]').waitFor();
 assert.notEqual(restored.id,run.id);assert.deepEqual(equalState(restored),equalState(preview));
 assert.equal(await page.evaluate(key=>JSON.parse(localStorage.getItem(key)),`${NS}.run`),restored.id);
 assert.equal(posts.filter(p=>p==='/api/runs/restore').length,1);
 await page.locator('[data-action="home"]').click();
 const current=BASE+`/api/runs/${restored.id}`;
 await page.route(current,route=>route.abort('failed'));
 const beforePosts=posts.length;
 await page.locator('[data-action="continue"]').click();
 await page.locator('.cover .error-inline').waitFor();
 assert.equal(posts.length,beforePosts,'Network failure must neither restore nor open a new run');
 assert.equal(await page.evaluate(key=>JSON.parse(localStorage.getItem(key)),`${NS}.run`),restored.id);
 await page.unroute(current);
 await page.route(current,route=>route.fulfill({status:500,contentType:'application/json',body:'{"error":"temporary failure"}'}));
 await page.locator('[data-action="continue"]').click();await page.locator('.cover .error-inline').waitFor();
 assert.equal(posts.length,beforePosts,'HTTP 500 must not restore');
 await page.unroute(current);
 await page.route(current,route=>route.fulfill({status:404,contentType:'application/json',body:'{"error":"missing"}'}));
 await page.evaluate(key=>localStorage.removeItem(key),`${NS}.checkpoint.${restored.id}`);
 await page.locator('[data-action="continue"]').click();await page.locator('.cover .error-inline').waitFor();
 assert.match(await page.locator('.cover .error-inline').textContent(),/没有完整的动作记录/);
 assert.equal(posts.length,beforePosts,'Missing checkpoint must not open a run');
 assert.deepEqual(errors,[]);
 console.log('PASS browser: authoritative preview checkpoint, 404 replay, new run ID, exact state; network/500/missing checkpoint never start a run.');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close();});
