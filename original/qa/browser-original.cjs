const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs'),path=require('path');
const BASE=(process.env.BASE_URL||'http://127.0.0.1:8158').replace(/\/$/,'');
const OUT='/tmp/ming-original-qa';fs.mkdirSync(OUT,{recursive:true});
const assert=(v,m)=>{if(!v)throw new Error(m)};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});const page=await context.newPage();let run=null;
 const errors=[],failed=[],checks=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',async res=>{if(res.status()>=400)failed.push({url:res.url(),status:res.status()});if(/\/original\/api\/runs/.test(res.url())&&res.status()<300){try{run=await res.json()}catch{}}});
 await page.goto(BASE+'/',{waitUntil:'networkidle'});assert(page.url().endsWith('/original/'),'root not original');
 await page.locator('[data-action="start"]').first().waitFor();await page.screenshot({path:OUT+'/original-cover.png',fullPage:true});
 assert(await page.locator('a[href="/storm/"]').count()===1,'archive missing');
 await page.locator('[data-action="cast"]').first().click();assert(await page.locator('[data-character]').count()===6,'six original cast missing');await page.locator('[data-character="hairui"]').click();assert((await page.locator('.sheet').innerText()).includes('尚未'),'Hai Rui falsely present');await page.getByRole('button',{name:'关闭',exact:true}).click();
 await page.locator('[data-action="start"]').first().click();
 const seen=[];
 for(let step=0;step<90;step++){
  await page.waitForTimeout(80);if(!run)continue;if(run.status==='ending'&&!await page.locator('.film-stage').count())break;
  if(await page.locator('.film-stage').count()){
   const before=run.revision;await page.waitForFunction(()=>{const v=document.querySelector('video.film');return v&&v.readyState>=2&&v.videoWidth>0});
   const details=await page.locator('video.film').evaluate(async v=>{if(v.paused)await v.play();v.currentTime=Math.min(v.duration*.62,v.duration-1);return {url:v.currentSrc,width:v.videoWidth,height:v.videoHeight,duration:v.duration,tracks:v.textTracks.length}});
   await page.waitForTimeout(250);const pixels=await page.locator('video.film').evaluate(v=>{const c=document.createElement('canvas');c.width=24;c.height=40;c.getContext('2d').drawImage(v,0,0,24,40);const d=c.getContext('2d').getImageData(0,0,24,40).data;let bright=0;for(let i=0;i<d.length;i+=4)if(d[i]+d[i+1]+d[i+2]>35)bright++;return bright/(24*40)});
   assert(pixels>.1,'black video '+details.url);seen.push(details);if(details.url.endsWith('/R05.mp4'))await page.screenshot({path:OUT+'/original-R05-player.png',fullPage:true});
   await page.locator('[data-action="film-skip"]').click();await page.waitForTimeout(80);assert(run.revision===before,'skip mutated state');continue;
  }
  const beatId=run.beat.id;
  if(run.beat.type==='choice')await page.locator('[data-option]').first().click();
  else if(run.beat.type==='qte')await page.locator('[data-action="qte-success"]').click();
  else if(run.beat.type==='free_input'){
   const before=JSON.stringify(run.state);await page.locator('#free-text').fill('新财源另列，军前收据仍须核查。');await page.locator('[data-action="preview"]').click();await page.locator('[data-confirm-rule]').waitFor();assert(JSON.stringify(run.state)===before,'preview mutated state');await page.locator('[data-confirm-rule]').click();
  }else{await page.locator('#story-text').click();await page.locator('[data-action="advance"]').click();}
  for(let i=0;i<200&&run.beat.id===beatId&&run.status!=='ending';i++)await page.waitForTimeout(25);
  assert(run.beat.id!==beatId||run.status==='ending','stalled '+beatId);
 }
 assert(run.status==='ending','no ending');const revision=run.revision;await page.screenshot({path:OUT+'/original-ending.png',fullPage:true});
 await page.reload({waitUntil:'networkidle'});await page.locator('[data-action="continue"]').click();await page.locator('.ending-stage').waitFor();assert(run.revision===revision,'refresh resettled');
 await page.setViewportSize({width:360,height:640});await page.locator('[data-action="home"]').click();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');
 const media=await (await context.request.get(BASE+'/original/api/media')).json();
 for(const [id,a] of Object.entries(media.assets)){
  const r=await context.request.get(BASE+'/original'+a.file,{headers:{Range:'bytes=0-127'}});assert(r.status()===206&&r.headers()['content-type']==='video/mp4','range '+id);
  if(a.subtitleFile){const v=await context.request.get(BASE+'/original'+a.subtitleFile);assert(v.status()===200&&(await v.text()).startsWith('WEBVTT'),'VTT '+id)}
  checks.push(id);
 }
 assert(!errors.length,'JS '+errors.join());assert(!failed.length,'HTTP '+JSON.stringify(failed));
 const report={base:BASE,checkedAt:new Date().toISOString(),viewport:[390,844],smallViewport:[360,640],ending:run.ending.id,revision,routeMedia:seen,rangeAndSubtitle:checks,errors,failed,freeInputConfirmed:true,skipDoesNotSettle:true,refreshStable:true};
 fs.writeFileSync(path.join(__dirname,'browser-original.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
