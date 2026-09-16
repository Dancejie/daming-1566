const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs');
(async()=>{
 const base=(process.env.BASE_URL||'http://127.0.0.1:8158').replace(/\/$/,'');const browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:390,height:844}});
 await page.goto(base+'/original/',{waitUntil:'domcontentloaded'});
 const result=await page.evaluate(async()=>{
  const data=await(await fetch('/original/api/media')).json();const rows=[];
  const v=document.createElement('video');v.muted=true;v.playsInline=true;v.style.cssText='position:fixed;inset:0;width:100%;height:100%;z-index:1000;background:black';document.body.append(v);
  for(const [id,a]of Object.entries(data.assets)){
   let timer;
   const loaded=new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(Error(id+' decode timeout')),30000);v.onloadeddata=resolve;v.onerror=()=>reject(Error(id+' media error'))});
   v.src='/original'+a.file;v.load();await loaded;clearTimeout(timer);await v.play();
   v.currentTime=Math.min(v.duration-1,Math.max(1,v.duration*.62));await new Promise(resolve=>v.onseeked=resolve);
   const c=document.createElement('canvas');c.width=30;c.height=50;c.getContext('2d').drawImage(v,0,0,30,50);const d=c.getContext('2d').getImageData(0,0,30,50).data;let bright=0;for(let i=0;i<d.length;i+=4)if(d[i]+d[i+1]+d[i+2]>35)bright++;
   if(!v.videoWidth||bright/1500<.1)throw Error(id+' black decoded frame');
   rows.push({id,width:v.videoWidth,height:v.videoHeight,duration:v.duration,nonBlackFraction:bright/1500});v.pause();
  }v.remove();return rows;
 });
 if(result.length!==12)throw Error('Expected all 12 reviewed clips, got '+result.length);
 fs.writeFileSync(__dirname+'/browser-all-media.json',JSON.stringify({base,checkedAt:new Date().toISOString(),clips:result},null,2));console.log('PASS all 12 public-path clips decode and have nonblack sampled frames:',result.map(x=>x.id).join(','));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
