"""Render the target evaluation report as one self-contained HTML page.

The page script has two parts. ``RENDER_SCRIPT`` holds pure functions that turn the report
data ``V`` and a view state into HTML strings, so tests can run them in Node. ``WIRING_SCRIPT``
holds the view state, puts each section into the page, and handles clicks.
"""

from __future__ import annotations

import json
from typing import Any

from ._report_styles import REPORT_CSS

REPORT_BODY = """\
<main class="report-shell">
  <header id="report-head"></header>
  <section id="score" aria-label="Score"></section>
  <section id="spec" aria-labelledby="spec-title"></section>
  <section id="results" aria-labelledby="results-title"></section>
  <section id="unmapped" class="unmapped" aria-labelledby="unmapped-title" hidden></section>
  <section id="run-details"></section>
</main>
<div id="drawer"></div>
"""

RENDER_SCRIPT = r"""
const esc=value=>String(value??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const pct=rate=>rate===null||rate===undefined?"—":`${rate}%`;
const isLow=(V,rate)=>rate!==null&&rate!==undefined&&rate<V.passRateTarget;
const lowClass=(V,rate)=>isLow(V,rate)?" low":"";
const tip=text=>`<span class="ibtn" tabindex="0" aria-label="About this">i<span class="tip">${text}</span></span>`;
const SCALE=[[242,207,210],[246,230,231],[241,242,242],[224,240,236],[198,230,222]];
const scaleStyle=rate=>{const p=Math.max(0,Math.min(100,rate))/25,i=Math.min(3,Math.floor(p)),t=p-i;
 return `background:rgb(${SCALE[i].map((v,j)=>Math.round(v+(SCALE[i+1][j]-v)*t)).join(",")})`};
const behaviourList=V=>(V.features||[]).flatMap(f=>f.behaviours.map(id=>V.behaviours[id]).filter(Boolean));
function renderHeader(V){
 return `<div class="head"><h1>Evaluation report</h1><div class="meta"><b>${esc(V.target)}</b><span>${esc(V.date)}</span></div></div>`;
}
function renderScore(V){
 const rate=V.scores.graderPassRate.rate,graded=behaviourList(V).filter(b=>b.rate!==null&&b.rate!==undefined);
 const below=graded.filter(b=>isLow(V,b.rate)).length,trials=V.trials||{};
 return `<div class="score"><div><div class="label">Average pass rate ${tip(`The average of the feature scores below. Each score is the average of the level under it. A criterion's score is its passed results ÷ its graded results. Skipped and errored results are not counted. The default pass-rate target is ${V.passRateTarget}%. Scores below it are shown in red.`)}</div>
 <div class="big${lowClass(V,rate)}">${pct(rate)}</div></div>
 <div class="facts"><div><span>Behaviours below the target</span><b>${graded.length?`${below} of ${graded.length}`:"—"}</b></div>
 <div><span>Trials that reached their goal</span><b>${trials.attempted?`${trials.successful} of ${trials.attempted}`:"—"}</b></div>
 <div><span>Test cases</span><b>${(V.plan.tasks||[]).length}</b></div></div></div>`;
}
const measured=b=>b.priority!==false&&b.criteria.length>0;
const criterionName=(V,id)=>(V.criteria[id]||{}).name||id;
const LIST_ICON='<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="3" cy="4" r="1.2" fill="currentColor"/><path d="M7 4h9"/><circle cx="3" cy="9" r="1.2" fill="currentColor"/><path d="M7 9h9"/><circle cx="3" cy="14" r="1.2" fill="currentColor"/><path d="M7 14h9"/></svg>';
const TREE_ICON='<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="1.5" y="7" width="4" height="4" rx="1"/><rect x="12.5" y="1.5" width="4" height="4" rx="1"/><rect x="12.5" y="12.5" width="4" height="4" rx="1"/><path d="M5.5 9H9v-5.5h3.5M9 9v5.5h3.5"/></svg>';
function renderSpecHead(V,S){
 const button=(view,label,icon)=>`<button type="button" data-view="${view}" aria-pressed="${S.view===view}">${icon}${label}</button>`;
 return `<div class="sechead"><h2 id="spec-title">Specification results</h2>${tip("<b>Every score here is an average.</b> A criterion's score is its passed results ÷ its graded results, over all test cases. A behaviour is the average of its criteria. A feature is the average of its behaviours. Skipped and errored results are not counted.")}
 <div class="seg" role="group" aria-label="View">${button("list","List",LIST_ICON)}${button("tree","Tree",TREE_ICON)}</div></div>`;
}
function renderList(V,S){
 const score=rate=>`<span class="score-val${lowClass(V,rate)}">${pct(rate)}</span>`;
 const closed=S.closed||new Set();
 return (V.features||[]).map(f=>`<button type="button" class="feat${closed.has(f.id)?"":" open"}" data-toggle-feature="${esc(f.id)}" aria-expanded="${!closed.has(f.id)}"><span><span class="car">▸</span> ${esc(f.name)}</span>${score(f.rate)}</button>`+(closed.has(f.id)?"":f.behaviours.map(id=>{
  const b=V.behaviours[id];if(!b)return "";const open=S.open.has(id);
  const head=`<button type="button" class="row b${open?" open":""}${S.selected===id?" sel":""}" data-behaviour="${esc(id)}" aria-expanded="${open}" title="${esc(b.label)}"><span class="car">${b.criteria.length?"▸":""}</span><span class="name">${esc(b.label)}</span>${measured(b)?score(b.rate):'<span class="n" style="text-align:right">Not measured</span>'}</button>`;
  const rows=open?b.criteria.map(cid=>`<button type="button" class="row c${S.selected===cid?" sel":""}" data-criterion="${esc(cid)}" title="${esc(criterionName(V,cid))}"><span></span><span class="name">${esc(criterionName(V,cid))}</span>${score((V.criteria[cid]||{}).rate)}</button>`).join(""):"";
  return head+rows}).join(""))).join("");
}
function renderTree(V,S){
 const BW=210,BH=48,GAP=12,X=[6,256,506,756],TOP=34,closed=S.closed||new Set();let y=TOP;const nodes=[],links=[];
 const featureYs=[];
 for(const f of V.features||[]){
  const ys=[],fopen=!closed.has(f.id);
  if(fopen)for(const id of f.behaviours){const b=V.behaviours[id];if(!b)continue;
   const cys=[],bopen=S.open.has(id);
   if(bopen)for(const cid of b.criteria){cys.push(y);nodes.push({x:X[3],y,name:criterionName(V,cid),rate:(V.criteria[cid]||{}).rate,id:cid,attr:`data-criterion="${esc(cid)}"`});y+=BH+GAP}
   if(!cys.length)y+=BH+GAP;
   const by=cys.length?(cys[0]+cys[cys.length-1])/2:y-BH-GAP;ys.push(by);
   nodes.push({x:X[2],y:by,name:b.label,rate:b.rate,unmeasured:!measured(b),id,attr:`data-behaviour="${esc(id)}"`,toggle:b.criteria.length?{attr:`data-toggle-behaviour="${esc(id)}"`,open:bopen}:null});
   cys.forEach((cy,k)=>links.push([X[2]+BW,by,X[3],cy,b.criteria[k]]));
  }
  if(!ys.length)y+=BH+GAP;
  const fy=ys.length?(ys[0]+ys[ys.length-1])/2:y-BH-GAP;featureYs.push(fy);
  nodes.push({x:X[1],y:fy,name:f.name,rate:f.rate,id:f.id,attr:"",toggle:f.behaviours.length?{attr:`data-toggle-feature="${esc(f.id)}"`,open:fopen}:null});
  ys.forEach((by,k)=>links.push([X[1]+BW,fy,X[2],by,f.behaviours[k]]));y+=10;
 }
 const ty=featureYs.length?(featureYs[0]+featureYs[featureYs.length-1])/2:TOP;
 nodes.push({x:X[0],y:ty,name:V.target,rate:V.scores.graderPassRate.rate,id:null,attr:""});
 featureYs.forEach((fy,k)=>links.push([X[0]+BW,ty,X[1],fy,(V.features[k]||{}).id]));
 const sel=S.selected,onPath=new Set();
 if(sel){onPath.add(sel);const bc=behaviourOf(V,sel);const bid=V.behaviours[sel]?sel:bc?bc[0]:null;if(bid){onPath.add(bid);const f=featureOf(V,bid);if(f)onPath.add(f.id)}}
 const fit=t=>{t=String(t??"");return t.length>24?t.slice(0,23)+"…":t};
 const dot=rate=>rate===null||rate===undefined?"#98a1aa":isLow(V,rate)?"#c73b45":"#087f73";
 const path=([x1,y1,x2,y2,to])=>`<path d="M${x1} ${y1+BH/2} C ${x1+20} ${y1+BH/2}, ${x2-20} ${y2+BH/2}, ${x2} ${y2+BH/2}" fill="none" stroke="${onPath.has(to)?"#087f73":"#c9d1d3"}" stroke-width="${onPath.has(to)?2:1.3}"/>`;
 const box=n=>{const picked=n.id&&n.id===sel,lit=picked||(n.id&&onPath.has(n.id));
  const toggle=n.toggle?`<g class="tree-toggle" ${n.toggle.attr} transform="translate(${BW},${BH/2})" role="button" tabindex="0" aria-label="${n.toggle.open?"Close":"Open"}"><circle r="8" fill="${n.toggle.open?"#dff3ef":"#fff"}" stroke="${n.toggle.open?"#087f73":"#b9c2c4"}" stroke-width="1.3"/><path d="M-4 0H4${n.toggle.open?"":"M0 -4V4"}" stroke="${n.toggle.open?"#087f73":"#5b6870"}" stroke-width="1.4" stroke-linecap="round"/></g>`:"";
  return `<g class="tree-node" transform="translate(${n.x},${n.y})" ${n.attr} role="button" tabindex="0"><title>${esc(n.name)}</title><rect width="${BW}" height="${BH}" rx="8" fill="${lit?"#dff3ef":"#fff"}" stroke="${lit?"#087f73":"#dce2e3"}" stroke-width="${picked?1.8:1.3}"/><circle cx="14" cy="16" r="4" fill="${dot(n.rate)}"/><text x="26" y="20" font-size="13" font-weight="700" fill="#172126">${esc(fit(n.name))}</text><text x="26" y="36" font-size="13" font-weight="700" font-family="JetBrains Mono,SFMono-Regular,Consolas,monospace" fill="${isLow(V,n.rate)?"#c73b45":"#5b6870"}">${n.rate===null||n.rate===undefined?(n.unmeasured?"Not measured":"Not graded"):n.rate+"%"}</text>${toggle}</g>`};
 const labels=["Target","Feature","Behaviour","Criterion"].map((l,k)=>`<text x="${X[k]+4}" y="16" font-size="12" font-weight="700" letter-spacing=".05em" fill="#5b6870">${l.toUpperCase()}</text>`).join("");
 return `<svg width="${X[3]+BW+16}" height="${y}" font-family="Lato,Helvetica Neue,Arial,sans-serif" aria-label="Specification tree">${labels}${links.map(path).join("")}${nodes.map(box).join("")}</svg>`;
}
const WORDS={pass:"Passed",fail:"Failed",skip:"Skipped",error:"Errored"};
const outcomeOf=r=>!r?null:r.pass?"passed":r.fail?"failed":r.error?"errored":r.skip?"skipped":null;
const countsLine=k=>{const graded=(k.pass||0)+(k.fail||0);
 return `${k.pass||0} of ${graded} graded results passed${k.skip?` · ${k.skip} skipped`:""}${k.error?` · <span class="probs"><span class="e">${k.error} errored</span></span>`:""}`};
const meanText=m=>m===null||m===undefined?"—":Number(m).toFixed(2);
const featureOf=(V,bid)=>(V.features||[]).find(f=>f.behaviours.includes(bid));
const behaviourOf=(V,cid)=>Object.entries(V.behaviours||{}).find(([,b])=>b.criteria.includes(cid));
const caseName=(V,row)=>`${esc((V.names.P||{})[row.persona]||row.persona)} · ${esc((V.names.S||{})[row.scenario]||row.scenario)}`;
function renderPanel(V,S){
 const sel=S.selected,c=V.criteria[sel];
 const big=rate=>`<span class="big${lowClass(V,rate)}">${pct(rate)}</span>`;
 if(c){const [bid,beh]=behaviourOf(V,sel)||[null,null],f=bid?featureOf(V,bid):null;
  const mark=c.grader_args&&typeof c.grader_args.threshold==="number"?`Score ≥ ${c.grader_args.threshold.toFixed(2)}`:"—";
  const rows=(V.resultTable.rows||[]).map(row=>{const r=row.results[sel];if(!r)return "";
   const squares=(row.trials||[]).map(t=>{const o=outcomeOf(t.results[sel]);return o?`<i class="q ${o}" title="Trial ${t.trial_index}: ${WORDS[{passed:"pass",failed:"fail",skipped:"skip",errored:"error"}[o]]}"></i>`:""}).join("");
   return `<button type="button" class="tc" data-goto-case="${esc(row.task_id)}" data-goto-criterion="${esc(sel)}" title="Open this test case in the results"><span><b>${esc(row.task_id)}</b><span class="n" style="display:block">${caseName(V,row)}</span></span><span class="sq">${squares}</span><span class="score-val${lowClass(V,r.rate)}">${pct(r.rate)}</span><span class="arrow">→</span></button>`}).join("");
  const parent=beh?`<div class="parent"><div class="n">${esc(f?f.name:"")} › Behaviour</div><div class="parent-row"><b>${esc(beh.label)}</b><span class="score-val${lowClass(V,beh.rate)}">${pct(beh.rate)}</span></div><p class="n">${esc(beh.statement)}</p></div>`:"";
  return `${parent}<div class="n">Criterion</div><h3>${esc(c.name)}</h3>
  <div style="margin-top:10px;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap">${big(c.rate)}<span class="n">${countsLine(c)}</span></div>
  <p class="desc">${esc(c.description)}</p>
  <div class="kv"><span>Grader</span><b>${esc(c.grader_name)}</b><span>Judge model</span><b>${esc((c.judge_models||[]).join(", ")||"None")}</b><span>Pass mark</span><b>${mark}</b><span>Mean score</span><b class="mono">${meanText(c.mean_score)}</b><span>Criterion ID</span><span class="mono">${esc(sel)}</span></div>
  <b>By test case</b><p class="n" style="margin:2px 0 4px">Click a test case to open it in the results below.</p>${rows}`}
 return `<div class="empty"><b style="color:var(--ink)">Pick a criterion</b><span>Open a behaviour, then click one of its criteria.</span></div>`;
}
function rowCounts(row){return Object.values(row.results||{}).reduce((a,r)=>({skip:a.skip+(r.skip||0),error:a.error+(r.error||0)}),{skip:0,error:0})}
function renderTable(V,S){
 const groups=(V.resultTable.features||[]).filter(f=>f.columns.length),cols=groups.flatMap(f=>f.columns.map(c=>c.criterion));
 const totals=(V.resultTable.rows||[]).map(rowCounts).reduce((a,k)=>({skip:a.skip+k.skip,error:a.error+k.error}),{skip:0,error:0});
 const head=`<div class="sechead" id="results-head"><h2 id="results-title">Results by test case</h2>${tip(`One row is one test case: one persona in one scenario, run one or more times. A cell is the criterion's pass rate over that test case's graded results. The numbers in brackets are its 95% confidence interval. A wide interval means there are too few trials to be sure. Click a test case to see each trial and its conversation.`)}</div>
 <div class="tsum"><span>Click a test case to see its trials.</span><span>${totals.skip} skipped · ${totals.error} errored</span></div>`;
 if(!cols.length||!(V.resultTable.rows||[]).length)return head+`<p class="n">No test case has a grader result.</p>`;
 const mark=cid=>cid===S.markCol?" mark":"";
 let html=`<div class="results-scroll" id="results-scroll"><table class="rt"><thead><tr><th class="stick fg" rowspan="2">Test case</th>${groups.map(f=>`<th class="fg" colspan="${f.columns.length}" title="${esc(f.name)}"><span>${esc(f.name)}</span></th>`).join("")}</tr>
 <tr>${cols.map(cid=>`<th id="col-${esc(cid)}" class="crit${mark(cid)}" title="${esc(criterionName(V,cid))}"><span>${esc(criterionName(V,cid))}</span></th>`).join("")}</tr></thead><tbody>`;
 for(const row of V.resultTable.rows||[]){
  const open=S.openCase===row.task_id,k=rowCounts(row);
  const probs=k.skip||k.error?`<div class="probs">${[k.skip?`${k.skip} skipped`:"",k.error?`<span class="e">${k.error} errored</span>`:""].filter(Boolean).join(" · ")}</div>`:"";
  html+=`<tr id="case-${esc(row.task_id)}"${S.markRow===row.task_id?' class="mark"':""}><td class="stick"><button type="button" class="case-toggle" data-case="${esc(row.task_id)}" aria-haspopup="dialog"><span class="case-name" title="${esc(((V.names.P||{})[row.persona]||row.persona)+" · "+((V.names.S||{})[row.scenario]||row.scenario))}"><b>${esc((V.names.P||{})[row.persona]||row.persona)}</b><span class="n">${esc((V.names.S||{})[row.scenario]||row.scenario)}</span>${probs}</span></button></td>`;
  html+=cols.map(cid=>{const r=row.results[cid];if(!r)return `<td class="cell"></td>`;
   const hover=`${criterionName(V,cid)}: ${r.pass||0} passed · ${r.fail||0} failed${r.skip?` · ${r.skip} skipped`:""}${r.error?` · ${r.error} errored`:""}`;
   const ci=r.confidence_interval,lo=ci?Math.round(ci.lower*100):null,hi=ci?Math.round(ci.upper*100):null;
   const bar=ci?`<span class="ci">(${lo}–${hi}%)</span>`:"";
   return r.rate===null||r.rate===undefined?`<td class="cell" aria-label="${esc(hover)}">—</td>`:`<td class="cell" style="${scaleStyle(r.rate)}" aria-label="${esc(hover+(ci?`. 95% range: ${lo}–${hi}%`:""))}"><span class="rate">${r.rate}%</span>${bar}</td>`}).join("")+"</tr>";
 }
 return head+html+"</tbody></table></div>";
}
const ENDING={succeeded:"Reached its goal",abandoned:"Stopped",error:"Error",timedOut:"Timed out"};
const SOURCE={target:"Target",userAgent:"User agent",evaluationRunner:"Evaluation runner"};
function trialCriteria(V,row,trial){
 return Object.keys(trial.results||{}).map(cid=>{const r=trial.results[cid],outcome=outcomeOf(r);
  const ev=((V.criteria[cid]||{}).evidence||[]).filter(e=>e.task_id===row.task_id&&e.trial_index===trial.trial_index).sort((a,b)=>a.result_number-b.result_number);
  return {cid,outcome,results:ev.map(e=>({outcome:e.outcome,score:e.score,reason:e.message}))}}).filter(x=>x.outcome);
}
const STATUS={succeeded:["ok","Reached its goal"],abandoned:["stop","Stopped"],error:["bad","Error"],timedOut:["time","Timed out"]};
const STATUS_SVG={ok:'<circle cx="9" cy="9" r="7.5" fill="none" stroke="#087f73" stroke-width="1.6"/><path d="M5.5 9.2l2.3 2.3 4.7-4.9" fill="none" stroke="#087f73" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
 bad:'<circle cx="9" cy="9" r="7.5" fill="none" stroke="#c73b45" stroke-width="1.6"/><path d="M6.2 6.2l5.6 5.6M11.8 6.2l-5.6 5.6" stroke="#c73b45" stroke-width="1.6" stroke-linecap="round"/>',
 stop:'<circle cx="9" cy="9" r="7.5" fill="none" stroke="#98a1aa" stroke-width="1.6"/><path d="M6 9h6" stroke="#98a1aa" stroke-width="1.6" stroke-linecap="round"/>',
 time:'<circle cx="9" cy="9" r="7.5" fill="none" stroke="#b7791f" stroke-width="1.6"/><path d="M9 5.5V9l2.5 1.8" fill="none" stroke="#b7791f" stroke-width="1.6" stroke-linecap="round"/>'};
const statusIcon=category=>{const [key,label]=STATUS[category]||["stop",category||"Unknown"];return `<svg class="st" viewBox="0 0 18 18" width="18" height="18" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title>${STATUS_SVG[key]}</svg>`};
const turnCount=t=>{const n=(t.conversation||[]).length;return n?` · ${n} turn${n===1?"":"s"}`:""};
const endingLine=t=>t.category==="succeeded"?`Reached its goal${turnCount(t)}`:`${ENDING[t.category]||t.category}: ${t.message||t.stopReason}${t.attempt>1?` · retried, attempt ${t.attempt}`:""}`;
const TAB_ORDER=[["failed","Failed"],["passed","Passed"],["errored","Errored"],["skipped","Skipped"]];
const rawResult=r=>{const shown={outcome:r.outcome};if(r.score!==null&&r.score!==undefined)shown.score=r.score;if(r.reason)shown.reason=r.reason;return JSON.stringify(shown,null,1)};
function graderOutput(x){
 const many=x.results.length>1;
 return x.results.map((r,k)=>{const label=many?`<span class="why-label">Result ${k+1}:</span> `:"";
  return r.reason?`<p class="why">${label}${esc(r.reason)}</p>`:`<div class="why">${label}<pre class="raw">${esc(rawResult(r))}</pre></div>`}).join("")||'<p class="why n">The grader returned no result for this trial.</p>';
}
function renderTrialDetail(V,S,row,trial){
 const ended=trial.category&&trial.category!=="succeeded";
 const note=ended?`<div class="endnote"><b>Ended early.</b> ${esc(ENDING[trial.category]||trial.category)}: ${esc(String(trial.message||trial.stopReason).replace(/\.\s*$/,""))}. Source: ${esc(SOURCE[trial.failureSource]||"Not recorded")}.${trial.attempt>1?` <span class="n">retried · attempt ${trial.attempt}</span>`:""}</div>`:"";
 const turns=trial.conversation||[];
 const bubble=(who,text,cls)=>`<div class="say ${cls}"><b>${esc(who)}</b><p>${esc(text)}</p></div>`;
 const conv=`<div class="chat">${turns.length?turns.map(t=>`<div class="exchange"><span class="tn">Turn ${t.turn}</span>${bubble("User",t.user||"No user message recorded","user")}${bubble(V.target,!t.target||/^\[unreadable: missing/.test(t.target)?"No reply recorded":t.target,"agent")}${(t.errors||[]).map(e=>`<div class="terr">Error: ${esc(e)}</div>`).join("")}</div>`).join(""):`<p class="n">No conversation was recorded for this trial.${trial.conversationProblem?` ${esc(trial.conversationProblem)}.`:""}</p>`}</div>`;
 const items=trialCriteria(V,row,trial),present=TAB_ORDER.filter(([o])=>items.some(x=>x.outcome===o));
 const key=`${row.task_id}:${trial.trial_index}`,marked=items.find(x=>x.cid===S.markCol);
 const pick=(S.verdictTab||{})[key]||(marked&&present.some(([o])=>o===marked.outcome)?marked.outcome:(present[0]||[])[0]);
 const tabs=present.map(([o,label])=>`<button type="button" class="vtab ${o}${o===pick?" on":""}" data-verdict-tab="${esc(key)}|${o}">${label}</button>`).join("");
 const lead={failed:"These criteria failed in this trial. Under each one is what its grader returned.",errored:"The grader could not score these criteria. This says nothing about the target.",skipped:"These criteria had nothing to grade in this trial.",passed:"These criteria passed in this trial. Under each one is what its grader returned."}[pick]||"";
 const list=items.filter(x=>x.outcome===pick);
 const rows=pick==="skipped"&&ended&&list.length>4?`<div class="why-row"><div class="why-head"><b>${list.length} criteria</b></div><p class="why">The trial ended before there was anything to grade.</p></div>`:list.map(x=>`<div class="why-row${x.cid===S.markCol?" mark":""}"><div class="why-head"><b>${esc(criterionName(V,x.cid))}</b></div>${graderOutput(x)}</div>`).join("");
 const verdicts=present.length?`<div class="verdicts"><h4>What the graders returned</h4><div class="vtabs" role="tablist">${tabs}</div><p class="n vlead">${lead}</p>${rows}</div>`:'<p class="n">No grader result was recorded for this trial.</p>';
 return `<div class="trial-detail"><h4 class="td-title">Trial ${trial.trial_index}</h4>${note}<div class="split">${conv}${verdicts}</div></div>`;
}
function renderDrawer(V,S){
 const rows=V.resultTable.rows||[],row=rows.find(r=>r.task_id===S.openCase);if(!row)return "";
 const P=V.names.P||{},SN=V.names.S||{},persona=P[row.persona]||row.persona,scenario=SN[row.scenario]||row.scenario;
 const trials=row.trials||[],index=S.trialByCase[row.task_id]||(trials[0]||{}).trial_index,trial=trials.find(t=>t.trial_index===index)||trials[0];
 const cols=(V.resultTable.features||[]).flatMap(f=>f.columns.map(c=>c.criterion)).filter(cid=>row.results[cid]);
 const word={passed:"Passed",failed:"Failed",skipped:"Skipped",errored:"Errored"};
 const head=`<tr><th class="st-col"></th><th class="sum-col">Trial</th>${cols.map(cid=>`<th class="cc${cid===S.markCol?" mark":""}" title="${esc(criterionName(V,cid))}"><span>${esc(criterionName(V,cid))}</span></th>`).join("")}</tr>`;
 const body=trials.map(t=>{const first=((t.conversation||[])[0]||{}).user||"No conversation was recorded.";
  return `<tr class="trow${t===trial?" on":""}" data-trial="${esc(row.task_id)}:${t.trial_index}" tabindex="0" role="button" aria-pressed="${t===trial}" aria-label="Show trial ${t.trial_index}"><td class="st-col">${statusIcon(t.category)}</td><td class="sum-col"><b>Trial ${t.trial_index}</b><span class="first" title="${esc(first)}">${esc(first)}</span><span class="n end">${esc(endingLine(t))}</span></td>${cols.map(cid=>{const o=outcomeOf((t.results||{})[cid]);return `<td class="pc${cid===S.markCol?" mark":""}">${o?`<span class="pill ${o}">${word[o]}</span>`:""}</td>`}).join("")}</tr>`}).join("");
 const reached=trials.filter(t=>t.category==="succeeded").length,T=V.passRateTarget;
 const ciRows=cols.map(cid=>{const r=row.results[cid],ci=r.confidence_interval,graded=(r.pass||0)+(r.fail||0);
  const lo=ci?Math.round(ci.lower*100):null,hi=ci?Math.round(ci.upper*100):null;
  const plot=ci?`<div class="ci-wide"><span class="ci-track"></span><span class="ci-rng" style="left:${lo}%;width:${hi-lo}%"></span><span class="ci-tg" style="left:${T}%"></span><span class="ci-pt" style="left:${r.rate}%"></span></div>`:'<div class="ci-wide none"></div>';
  return `<div class="ci-row${cid===S.markCol?" mark":""}"><span class="ci-name" title="${esc(criterionName(V,cid))}">${esc(criterionName(V,cid))}</span><span class="ci-rate mono${lowClass(V,r.rate)}">${pct(r.rate)}</span>${plot}<span class="ci-num mono">${ci?`${lo}–${hi}%`:"—"}</span><span class="ci-n">${r.pass||0} of ${graded} passed</span></div>`}).join("");
 const axis=`<div class="ci-row ci-axis"><span></span><span></span><div class="ci-wide ticks">${[0,25,50,75,100].filter(v=>Math.abs(v-T)>8).map(v=>`<span style="left:${v}%"${v===0?' class="first"':v===100?' class="last"':""}>${v}%</span>`).join("")}<span class="tg-label" style="left:${T}%">${T}% target</span></div><span></span><span></span></div>`;
 return `<div class="drawer-back" data-close-drawer></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="Trials of ${esc(persona)} · ${esc(scenario)}">
 <div class="drawer-head"><button type="button" class="drawer-close" data-close-drawer aria-label="Close">»</button><span class="n">Results by test case ›</span><b>${esc(persona)} · ${esc(scenario)}</b></div>
 <div class="drawer-body"><div class="drawer-main">
 <div class="dm-head"><div><h3>${esc(persona)} · ${esc(scenario)}</h3><p class="n">${esc((V.describe.S||{})[row.scenario]||"")}</p></div>
 <div class="dm-facts"><div><b class="mono">${trials.length}</b><span>trials ran</span></div><div><b class="mono">${reached}</b><span>reached their goal</span></div></div></div>
 <h4 class="dm-sec">Pass rate and 95% range for each criterion ${tip(`Each row pools this test case's ${trials.length} trials. The dark tick is the pass rate, the grey band is the 95% confidence interval, and the red line is the ${T}% target. When the band crosses the red line, these trials cannot show if the true pass rate is above or below the target.`)}</h4>
 <div class="ci-list">${axis}${ciRows}</div>
 <h4 class="dm-sec">Trials</h4>
 <div class="dt-scroll"><table class="dt"><thead>${head}</thead><tbody>${body}</tbody></table></div>
 ${trial?renderTrialDetail(V,S,row,trial):'<p class="n">No trial record was found for this test case.</p>'}</div></div></aside>`;
}
function renderUnmapped(V){
 const groups=V.unmapped||[];if(!groups.length)return "";
 const word={passed:"Passed",failed:"Failed",skipped:"Skipped",errored:"Errored"};
 return `<h2 id="unmapped-title">Results without a matching criterion</h2><p class="n">These results match no Task and Criterion in the specification. They are not part of any score.</p>`+groups.map(g=>`<div class="um"><b>${esc(g.criterion_id)} / ${esc(g.grader_fqn)}</b><p class="n">${esc(g.why)}</p>${(g.records||[]).flatMap(r=>r.results.map((x,i)=>`<div class="um-item"><span class="pill ${esc(x.outcome)}">${word[x.outcome]||esc(x.outcome)}</span> ${esc(r.task_id)} trial ${r.trial_index}${r.results.length>1?` · result ${i+1}`:""}<div>${esc(x.reason)}</div><details><summary class="n">Recorded grader settings ▸</summary><pre>${esc(JSON.stringify({grader_fqn:r.grader_fqn,grader_args:r.grader_args},null,1))}</pre></details></div>`)).join("")}</div>`).join("");
}
function renderRunDetails(V){
 const tasks=V.plan.tasks||[],trials=tasks.reduce((a,t)=>a+(t.trials||0),0);
 const models=[...new Set(Object.values(V.criteria||{}).flatMap(c=>c.judge_models||[]))];
 const facts=[["Run",V.run],["Report date",V.date||"—"],["Plan",`${(V.personas||[]).length} personas · ${(V.scenarios||[]).length} scenarios · ${trials} trials`],
  ["Grading time",V.latency===null||V.latency===undefined?"—":`${Number(V.latency).toFixed(1)} s`],["Judge models",models.join(", ")||"None"],
  ["Results without a criterion",(V.unmapped||[]).reduce((a,u)=>a+(u.records||[]).length,0)],["Unresolved criteria",(V.unresolved||[]).length],["report.json",`schema version ${V.schema_version}`]];
 return `<details class="run"><summary>Run details ▸</summary><div class="rd">${facts.map(([k,v])=>`<div><span>${esc(k)}</span>${esc(v)}</div>`).join("")}</div></details>`;
}
"""

