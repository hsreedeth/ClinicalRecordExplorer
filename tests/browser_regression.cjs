/* Run against the real app: NODE_PATH=/path/to/playwright/node_modules node tests/browser_regression.cjs
   Playwright is verification tooling only; the application has no browser-library dependency. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const ROOT=path.resolve(__dirname,'..'),BASE=process.env.CRE_BASE_URL||'http://127.0.0.1:8766';
const OUTPUT=path.join(ROOT,'artifacts','repair');fs.mkdirSync(OUTPUT,{recursive:true});
const chrome=process.env.CRE_BROWSER_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--disable-gpu'],...(fs.existsSync(chrome)?{executablePath:chrome}:{})});
 try{
 const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 const health=await(await page.request.get(BASE+'/api/health')).json();
 assert.equal(health.project_root,ROOT);assert.equal(health.report_schema_version,2);
 assert.equal(health.loaded_pipeline_sha256,crypto.createHash('sha256').update(fs.readFileSync(path.join(ROOT,'pipeline.py'))).digest('hex'));
 for(const file of ['ui.js','style.css'])assert.equal(await(await page.request.get(BASE+'/'+file)).text(),fs.readFileSync(path.join(ROOT,'web',file),'utf8'));
 await page.goto(BASE);await page.waitForSelector('#patients tr');await page.evaluate(()=>document.fonts.ready);assert.equal(await page.locator('#patients tr').count(),8);
 const viewport=await page.evaluate(()=>({innerWidth,innerHeight,devicePixelRatio,visualViewportScale:visualViewport.scale,cssZoom:getComputedStyle(document.body).zoom,cssTransform:getComputedStyle(document.body).transform}));
 assert.equal(viewport.innerWidth,1920);assert.equal(viewport.innerHeight,1080);assert.equal(viewport.visualViewportScale,1);assert.equal(viewport.devicePixelRatio,1);assert.equal(viewport.cssZoom,'1');assert.equal(viewport.cssTransform,'none');
 const style=await page.evaluate(()=>({title:parseFloat(getComputedStyle(document.querySelector('h1')).fontSize),body:parseFloat(getComputedStyle(document.body).fontSize),control:document.getElementById('threshold').getBoundingClientRect().height,rowHeights:[...document.querySelectorAll('#patients tr')].map(r=>r.getBoundingClientRect().height)}));
 assert.equal(style.title,22);assert.equal(style.body,14);assert.equal(style.control,44);assert(style.rowHeights.every(h=>h>=62&&h<=96));
 async function assertNoVisibleErrors(){for(const id of ['error','graph-error'])assert.equal(await page.locator('#'+id).isVisible(),false);assert.deepEqual(errors,[])}
 await assertNoVisibleErrors();
 assert.equal(await page.locator('#back').isVisible(),false);
 assert.equal(await page.locator('footer a').getAttribute('href'),'https://github.com/hsreedeth/ClinicalRecordExplorer');
 const shortcutSize=await page.locator('#see').boundingBox(),resetSize=await page.locator('#reset').boundingBox();
 assert.equal(shortcutSize.width,resetSize.width);assert.equal(shortcutSize.height,resetSize.height);
 await page.locator('#see-rules').click();assert.equal(await page.locator('#disclosure').evaluate(el=>el.open),true);
 assert.equal(await page.locator('#inspect-select').inputValue(),'Rules');assert.equal(await page.locator('#inspect-content li').count(),7);
 await page.waitForTimeout(700);
 const rulesTop=await page.locator('#disclosure summary').boundingBox(),toolbar=await page.locator('#study-controls').boundingBox();
 assert(rulesTop.y>=toolbar.y+toolbar.height,'Rules must scroll below the fixed toolbar');
 await page.selectOption('#inspect-select','Cohort SQL');
 const sql=await(await page.request.get(BASE+'/api/report')).json();
 assert.equal(await page.locator('#inspect-content code').textContent(),sql.sql);assert(await page.locator('#inspect-content .token.syntax-keyword').count()>0);
 for(const mode of ['Run information','Relational output']){
  await page.selectOption('#inspect-select',mode);assert(await page.locator('#inspect-content .token.syntax-key').count()>0);
  const parsed=JSON.parse(await page.locator('#inspect-content code').textContent());
  if(mode==='Run information'){const numberStyle=await page.locator('#inspect-content .syntax-number').first().evaluate(el=>({size:getComputedStyle(el).fontSize,margin:getComputedStyle(el).marginTop}));assert.equal(numberStyle.size,'13px');assert.equal(numberStyle.margin,'0px');}
  if(mode==='Relational output')assert.deepEqual(parsed,sql.tables[await page.locator('#table-select').inputValue()]);else assert.deepEqual(parsed.parameters,sql.parameters);
 }
 // Highlighted strings must stay literal, including markup-looking source evidence.
 const literal=await page.evaluate(()=>{const raw=JSON.stringify({value:'<script>alert(1)</script>',quoted:'a "quote"',number:-1.2e3},null,2);const panel=document.createElement('pre');panel.innerHTML=highlightCode(raw,'json');return {raw,text:panel.textContent,scripts:panel.querySelectorAll('script').length}});
 assert.equal(literal.text,literal.raw);assert.equal(literal.scripts,0);
 await page.locator('#disclosure').evaluate(el=>el.open=false);await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(100);
 await page.screenshot({path:path.join(OUTPUT,'overview.png')});
 await page.locator('.compare').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(OUTPUT,'comparison.png')});
 await page.locator('#trace-open').click();await page.waitForSelector('.node.stage');await page.waitForTimeout(50);
 await page.waitForTimeout(260);
 const header=await page.evaluate(()=>{const title=document.querySelector('h1').getBoundingClientRect(),back=document.getElementById('back').getBoundingClientRect();return {titleX:title.x,backRight:back.right,backInHeader:document.querySelector('header').contains(document.getElementById('back'))}});
 assert(header.backInHeader);assert(header.titleX>header.backRight);assert.equal(header.titleX,116);
 assert.equal(await page.locator('#patient-select').inputValue(),'all');assert.equal(await page.locator('.node.stage').count(),40);assert.equal(await page.locator('.node.check').count(),0);assert(await page.locator('.edge').count()>0);
 const graph=await page.evaluate(()=>{const canvas=document.getElementById('canvas').getBoundingClientRect();const nodes=[...document.querySelectorAll('.node.stage')].map(n=>{const b=n.getBoundingClientRect();return {patient:n.dataset.patient,x:b.x,y:b.y,width:b.width,height:b.height,visible:b.x>=canvas.x&&b.right<=canvas.right&&b.y>=canvas.y&&b.bottom<=canvas.bottom&&b.bottom<=innerHeight}});return {canvas:{x:canvas.x,y:canvas.y,width:canvas.width,height:canvas.height},nodes}});
 assert(graph.canvas.width>0&&graph.canvas.height>=560&&graph.canvas.height<=680);assert(graph.nodes.every(n=>n.visible),'Every stage must be visible at default desktop viewport');
 assert.deepEqual([...new Set(graph.nodes.map(n=>n.patient))],['A','B','C','D','E','F','G','H']);
 await page.screenshot({path:path.join(OUTPUT,'all-patient-lanes.png')});await assertNoVisibleErrors();
 const positions=await page.locator('.node.stage').evaluateAll(ns=>ns.map(n=>n.getAttribute('transform')));
 await page.selectOption('#patient-select','B');assert.deepEqual(await page.locator('.node.stage').evaluateAll(ns=>ns.map(n=>n.getAttribute('transform'))),positions);
 assert.equal(await page.locator('.node.stage.active').count(),5);assert.equal(await page.locator('.node.stage.muted').count(),35);assert(await page.locator('.edge.active').count()>0);assert(await page.locator('.edge.muted').count()>0);
 await page.locator('[data-expand="B:stage:source"]').click();assert(await page.locator('.node.check').count()>0);
 assert((await page.locator('[data-node="B:stage:source"]').textContent()).includes('9.1% → corrected 6.8%'));
 assert((await page.locator('.node.check').allTextContents()).join(' ').includes('9.1 %'));
 await page.screenshot({path:path.join(OUTPUT,'B-correction-expanded.png')});
 // Every displayed expanded connector maps from an original report edge, without invented rules.
 const evidence=await(await page.request.get(BASE+'/api/report')).json();const groups=new Map(evidence.lineage.groups.map(g=>[g.id,g]));
 const original=new Set(evidence.lineage.edges.map(e=>e.source+'→'+e.target));
 const displayed=await page.locator('.edge').evaluateAll(es=>es.map(e=>({source:e.dataset.source,target:e.dataset.target})));
 for(const e of displayed){const sources=groups.has(e.source)?groups.get(e.source).member_ids:[e.source],targets=groups.has(e.target)?groups.get(e.target).member_ids:[e.target];assert(sources.some(s=>targets.some(t=>original.has(s+'→'+t))))}
 await page.locator('[data-expand="B:stage:source"]').click();await page.selectOption('#patient-select','D');
 await page.locator('[data-inspect="D:stage:source"]').click();const inspector=await page.locator('#inspector').innerText();assert(inspector.includes('Current result withdrawn'));assert(inspector.includes('previous value cannot reappear'));assert(inspector.includes('withdrawn'));
 await page.screenshot({path:path.join(OUTPUT,'D-withdrawal-inspection.png')});await page.locator('#close-inspector').click();
 await page.selectOption('#patient-select','F');assert((await page.locator('[data-node="F:stage:measurement"]').textContent()).includes('Day 181: outside window'));
 await page.locator('[data-inspect="F:stage:measurement"]').click();assert((await page.locator('#inspector').innerText()).includes('window_days'));
 await page.locator('#days').fill('181');const recalculated=page.waitForResponse(r=>r.url().includes('/api/report?')&&r.url().includes('days=181'));await page.locator('#apply').click();const newReport=await(await recalculated).json();await page.waitForFunction(()=>document.querySelector('[data-node="F:stage:measurement"]').textContent.includes('Day 181: included'));
 assert.equal(newReport.counts.meets_threshold,3);assert.equal(newReport.counts.measured,4);assert.equal(await page.locator('#patient-select').inputValue(),'F');assert((await page.locator('#inspector').innerText()).includes('181'));
 await page.locator('#close-inspector').click();await page.locator('#disclosure summary').click();for(const option of ['Rules','Cohort SQL','Run information','Relational output']){await page.selectOption('#inspect-select',option);assert((await page.locator('#inspect-content').innerText()).length>0)}
 await page.selectOption('#inspect-select','Run information');assert((await page.locator('#inspect-content').innerText()).includes('duplicate_handling'));await assertNoVisibleErrors();
 await page.locator('#back').click();const reset=page.waitForResponse(r=>r.url().includes('days=180'));await page.locator('#reset').click();await reset;
 await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(OUTPUT,'narrow-overview.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
 await page.locator('#patients [data-patient="B"]').click();assert.equal(await page.locator('#patient-select').inputValue(),'B');await page.waitForTimeout(400);await page.screenshot({path:path.join(OUTPUT,'narrow-trace.png'),fullPage:true});await assertNoVisibleErrors();
 // Missing-lineage regression: overview remains usable and graph error states the repair.
 const broken=await browser.newPage({viewport:{width:1920,height:1080}});const brokenErrors=[];broken.on('pageerror',e=>brokenErrors.push(e.message));
 await broken.route('**/api/report?*',async route=>{const response=await route.fetch();const body=await response.json();delete body.lineage;await route.fulfill({response,json:body})});
 await broken.goto(BASE);await broken.waitForSelector('#patients tr');assert.equal(await broken.locator('#patients tr').count(),8);assert.equal(await broken.locator('#error').isVisible(),false);await broken.locator('#trace-open').click();assert.equal(await broken.locator('#graph-error').isVisible(),true);assert((await broken.locator('#graph-error').innerText()).includes('Restart app.py'));await broken.locator('#disclosure summary').click();await broken.selectOption('#inspect-select','Run information');assert((await broken.locator('#inspect-content').innerText()).includes('lineage_error'));assert.deepEqual(brokenErrors,[]);await broken.close();
 // Snapshot parity and rendering: same JSON contract, same UI.
 const preview=await browser.newPage();await preview.goto('file://'+path.join(ROOT,'Preview.html'));await preview.waitForSelector('#patients tr');assert.equal(await preview.locator('#apply').isDisabled(),true);const snapshot=await preview.locator('#snapshot-report').textContent();assert.deepEqual(JSON.parse(snapshot),await(await page.request.get(BASE+'/api/report')).json());await preview.locator('#trace-open').click();assert.equal(await preview.locator('.node.stage').count(),40);assert.equal(await preview.locator('#graph-error').isVisible(),false);await preview.close();
 const result={health,viewport,style,graph,errors,countsDefault:evidence.counts,counts181:newReport.counts,underlyingNodes:evidence.lineage.nodes.length,defaultCards:40,checks:['nonempty visible graph','all eight lanes','focus without repositioning','B correction expansion','real dependency edges','D withdrawal inspection','F recalculation','all disclosure modes','missing-lineage isolation','snapshot parity','narrow layout']};fs.writeFileSync(path.join(OUTPUT,'browser-checks.json'),JSON.stringify(result,null,2));console.log({viewport,graphHeight:graph.canvas.height,defaultCards:40,errors,checks:result.checks});
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
