const $=id=>document.getElementById(id);
const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={meets_threshold:'Meets threshold',below_threshold:'Below threshold',no_eligible_result:'No eligible result',outside_cohort:'Outside diagnosis cohort'};
let report,focus='all',inspection=null,trace=false,lineageError=null,positions=new Map(),viewport={x:0,y:0,scale:1},drag=null;
const expanded=new Set();let visibleGraph=[];const STAGES=['source','diagnosis','measurement','selected','outcome'];
let overviewTrigger=null;
function switchView(value,patient='all'){
 if(value)overviewTrigger=document.activeElement;
 trace=value;document.body.classList.toggle('trace-view',value);
 $('back').disabled=!value;$('back').setAttribute('aria-hidden',String(!value));
 if(value)focus=patient;$('overview').hidden=value;$('intro').hidden=value;$('trace').hidden=!value;
 if(value){drawGraph();requestAnimationFrame(()=>{fit();$('back').focus({preventScroll:true})})}
 else if(overviewTrigger?.isConnected)overviewTrigger.focus({preventScroll:true});
 window.scrollTo(0,0);measureStudyToolbar();
}
// Tokenize raw text before escaping it, so source strings stay literal and safe.
function highlightCode(value,language){
 const pattern=language==='sql'
  ? /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:''|[^'])*')|("(?:""|[^"])*")|(:[A-Za-z_]\w*)|\b(WITH|AS|SELECT|FROM|JOIN|USING|WHERE|AND|OR|GROUP|BY|OVER|PARTITION|ORDER|DESC|ASC|IN|IS|NOT|NULL|BETWEEN|CASE|WHEN|THEN|ELSE|END|LEFT|RIGHT|INNER|OUTER|ON|DISTINCT|LIMIT|HAVING|UNION|ALL)\b|\b(MIN|MAX|COUNT|SUM|AVG|ROW_NUMBER|DATE)\b|\b(\d+(?:\.\d+)?)\b|([(),.;*+<>=|\/-])/gi
  : /("(?:\\.|[^"\\])*"\s*:)|("(?:\\.|[^"\\])*")|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([{}\[\],:])/g;
 const types=language==='sql'
  ? ['comment','string','key','parameter','keyword','function','number','punctuation']
  : ['key','string','keyword','number','punctuation'];
 let html='',cursor=0;
 for(const match of value.matchAll(pattern)){
  html+=esc(value.slice(cursor,match.index));
  const type=types[match.slice(1).findIndex(token=>token!==undefined)];
  html+=`<span class="token syntax-${type}">${esc(match[0])}</span>`;cursor=match.index+match[0].length;
 }
 return html+esc(value.slice(cursor));
}
function canAnimate(element){return !matchMedia('(prefers-reduced-motion: reduce)').matches&&element.getClientRects().length>0}
function animateNumber(element,from,to){
 if(!Number.isFinite(from)||from===to||!canAnimate(element))return;
 const digit=document.createElement('span');digit.className='count-digit';digit.textContent=from;element.replaceChildren(digit);
 const steps=Math.abs(to-from),direction=Math.sign(to-from);
 // Visit every integer, shortening each flip as the count approaches its result.
 (async()=>{
  for(let step=1;step<=steps;step++){
   const duration=steps===1?260:240-120*(step-1)/(steps-1);
   if(!element.isConnected)return;
   await digit.animate([{transform:'perspective(240px) rotateX(0deg)',opacity:1},{transform:'perspective(240px) rotateX(70deg)',opacity:0}],{duration:duration/2,easing:'ease-in',fill:'forwards'}).finished;
   if(!element.isConnected)return;
   digit.textContent=from+direction*step;
   const incoming=digit.animate([{transform:'perspective(240px) rotateX(-70deg)',opacity:0},{transform:'perspective(240px) rotateX(0deg)',opacity:1}],{duration:duration/2,easing:'ease-out'});
   // Clear the outgoing fill before the incoming animation finishes.
   digit.getAnimations().filter(animation=>animation!==incoming).forEach(animation=>animation.cancel());
   await incoming.finished;
  }
 })();
}
function animateChange(element){
 if(!canAnimate(element))return;
 element.animate([{opacity:.25,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],{duration:500,easing:'cubic-bezier(.2,.7,.2,1)'});
}
function render(){const c=report.counts;
 const previousNumbers=[...$('metrics').querySelectorAll('.number')].map(el=>Number(el.textContent));
 const previousBars=[...$('comparison').querySelectorAll('.fill')].map(el=>el.getBoundingClientRect().width/el.parentElement.getBoundingClientRect().width*100);
 const previousRows=new Map([...$('patients').children].map(row=>[row.dataset.patient,[...row.cells].map(cell=>cell.querySelector(':scope > .cell-update')?.innerHTML??cell.innerHTML)]));
 const updating=previousRows.size>0;
 const previousLayout=JSON.stringify([...positions]);
 $('metrics').innerHTML=[['Qualifying patients',c.qualifying,`${c.imported} imported · ${c.outside_cohort} outside cohort`],['Meet threshold',c.meets_threshold,'A selected eligible result at<br>or above cutoff'],['Eligible measurements',c.measured,`${c.below_threshold} below threshold`],['No eligible result',c.no_eligible_result,'Retained in cohort ·<br>level remains unknown']].map((m,i)=>`<div class="metric ${i===1?'highlight':''}"><div class="label">${m[0]}</div><div class="number">${m[1]}</div><div class="hint">${m[2]}</div></div>`).join('');
 $('comparison').innerHTML=[['Naive Query',c.naive,'naive'],['Checked Query',c.meets_threshold,'']].map(([name,n,css])=>`<div class="bar-row"><span>${name}</span><div class="track" role="meter" aria-label="${name}" aria-valuemin="0" aria-valuemax="${c.imported}" aria-valuenow="${n}"><div class="fill ${css}" style="width:${c.imported?n/c.imported*100:0}%"></div></div><strong>${n}</strong></div>`).join('');
 $('metrics').querySelectorAll('.number').forEach((element,index)=>animateNumber(element,previousNumbers[index],Number(element.textContent)));
 $('comparison').querySelectorAll('.fill').forEach((element,index)=>{
  const from=previousBars[index],to=parseFloat(element.style.width);
  if(Number.isFinite(from)&&from!==to&&canAnimate(element))element.animate([{width:from+'%'},{width:to+'%'}],{duration:700,easing:'cubic-bezier(.2,.7,.2,1)'});
 });
 $('denominator').innerHTML=`${c.meets_threshold} of ${c.qualifying} qualifying patients meet the threshold. ${c.no_eligible_result} lack an eligible result.<br>Among measured patients: ${c.meets_threshold} of ${c.measured}.`;
 $('patients').innerHTML=report.patients.map(r=>`<tr tabindex="0" aria-label="Trace patient ${esc(r.person_id)}" data-patient="${esc(r.person_id)}"><td>${esc(r.person_id)}</td><td>${esc(r.index_date)}</td><td>${r.value===null?'—':esc(r.value)+'%'}${r.effective_date?'<br><span class="small">'+esc(r.effective_date)+'</span>':''}</td><td class="${r.outcome}">${labels[r.outcome]}</td><td>${esc(r.reason)}${r.warnings.map(w=>'<p>'+esc(w)+'</p>').join('')}</td></tr>`).join('');
 document.querySelectorAll('#patients [data-patient]').forEach(r=>{
  const previous=previousRows.get(r.dataset.patient);
  [...r.cells].forEach((cell,index)=>{
   if(previous&&previous[index]!==cell.innerHTML){
    const content=document.createElement('div');content.className='cell-update';content.innerHTML=cell.innerHTML;cell.replaceChildren(content);animateChange(content);
    if(canAnimate(cell))cell.animate([{backgroundColor:'#f5e4b8'},{backgroundColor:'transparent'}],{duration:700,easing:'ease-out'});
   }
  });
  r.onclick=()=>switchView(true,r.dataset.patient);r.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();r.click()}};
 });
 if(focus!=='all'&&!report.patients.some(p=>p.person_id===focus))focus='all';
 $('patient-select').innerHTML='<option value="all">All patients</option>'+report.patients.map(r=>`<option value="${esc(r.person_id)}">Patient ${esc(r.person_id)}</option>`).join('');
 const table=$('table-select').value;$('table-select').innerHTML=Object.keys(report.tables).map(t=>`<option>${t}</option>`).join('');if(table)$('table-select').value=table;
 lineageError=validateLineage(report);renderDisclosure();if(!lineageError)layout();drawGraph(updating);if(trace&&(!updating||previousLayout!==JSON.stringify([...positions])))requestAnimationFrame(()=>fit());if(inspection&&!lineageError)inspect(inspection);scheduleToolbarMeasurement();
}
function renderDisclosure(){const type=$('inspect-select').value;$('table-label').hidden=type!=='Relational output';
 if(!report)return;
 if(type==='Rules')$('inspect-content').innerHTML=`<ol><li>Preserve original source payloads. Collapse identical copies; conflicting copies stop the run.</li><li>Select current revisions by the explicit manifest and opaque version ID. Superseded revisions remain source history.</li><li>Validate supported fields, references and mappings. Quarantine unsupported resources. Withdraw entered-in-error current records without restoring older revisions.</li><li>Require mapped diabetes, confirmed verification, active clinical status, and age ≥18 at recorded diagnosis. Use the earliest qualifying recorded date as index.</li><li>Require mapped HbA1c, final/corrected status, numeric value, UCUM %, and the inclusive day 0–${report.parameters.window_days} window.</li><li>Select latest eligible measurement. Break same-date ties by ascending stable source key; flag conflicting values.</li><li>Compare the selected value to ${report.parameters.threshold}%. Retain qualifying patients without eligible measurements as unknown.</li></ol><p>Coverage is a declared synthetic assumption. Diagnosis and measurement processing are separate branches; study window eligibility depends on the qualifying index.</p>`;
 else {const language=type==='Cohort SQL'?'sql':'json';const value=language==='sql'?report.sql:JSON.stringify(type==='Run information'?{...report.run,parameters:report.parameters,dispositions:report.dispositions,...(lineageError?{lineage_error:lineageError}:{duplicate_handling:report.lineage.duplicate_handling})}:report.tables[$('table-select').value],null,2);$('inspect-content').innerHTML=(language==='sql'?`<p>Parameters: threshold = ${report.parameters.threshold}%; window_days = ${report.parameters.window_days}</p>`:'')+`<pre class="code-panel" tabindex="0" aria-label="${esc(type)}"><code class="language-${language}">${highlightCode(value,language)}</code></pre>`}
}
// Contract: report schema 2; lineage schema 1 with a complete node partition into five stages.
function validateLineage(body){
 const l=body.lineage;
 if(body.schema_version!==2||!l||l.schema_version!==1)return 'Lineage unavailable: this report does not contain the supported evidence format. Restart app.py from this project and recalculate. The overview and export remain available.';
 if(!Array.isArray(l.nodes)||!l.nodes.length||!Array.isArray(l.edges)||!Array.isArray(l.groups)||!l.duplicate_handling||!Number.isInteger(l.duplicate_handling.duplicate_copies)||typeof l.duplicate_handling.policy!=='string')return 'Lineage unavailable: the report is missing nodes, edges, stage groups or duplicate-handling evidence. Restart the server and recalculate.';
 const ids=new Set(l.nodes.map(n=>n.id)),patients=new Set(body.patients.map(p=>p.person_id)),decisions=new Set(['pass','fail','not applicable','not evaluated']);
 if(ids.size!==l.nodes.length||l.nodes.some(n=>!patients.has(n.patient_id)||!decisions.has(n.decision)||!n.evidence||typeof n.evidence!=='object'||typeof n.reason!=='string'))return 'Lineage unavailable: invalid evidence-node identities or decisions in the report.';
 if(l.edges.some(e=>!ids.has(e.source)||!ids.has(e.target)||!patients.has(e.patient_id)))return 'Lineage unavailable: an evidence edge references a missing node or patient.';
 const assigned=[];const groupIds=new Set();
 for(const g of l.groups){if(groupIds.has(g.id)||!patients.has(g.patient_id)||!STAGES.includes(g.stage_id)||!decisions.has(g.decision)||!Array.isArray(g.member_ids)||!ids.has(g.decisive_node_id)||typeof g.summary!=='string'||typeof g.reason!=='string')return 'Lineage unavailable: an invalid stage summary was supplied.';groupIds.add(g.id);assigned.push(...g.member_ids)}
 if(assigned.length!==ids.size||new Set(assigned).size!==ids.size||assigned.some(id=>!ids.has(id)))return 'Lineage unavailable: stage groups do not contain the complete evidence graph.';
 for(const pid of patients){const stages=l.groups.filter(g=>g.patient_id===pid).map(g=>g.stage_id);if(stages.length!==5||new Set(stages).size!==5)return 'Lineage unavailable: a patient is missing a required stage.'}
 return null;
}
const CARD_W=302,CARD_H=64,CHECK_H=58,COL_STEP=330,LEFT=74,TOP=28,ROW_STEP=72;
function layout(){
 positions=new Map();visibleGraph=[];let y=TOP;
 for(const patient of report.patients){
  const groups=STAGES.map(stage=>report.lineage.groups.find(g=>g.patient_id===patient.person_id&&g.stage_id===stage));
  groups.forEach((group,column)=>{positions.set(group.id,{x:LEFT+column*COL_STEP,y,w:CARD_W,h:CARD_H});visibleGraph.push({...group,kind:'stage'})});
  let detailY=y+CARD_H+32;
  for(const group of groups){if(!expanded.has(group.id))continue;
   group.member_ids.forEach((id,index)=>{const n=report.lineage.nodes.find(n=>n.id===id);positions.set(id,{x:LEFT+(index%4)*400,y:detailY+Math.floor(index/4)*(CHECK_H+18),w:CARD_W,h:CHECK_H});visibleGraph.push({...n,kind:'check',parent_group:group.id})});
   detailY+=Math.max(28,Math.ceil(group.member_ids.length/4)*(CHECK_H+18))+28;
  }
  y=expanded.size&&groups.some(g=>expanded.has(g.id))?detailY:y+ROW_STEP;
 }
}
function lines(text,max=36){const words=String(text).split(/\s+/);const result=[''];for(const word of words){const last=result.length-1;if((result[last]+' '+word).trim().length>max&&result[last])result.push(word);else result[last]+=(result[last]?' ':'')+word}return result}
function svgText(text,x,y,css,max=36,maxLines=2){return `<text class="${css}" x="${x}" y="${y}">${lines(text,max).slice(0,maxLines).map((line,i)=>i?`<tspan x="${x}" dy="16">${esc(line)}</tspan>`:esc(line)).join('')}</text>`}
function checkDetail(n){
 const q=n.source_json&&n.source_json.valueQuantity;
 if(n.information==='source'&&q)return `${q.value===undefined?'no numeric value':q.value+' '+q.code} · ${n.source_json.status}`;
 if(n.rule_id.endsWith('-revision'))return 'Version: '+n.version;
 if(n.rule_id.endsWith('-transform'))return n.disposition;
 if(n.rule_id.endsWith('-window'))return n.evidence.day_from_index===null?'No qualifying index':'Day '+n.evidence.day_from_index+' · window '+n.evidence.window_days;
 if(n.rule_id.endsWith('-unit')&&q)return String(q.value)+' '+q.code;
 if(n.rule_id.endsWith('-mapping'))return n.evidence.local_concept||'No relational event emitted';
 const value=Object.entries(n.evidence).find(([k,v])=>v!==null&&typeof v!=='object');return value?value[0]+': '+value[1]:'No available input';
}
function mappedEdges(){
 const membership=new Map();for(const group of report.lineage.groups)for(const id of group.member_ids)membership.set(id,expanded.has(group.id)?id:group.id);
 const seen=new Set(),result=[];
 for(const e of report.lineage.edges){const source=membership.get(e.source),target=membership.get(e.target);if(source===target)continue;const key=source+'→'+target;if(seen.has(key))continue;seen.add(key);result.push({...e,source,target})}
 return result;
}
function drawGraph(animateUpdates=false){if(!report)return;
 const previousCards=animateUpdates?new Map([...$('scene').querySelectorAll('[data-node]')].map(node=>[node.dataset.node,node.querySelector('.card-inspect').textContent])):new Map();
 $('patient-select').value=focus;$('focus-label').textContent=focus==='all'?`All ${report.patients.length} patient lanes`:'Focused: Patient '+focus;
 $('graph-error').hidden=!lineageError;$('graph').hidden=!!lineageError;if(lineageError){$('graph-error-message').textContent=lineageError;$('scene').innerHTML='';$('inspector').hidden=true;return}
 let html='';
 for(const patient of report.patients){const p=positions.get(patient.person_id+':stage:source');html+=`<text class="lane-label ${focus!=='all'&&focus!==patient.person_id?'muted':''}" x="16" y="${p.y+37}">${esc(patient.person_id)}</text>`}
 for(const edge of mappedEdges()){
  const a=positions.get(edge.source),b=positions.get(edge.target),active=focus!=='all'&&edge.patient_id===focus;
  const x=a.x+a.w,y=a.y+a.h/2,tx=b.x,ty=b.y+b.h/2;
  let path;if(edge.source.includes(':stage:')&&edge.target.includes(':stage:')&&b.x-a.x>COL_STEP+1){const rail=a.y-5;path=`M${x},${y} C${x+12},${y} ${x+12},${rail} ${x+20},${rail} L${tx-20},${rail} C${tx-12},${rail} ${tx-12},${ty} ${tx},${ty}`}else if(b.x<a.x){const rail=Math.max(a.y+a.h,b.y+b.h)+10;path=`M${x},${y} C${x+16},${y} ${x+16},${rail} ${x+4},${rail} L${tx-12},${rail} C${tx-18},${rail} ${tx-18},${ty} ${tx},${ty}`}else if(a.x===b.x){const right=x+18;path=`M${x},${y} C${right},${y} ${right},${ty} ${b.x+b.w},${ty}`}else{const bend=Math.max(16,Math.abs(tx-x)*.45);path=`M${x},${y} C${x+bend},${y} ${tx-bend},${ty} ${tx},${ty}`}
  html+=`<path class="edge ${active?'active':focus==='all'?'':'muted'}" data-patient-edge="${esc(edge.patient_id)}" data-source="${esc(edge.source)}" data-target="${esc(edge.target)}" d="${path}"/>`;
 }
 for(const n of visibleGraph){const p=positions.get(n.id),active=focus!=='all'&&n.patient_id===focus;
  html+=`<g class="node ${n.kind} ${active?'active':focus==='all'?'':'muted'} ${inspection===n.id?'selected':''}" transform="translate(${p.x},${p.y})" data-node="${esc(n.id)}" data-patient="${esc(n.patient_id)}"><title>${esc(n.title)} · ${esc(n.decision)}: ${esc(n.summary||n.reason)}</title><rect class="card" width="${p.w}" height="${p.h}" rx="8"/><circle class="port" cx="0" cy="${p.h/2}" r="3"/><circle class="port" cx="${p.w}" cy="${p.h/2}" r="3"/><g class="card-inspect" tabindex="0" role="button" data-inspect="${esc(n.id)}" aria-label="Inspect patient ${esc(n.patient_id)} ${esc(n.title)}"><rect class="hit-area" width="${p.w-(n.kind==='stage'?32:0)}" height="${p.h}" fill="transparent"/>${svgText(n.title,12,17,'title',35,1)}${svgText(n.kind==='stage'?n.summary:n.decision,12,36,'summary '+(n.stage_id==='outcome'?n.outcome:''),38,1)}${svgText(n.kind==='stage'?n.decision+' · '+n.member_ids.length+(n.member_ids.length===1?' check':' checks'):checkDetail(n),12,53,'decision',42,1)}</g>`;
  if(n.kind==='stage')html+=`<g class="expand-control" tabindex="0" role="button" data-expand="${esc(n.id)}" aria-expanded="${expanded.has(n.id)}" aria-label="${expanded.has(n.id)?'Collapse':'Expand'} patient ${esc(n.patient_id)} ${esc(n.title)} checks"><rect x="${CARD_W-29}" y="7" width="22" height="22" rx="4"/><text x="${CARD_W-18}" y="23" text-anchor="middle">${expanded.has(n.id)?'−':'+'}</text></g>`;
  html+='</g>';
 }
 $('scene').innerHTML=html;
 $('scene').querySelectorAll('[data-node]').forEach(node=>{
  const item=visibleGraph.find(item=>item.id===node.dataset.node),status=item.decision;
  const label=node.querySelector(item.kind==='stage'?'.decision':'.summary');
  if(status==='pass'||status==='fail')label.classList.add('status-'+status);
  const content=node.querySelector('.card-inspect');
  if(previousCards.has(item.id)&&previousCards.get(item.id)!==content.textContent&&canAnimate(node)){
   animateChange(content);
   node.querySelector('.card').animate([{fill:'#f5e4b8'},{fill:node.classList.contains('muted')?'#fafafa':'white'}],{duration:700,easing:'ease-out'});
  }
 });
 document.querySelectorAll('[data-inspect]').forEach(el=>{el.onclick=()=>{inspect(el.dataset.inspect);drawGraph()};keyboardClick(el)});
 document.querySelectorAll('[data-expand]').forEach(el=>{el.onclick=e=>{e.stopPropagation();const id=el.dataset.expand;const opening=!expanded.has(id);opening?expanded.add(id):expanded.delete(id);layout();drawGraph();fit(opening?id.split(':')[0]:null)};keyboardClick(el)});
 transform();
}
function keyboardClick(el){el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.dispatchEvent(new MouseEvent('click',{bubbles:true}))}}}
function nodeEvidence(n){return `<article><h3>${esc(n.title)}</h3><p><strong>${esc(n.decision)}</strong> · ${esc(n.information)}</p><p>${esc(n.explanation)}</p><details><summary>Inputs and source evidence</summary><pre>${esc(JSON.stringify(n.evidence,null,2))}</pre>${n.source_key?`<p>Resource: ${esc(n.source_key)}<br>Opaque version: ${esc(n.version)}<br>Disposition: ${esc(n.disposition)}</p><details><summary>Original source JSON</summary><pre>${esc(JSON.stringify(n.source_json,null,2))}</pre></details>`:''}</details></article>`}
function inspect(id){
 const group=report.lineage.groups.find(g=>g.id===id),node=report.lineage.nodes.find(n=>n.id===id),item=group||node;
 if(!item){inspection=null;$('inspector').hidden=true;return}inspection=id;$('inspector').hidden=false;
 const members=group?group.member_ids.map(nid=>report.lineage.nodes.find(n=>n.id===nid)):[node];
 const decisive=group?report.lineage.nodes.find(n=>n.id===group.decisive_node_id):node;
 const summary=group?group.summary:node.explanation;
 $('inspector').innerHTML=`<button id="close-inspector" aria-label="Close inspection">Close ×</button><p class="small">Patient ${esc(item.patient_id)} · ${group?'stage summary':'evidence check'}</p><h2>${esc(item.title)}</h2><p><strong>${esc(item.decision)}</strong> · ${esc(summary)}</p><p>${esc(item.reason)}</p>${group?'<p class="small">A visual group of actual checks. Individual decisions below retain pass, fail, not applicable and not evaluated.</p>':''}<h3>Decisive evidence</h3>${decisive.source_key?`<p>Resource: ${esc(decisive.source_key)}<br>Opaque version: ${esc(decisive.version)}<br>Disposition: ${esc(decisive.disposition)}</p>`:''}<pre>${esc(JSON.stringify(group?group.evidence:node.evidence,null,2))}</pre>${members.map(nodeEvidence).join('')}`;
 $('close-inspector').onclick=()=>{inspection=null;$('inspector').hidden=true;drawGraph()};
}
function transform(){$('scene').setAttribute('transform',`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`)}
function fit(patient=null){
 if(lineageError||!positions.size||$('trace').hidden)return;
 const relevant=visibleGraph.filter(n=>!patient||n.patient_id===patient).map(n=>positions.get(n.id));
 if(!relevant.length)return;
 const minX=0,minY=patient?Math.min(...relevant.map(p=>p.y))-8:0,maxX=Math.max(...relevant.map(p=>p.x+p.w))+12,maxY=Math.max(...relevant.map(p=>p.y+p.h))+12;
 const box=$('canvas').getBoundingClientRect(),s=Math.min(1,(box.width-12)/(maxX-minX),(box.height-12)/(maxY-minY));
 viewport={scale:s,x:6,y:6-minY*s};transform();
}
function zoom(factor,cx=$('canvas').clientWidth/2,cy=$('canvas').clientHeight/2){if(lineageError)return;const old=viewport.scale,s=Math.max(.2,Math.min(3,old*factor));viewport.x=cx-(cx-viewport.x)*s/old;viewport.y=cy-(cy-viewport.y)*s/old;viewport.scale=s;transform()}
$('canvas').addEventListener('wheel',e=>{e.preventDefault();const b=$('canvas').getBoundingClientRect();zoom(Math.exp(-e.deltaY*.001),e.clientX-b.left,e.clientY-b.top)},{passive:false});
$('canvas').onpointerdown=e=>{if(e.target.closest('.node'))return;drag={x:e.clientX,y:e.clientY,vx:viewport.x,vy:viewport.y};$('canvas').setPointerCapture(e.pointerId)};
$('canvas').onpointermove=e=>{if(drag){viewport.x=drag.vx+e.clientX-drag.x;viewport.y=drag.vy+e.clientY-drag.y;transform()}};$('canvas').onpointerup=()=>drag=null;$('canvas').onpointercancel=()=>drag=null;
$('zoom-in').onclick=()=>zoom(1.25);$('zoom-out').onclick=()=>zoom(.8);$('fit').onclick=()=>fit();
$('patient-select').onchange=e=>{focus=e.target.value;drawGraph()};
$('graph-retry').onclick=load;

