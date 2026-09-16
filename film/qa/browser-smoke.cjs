const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname,'..');
const QA = '/tmp/ming1566-film-qa';
fs.mkdirSync(QA,{recursive:true});
const assert=(v,m)=>{if(!v)throw new Error(m)};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,reducedMotion:'reduce'});
 const page=await context.newPage();const errors=[];const failed=[];let run=null;
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',async res=>{if(res.status()>=400)failed.push({url:res.url(),status:res.status()});if(/\/api\/runs/.test(res.url())&&res.status()<300){try{run=await res.json()}catch{}}});
 await page.goto(process.env.BASE_URL || 'http://127.0.0.1:8156/',{waitUntil:'networkidle'});
 await page.locator('[data-action="start"]').first().waitFor();
 await page.screenshot({path:path.join(QA,'cover.png'),fullPage:true});
 await page.locator('[data-action="cast"]').first().click();
 assert(await page.locator('[data-character]').count()>=6,'six cast cards missing');
 await page.locator('[data-character="hairui"]').click();
 await page.screenshot({path:path.join(QA,'character.png'),fullPage:true});
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 await page.locator('[data-action="settings"]').first().click();
 const media=page.locator('[data-pref="media"]');
 if((await media.textContent()).includes('声画'))await media.click();
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 await page.locator('[data-action="start"]').first().click();
 await page.waitForFunction(()=>document.querySelector('.stage'));
 const runIds=[];let receiptChecked=false,freeInputChecked=false,qteChecked=false;
 for(let i=0;i<130;i++){
  if(!run){await page.waitForTimeout(100);continue}
  if(!runIds.includes(run.id))runIds.push(run.id);
  if(run.status==='ending')break;
  const before=run.revision;const beforeBeat=run.beat.id;const type=run.beat.type;
  if(type==='choice'){
   if(!receiptChecked)await page.screenshot({path:path.join(QA,'choice.png'),fullPage:true});
   await page.locator('[data-option]:not([disabled])').first().click();receiptChecked=true;
  }else if(type==='free_input'){
   await page.locator('#free-text').fill('先核实账册的证据，保留原账与经手收条。');
   await page.locator('[data-action="preview"]').click();
   await page.locator('[data-confirm-rule]').waitFor();
   await page.screenshot({path:path.join(QA,'free-input.png'),fullPage:true});
   await page.locator('[data-confirm-rule]').click();freeInputChecked=true;
  }else if(type==='qte'){
   await page.locator('[data-action="qte-success"]').click();qteChecked=true;
  }else{
   await page.locator('#story-text').click();
   await page.locator('[data-action="advance"]').click();
  }
  await page.waitForFunction(rev=>!document.querySelector('#app[aria-busy="true"]')&&!!document.querySelector('.stage,.ending-stage'),before);
  for(let n=0;n<160&&run.beat.id===beforeBeat&&run.status!=='ending';n++)await page.waitForTimeout(50);
  assert(run.beat.id!==beforeBeat||run.status==='ending','UI did not advance '+type);
 }
 assert(run?.status==='ending','did not reach ending');
 assert(freeInputChecked&&qteChecked,'missing free input or QTE');
 await page.screenshot({path:path.join(QA,'ending.png'),fullPage:true});
 const endingId=run.ending.id;const endingRevision=run.revision;
 await page.reload({waitUntil:'networkidle'});
 await page.locator('[data-action="continue"]').click();
 await page.locator('.ending-stage').waitFor();
 assert(run.revision===endingRevision,'refresh changed settlement');
 await page.setViewportSize({width:360,height:640});
 await page.locator('[data-action="home"]').click();
 await page.screenshot({path:path.join(QA,'cover-short.png'),fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');
 const result={checkedAt:new Date().toISOString(),viewport:[390,844],shortViewport:[360,640],endingId,runIds,
  freeInputChecked,qteChecked,refreshRetainsRevision:true,errors,failedRequests:failed,screenshotsTemporary:QA};
 fs.writeFileSync(path.join(ROOT,'qa/browser-smoke.json'),JSON.stringify(result,null,2));
 assert(errors.length===0,'browser JS errors');assert(failed.length===0,'failed network requests');
 console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
