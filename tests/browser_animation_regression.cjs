/* NODE_PATH=/path/to/playwright/node_modules node tests/browser_animation_regression.cjs */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const BASE=process.env.CRE_BASE_URL||'http://127.0.0.1:8766';
const chrome=process.env.CRE_BROWSER_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

(async()=>{
 const browser=await chromium.launch({headless:true,...(fs.existsSync(chrome)?{executablePath:chrome}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1920,height:1080}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(BASE);await page.waitForSelector('#patients tr');
  await page.evaluate(()=>{
   window.countHistory=[2];
   new MutationObserver(()=>{const value=Number(document.querySelector('#metrics .highlight .number').textContent);if(value!==countHistory.at(-1))countHistory.push(value)}).observe(document.getElementById('metrics'),{subtree:true,childList:true,characterData:true});
  });
  async function recalculate(threshold,days){
   await page.locator('#threshold').fill(String(threshold));await page.locator('#days').fill(String(days));
   await page.evaluate(()=>document.getElementById('study').requestSubmit());
   await page.waitForFunction(([t,d])=>report.parameters.threshold===t&&report.parameters.window_days===d,[threshold,days]);
  }
  await recalculate(6,181);
  assert(await page.locator('#comparison .fill').last().evaluate(el=>el.getAnimations().some(a=>a.playState==='running')),'The comparison bar should animate');
  assert(await page.locator('#patients .cell-update').count()>0,'Changed table cells should animate');
  assert(await page.locator('#patients [data-patient="F"] td').evaluateAll(cells=>cells.some(cell=>cell.getAnimations().some(a=>a.playState==='running'))));
  await page.waitForFunction(()=>document.querySelector('#metrics .highlight .number').textContent==='4');
  assert.deepEqual(await page.evaluate(()=>countHistory),[2,3,4]);
  await page.waitForTimeout(750);
  await recalculate(8,180);
  await page.waitForFunction(()=>document.querySelector('#metrics .highlight .number').textContent==='2');
  assert.deepEqual(await page.evaluate(()=>countHistory),[2,3,4,3,2]);
  await page.waitForTimeout(750);
  // Repeating the same parameters must not animate unchanged table cells.
  await page.evaluate(()=>{window.renderCount=0;new MutationObserver(()=>renderCount++).observe(document.getElementById('patients'),{childList:true})});
  await recalculate(8,180);await page.waitForFunction(()=>renderCount>0);
  assert.equal(await page.locator('#patients .cell-update').count(),0);
  // A fresh result during a flip must replace the old animation cleanly.
  await recalculate(6,181);await recalculate(8,180);await page.waitForTimeout(750);
  assert.equal(await page.locator('#metrics .highlight .number').textContent(),'2');
  await page.locator('#see').click();await page.waitForSelector('.node.stage');
  const statuses=await page.locator('.node.stage .decision').evaluateAll(labels=>labels.map(label=>({text:label.textContent,color:getComputedStyle(label).fill})));
  assert(statuses.some(label=>label.text.startsWith('pass')&&label.color==='rgb(35, 131, 31)'));
  assert(statuses.some(label=>label.text.startsWith('fail')&&label.color==='rgb(189, 48, 48)'));
  await page.locator('#zoom-in').click();
  const viewBefore=await page.evaluate(()=>({...viewport}));
  await recalculate(6,181);
  assert.deepEqual(await page.evaluate(()=>({...viewport})),viewBefore,'Recalculation should preserve graph zoom and pan');
  assert(await page.locator('[data-node="F:stage:measurement"] .card-inspect').evaluate(el=>el.getAnimations().some(a=>a.playState==='running')),'Changed lineage cards should animate');
  assert((await page.locator('[data-node="F:stage:measurement"] .decision').getAttribute('class')).includes('status-pass'));
  await page.waitForTimeout(750);
  await page.emulateMedia({reducedMotion:'reduce'});await page.locator('#back').click();
  await recalculate(8,180);
  assert.equal(await page.locator('#metrics .highlight .number').textContent(),'2');
  assert.equal(await page.locator('#comparison .fill').last().evaluate(el=>el.getAnimations().length),0);
  assert.equal(await page.locator('#patients .cell-update').evaluateAll(cells=>cells.reduce((n,cell)=>n+cell.getAnimations().length,0)),0);
  assert.deepEqual(errors,[]);
  console.log('Passed: sequential counts in both directions, animated bars/cells/lineage, unchanged values, pass/fail colours, reduced motion.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