$('trace-open').onclick=()=>switchView(true);$('see').onclick=e=>{e.preventDefault();switchView(true)};$('back').onclick=()=>switchView(false);
$('see-rules').onclick=()=>{
 $('inspect-select').value='Rules';$('disclosure').open=true;renderDisclosure();
 measureStudyToolbar();
 $('disclosure').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
 $('disclosure').querySelector('summary').focus({preventScroll:true});
};
$('inspect-select').onchange=renderDisclosure;$('table-select').onchange=renderDisclosure;
async function load(){ $('apply').disabled=true;$('error').hidden=true;try{const response=await fetch(`/api/report?threshold=${encodeURIComponent($('threshold').value)}&days=${encodeURIComponent($('days').value)}`);const body=await response.json();if(!response.ok)throw Error(body.error||'Could not load report');report=body;render()}catch(e){$('error').textContent=e.message;$('error').hidden=false}finally{$('apply').disabled=false}}
$('study').onsubmit=e=>{e.preventDefault();load()};$('reset').onclick=()=>{$('threshold').value=8;$('days').value=180;load()};
$('download').onclick=()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='clinical-record-explorer-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
window.addEventListener('resize',()=>{if(trace)fit()});
// One control component: keep its normal flow space while the same DOM node is fixed.
const controls=$('study-controls'),studySlot=$('study-slot'),statisticsEnd=$('statistics-end');
let normalStudyHeight=0,compactStudyHeight=0,toolbarBoundary=0,statisticsObserver,toolbarFrame=0;
function updateStudyToolbar(){
 const persistent=trace||statisticsEnd.getBoundingClientRect().top<=toolbarBoundary;
 controls.classList.toggle('is-persistent',persistent);
 studySlot.style.minHeight=persistent?`${trace?compactStudyHeight:normalStudyHeight}px`:'';
 document.documentElement.style.setProperty('--toolbar-height',persistent?`${compactStudyHeight}px`:'0px');
 controls.dataset.persistent=String(persistent);
}
function measureStudyToolbar(){
 const wasPersistent=controls.classList.contains('is-persistent');
 controls.classList.remove('is-persistent');normalStudyHeight=Math.ceil(controls.getBoundingClientRect().height);
 controls.classList.add('is-persistent');compactStudyHeight=Math.ceil(controls.getBoundingClientRect().height);
 controls.classList.toggle('is-persistent',wasPersistent);
 const headerHeight=Math.ceil(document.querySelector('header').getBoundingClientRect().height);
 document.documentElement.style.setProperty('--header-height',`${headerHeight}px`);
 // The sentinel crosses the future toolbar's lower edge, keeping the next heading clear.
 toolbarBoundary=headerHeight+compactStudyHeight+16;
 if(statisticsObserver)statisticsObserver.disconnect();
 statisticsObserver=new IntersectionObserver(updateStudyToolbar,{rootMargin:`-${toolbarBoundary}px 0px 0px 0px`,threshold:0});
 statisticsObserver.observe(statisticsEnd);updateStudyToolbar();
}
function scheduleToolbarMeasurement(){if(toolbarFrame)return;toolbarFrame=requestAnimationFrame(()=>{toolbarFrame=0;measureStudyToolbar()})}
window.addEventListener('resize',scheduleToolbarMeasurement);
// Large scroll jumps can skip an observer intersection entirely (below → above).
let scrollFrame=0;window.addEventListener('scroll',()=>{if(scrollFrame)return;scrollFrame=requestAnimationFrame(()=>{scrollFrame=0;updateStudyToolbar()})},{passive:true});
new ResizeObserver(scheduleToolbarMeasurement).observe(document.querySelector('header'));
measureStudyToolbar();document.fonts.ready.then(scheduleToolbarMeasurement);

const snapshot=$('snapshot-report');
if(snapshot){report=JSON.parse(snapshot.textContent);render();for(const id of ['apply','reset','threshold','days','graph-retry'])$(id).disabled=true}else load();