WIRING_SCRIPT = r"""
const S={view:"list",open:new Set(),closed:new Set(),selected:null,openCase:null,trialByCase:{},markCol:null,markRow:null};
const KEEP=[".listwrap",".treewrap","#panel","#results-scroll",".drawer-main"];
const FOCUS_KEYS=["view","toggleFeature","toggleBehaviour","behaviour","criterion","case","trial","verdictTab","gotoCase"];
function focusKey(el){const host=el&&el.closest&&el.closest(FOCUS_KEYS.map(k=>`[data-${k.replace(/[A-Z]/g,c=>"-"+c.toLowerCase())}]`).join(","));
 if(!host)return null;for(const k of FOCUS_KEYS)if(host.dataset[k]!==undefined)return [k,host.dataset[k],host.tagName];return null}
const put=(id,html)=>{const root=document.getElementById(id),kept=KEEP.map(sel=>{const el=root.querySelector(sel);return el?[sel,el.scrollTop,el.scrollLeft]:null}).filter(Boolean);
 const key=root.contains(document.activeElement)?focusKey(document.activeElement):null;
 root.innerHTML=html;
 for(const [sel,top,left] of kept){const el=root.querySelector(sel);if(el){el.scrollTop=top;el.scrollLeft=left}}
 if(key){const [k,v,tag]=key,attr=`data-${k.replace(/[A-Z]/g,c=>"-"+c.toLowerCase())}`;
  const el=[...root.querySelectorAll(`[${attr}]`)].find(e=>e.dataset[k]===v&&e.tagName===tag)||[...root.querySelectorAll(`[${attr}]`)].find(e=>e.dataset[k]===v);
  if(el&&el.focus)el.focus({preventScroll:true})}};
function renderSpec(){
 put("spec",`${renderSpecHead(V,S)}<div class="inv"><div class="specview"><div class="listwrap"${S.view==="list"?"":" hidden"}>${renderList(V,S)}</div><div class="treewrap"${S.view==="tree"?"":" hidden"}>${renderTree(V,S)}</div></div><aside class="panel" id="panel">${renderPanel(V,S)}</aside></div>`);
}
function renderAll(){
 put("report-head",renderHeader(V));
 put("score",renderScore(V));
 renderSpec();
 put("results",renderTable(V,S));
 renderDrawerInto();
 const unmapped=renderUnmapped(V);put("unmapped",unmapped);document.getElementById("unmapped").hidden=!unmapped;
 put("run-details",renderRunDetails(V));
}
let opener=null;
function renderDrawerInto(){const wasOpen=!!document.querySelector("#drawer .drawer");
 if(S.openCase&&!wasOpen)opener=document.activeElement;
 document.getElementById("drawer").innerHTML=renderDrawer(V,S);document.body.classList.toggle("drawer-open",!!S.openCase);
 if(S.openCase){const close=document.querySelector(".drawer-close");if(close)close.focus({preventScroll:true})}
 else if(opener){const back=document.querySelector(`[data-case="${CSS.escape(opener.dataset&&opener.dataset.case||"")}"]`)||opener;if(back.focus)back.focus({preventScroll:true});opener=null}}
function goToEvidence(caseId,criterionId){
 S.openCase=caseId;S.markCol=criterionId;S.markRow=caseId;delete S.trialByCase[caseId];
 put("results",renderTable(V,S));renderDrawerInto();
 document.getElementById("results").scrollIntoView({behavior:"smooth",block:"start"});
 const box=document.getElementById("results-scroll"),col=document.getElementById("col-"+criterionId),sticky=box&&box.querySelector("thead .stick");
 if(box&&col)box.scrollTo({left:Math.max(0,col.offsetLeft-(sticky?sticky.offsetWidth:0)-2*col.offsetWidth),behavior:"smooth"});
}
document.addEventListener("click",event=>{
 const close=event.target.closest("[data-close-drawer]");if(close){S.openCase=null;renderDrawerInto();return}
 const vt=event.target.closest("[data-verdict-tab]");if(vt){const [key,o]=vt.dataset.verdictTab.split("|");S.verdictTab=S.verdictTab||{};S.verdictTab[key]=o;put("drawer",renderDrawer(V,S));return}
 const tab=event.target.closest("[data-trial]");if(tab){const [id,index]=tab.dataset.trial.split(":");S.trialByCase[id]=Number(index);put("drawer",renderDrawer(V,S));return}
 const toggle=event.target.closest("[data-case]");if(toggle){S.openCase=toggle.dataset.case;S.markRow=null;renderDrawerInto();return}
 const view=event.target.closest("[data-view]");if(view){S.view=view.dataset.view;renderSpec();return}
 const tf=event.target.closest("[data-toggle-feature]");if(tf){const id=tf.dataset.toggleFeature;S.closed.has(id)?S.closed.delete(id):S.closed.add(id);renderSpec();return}
 const tb=event.target.closest("[data-toggle-behaviour]");if(tb){const id=tb.dataset.toggleBehaviour;S.open.has(id)?S.open.delete(id):S.open.add(id);renderSpec();return}
 const goto=event.target.closest("[data-goto-case]");if(goto){goToEvidence(goto.dataset.gotoCase,goto.dataset.gotoCriterion);return}
 const crit=event.target.closest("[data-criterion]");if(crit){S.selected=crit.dataset.criterion;S.markCol=S.selected;renderSpec();put("results",renderTable(V,S));return}
 const beh=event.target.closest("[data-behaviour]");if(beh){const id=beh.dataset.behaviour;S.open.has(id)?S.open.delete(id):S.open.add(id);renderSpec();return}
});
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&S.openCase){S.openCase=null;renderDrawerInto();return}
 if(event.key==="Tab"&&S.openCase){const d=document.querySelector(".drawer");if(d){const f=[...d.querySelectorAll('button,[tabindex="0"],summary,a[href]')].filter(e=>!e.closest("[hidden]"));
  if(f.length){const first=f[0],last=f[f.length-1];if(!d.contains(document.activeElement)){event.preventDefault();first.focus();return}
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();return}if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();return}}}}
 if((event.key==="Enter"||event.key===" ")&&event.target.closest&&event.target.closest("tr.trow")){event.preventDefault();event.target.closest("tr.trow").click();return}if((event.key==="Enter"||event.key===" ")&&event.target.closest(".tree-node,.tree-toggle")){event.preventDefault();event.target.closest(".tree-toggle,.tree-node").dispatchEvent(new MouseEvent("click",{bubbles:true}))}});
renderAll();
"""


def render_report_page(
    report: dict[str, Any], *, title: str = "Target evaluation"
) -> str:
    """Build one offline HTML document from a report dictionary."""
    # Escape every "<" so no text in the data can end or comment out the script.
    data = json.dumps(report, separators=(",", ":"), default=str).replace(
        "<", "\\u003c"
    )
    safe_title = (
        str(title).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{safe_title}</title>\n<style>{REPORT_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{REPORT_BODY}\n<script>\n(function(){{\n"
        f"const V={data};\n{RENDER_SCRIPT}\n{WIRING_SCRIPT}\n"
        "})();\n</script>\n</body>\n</html>\n"
    )
