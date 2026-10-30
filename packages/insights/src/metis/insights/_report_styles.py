"""Styles for the self-contained target evaluation report."""

REPORT_CSS = r"""
:root{--ink:#172126;--muted:#5b6870;--line:#e3e7e8;--soft:#fafbfb;--tree:#f4f6f5;--red:#c73b45;--amber:#b7791f;
 --grey-sq:#9fb0b5;--skip-line:#b4bcc2;--t-pass:#e0f0ec;--t-pass-ink:#0b6b5c;--t-fail:#f2cfd2;--t-fail-ink:#a3262f;--t-skip:#f1f2f2;--t-err:#f7ecd6;
 --mono:"JetBrains Mono","SFMono-Regular",Consolas,monospace;--sans:Lato,"Helvetica Neue",Arial,sans-serif}
*{box-sizing:border-box}[hidden]{display:none!important}
html{background:#fff;color:var(--ink);font:15px/1.5 var(--sans)}body{margin:0}
button{font:inherit;color:inherit}
.report-shell{width:min(1800px,calc(100% - 48px));margin:0 auto;padding:28px 0 60px}
.n{color:var(--muted);font-size:14px}.mono{font-family:var(--mono)}.low{color:var(--red)}
h1,h2,h3,h4,h5,p{margin:0}
.ibtn{display:inline-flex;width:18px;height:18px;border-radius:50%;border:1.5px solid var(--muted);color:var(--muted);font:italic 800 11px Georgia,serif;align-items:center;justify-content:center;cursor:help;position:relative;vertical-align:2px;flex:0 0 auto}
.ibtn .tip{display:none;position:absolute;top:26px;left:-20px;z-index:30;width:380px;background:var(--ink);color:#fff;border-radius:8px;padding:12px 14px;font:400 14px/1.5 var(--sans);text-align:left}
.ibtn:hover .tip,.ibtn:focus .tip{display:block}
.head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding-bottom:14px;border-bottom:1px solid var(--line)}
.head h1{font-size:28px;font-weight:700;letter-spacing:-.02em}
.head .meta{display:flex;flex-direction:column;align-items:flex-end;font-size:14px;color:var(--muted)}.head .meta b{color:var(--ink);font-size:15px}
.score{display:flex;justify-content:space-between;align-items:center;gap:56px;padding:22px 0;border-bottom:1px solid var(--line)}
.score .label{font-weight:600;margin-bottom:6px}
.score .big{font-size:56px;font-weight:700;letter-spacing:-.03em;line-height:1}
.score .facts{display:flex;flex-direction:column;min-width:380px}
.score .facts div{display:flex;justify-content:space-between;align-items:baseline;gap:24px;padding:7px 0;border-top:1px solid var(--line);font-size:14px;color:var(--muted)}
.score .facts div:first-child{border-top:0}.score .facts b{font:600 16px var(--mono);color:var(--ink)}
.sechead{display:flex;align-items:center;gap:10px;margin:34px 0 10px}.sechead h2{font-size:20px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:6px;padding:3px;margin-left:auto}
.seg button{display:flex;align-items:center;gap:6px;border:0;background:transparent;padding:5px 11px;border-radius:4px;font-size:13px;color:var(--muted);cursor:pointer}
.seg button[aria-pressed="true"]{background:#f1f3f4;color:var(--ink)}.seg svg{width:17px;height:17px}
.inv{display:grid;grid-template-columns:minmax(0,1fr) minmax(480px,40%);border-top:1px solid var(--line);border-bottom:1px solid var(--line);height:70vh;min-height:360px}
.specview{display:flex;flex-direction:column;min-width:0;min-height:0;background:var(--tree)}
.listwrap{flex:1;min-height:0;overflow:auto;padding:4px 14px 14px;min-width:0}
.feat{display:flex;justify-content:space-between;width:100%;margin-top:18px;padding:0 6px 6px;border:0;background:none;cursor:pointer;font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:700}
.row{display:grid;grid-template-columns:18px minmax(0,1fr) 110px;gap:10px;align-items:center;width:100%;padding:10px 6px;border:0;border-top:1px solid var(--line);background:#fff;text-align:left;cursor:pointer}
.row:hover{background:var(--soft)}.row.b .name{font-weight:600}.row.c{padding-left:34px;border-top:1px dashed #edf0f0}
.row .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row.sel{box-shadow:inset 2px 0 0 var(--ink);background:var(--soft)}
.car{color:var(--muted);font-size:11px;display:inline-block;transition:transform .15s}.row.open .car,.feat.open .car{transform:rotate(90deg)}
.tree-toggle{cursor:pointer}
.score-val{font:600 15px var(--mono);text-align:right}
.treewrap{flex:1;min-height:0;display:flex;padding:14px;overflow:auto;background:var(--tree)}.treewrap svg{margin:auto;flex:0 0 auto}
.tree-node{cursor:pointer}
.panel{border-left:1px solid var(--line);padding:22px 12px 22px 18px;min-width:0;min-height:0;overflow-y:auto;overflow-x:hidden}
.panel h3{margin-top:4px;font-size:19px;line-height:1.3;overflow-wrap:anywhere}
.panel .big{font:700 34px var(--mono)}
.panel .desc{margin-top:12px;white-space:pre-wrap}
.parent{padding-bottom:14px;margin-bottom:14px;border-bottom:1px solid var(--line)}.parent-row{display:flex;justify-content:space-between;gap:12px;margin:2px 0 4px}
.kv{display:grid;grid-template-columns:120px 1fr;gap:7px 12px;font-size:15px;margin:16px 0;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.kv span{color:var(--muted)}
.tc{display:grid;grid-template-columns:minmax(0,1fr) auto 54px 16px;gap:10px;align-items:center;width:100%;padding:9px 8px;margin:0;border:0;border-top:1px solid #f0f2f2;border-radius:6px;background:none;text-align:left;font-size:15px;cursor:pointer}
.tc:hover{background:var(--tree)}.tc .arrow{color:var(--muted);opacity:0}.tc:hover .arrow{opacity:1}
.sq{display:inline-flex;gap:4px;vertical-align:middle}.q{width:12px;height:12px;border-radius:2px;display:block}
.q.passed{background:var(--grey-sq)}.q.failed{background:var(--red)}.q.skipped{background:#fff;border:1.5px solid var(--skip-line)}.q.errored{background:var(--amber)}
.empty{display:grid;place-content:center;text-align:center;min-height:300px;color:var(--muted)}
.tsum{display:flex;justify-content:space-between;gap:18px;font-size:14px;color:var(--muted);padding:10px 0;border-top:1px solid var(--line)}
.results-scroll{overflow:auto;max-height:640px;border:1px solid var(--line);border-radius:8px}
table.rt{border-collapse:separate;border-spacing:0;font-size:14px}
.rt th,.rt td{border-right:1px solid var(--line);border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;background:#fff;vertical-align:middle}
.rt thead th{position:sticky;top:0;z-index:3;background:var(--soft);font-size:13px;color:var(--muted);font-weight:600}
.rt thead tr:nth-child(2) th{top:39px}.rt th.fg{color:var(--ink);height:39px;max-height:39px;white-space:nowrap}.rt th.fg span{display:block;overflow:hidden;text-overflow:ellipsis}.rt th.fg:not(.stick){max-width:0}
.rt th.crit{width:118px;min-width:118px;max-width:118px;line-height:1.3;vertical-align:bottom}
.rt th.crit span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rt th.crit.mark{background:var(--ink);color:#fff}
.rt .stick{position:sticky;left:0;z-index:2;padding-top:6px;padding-bottom:6px;width:380px;min-width:380px;max-width:380px;box-shadow:1px 0 0 var(--line)}
.rt thead .stick{z-index:4}
.rt td.cell{font:600 14px var(--mono);color:var(--ink);white-space:nowrap;padding-top:6px;padding-bottom:6px}
.rt td.cell .ci{display:block;margin-top:1px;font:400 11px var(--mono);color:#9aa6ab}
.ci-track{position:absolute;left:0;right:0;top:5px;height:2px;background:#dfe4e5}
.ci-rng{position:absolute;top:2px;height:8px;border-radius:4px;background:#d3d8da}
.ci-tg{position:absolute;top:0;width:2px;height:12px;margin-left:-1px;background:var(--red)}
.ci-pt{position:absolute;top:0;width:3px;height:12px;margin-left:-1px;background:var(--ink);border-radius:1px}
.rt tr.mark>td.stick{box-shadow:inset 3px 0 0 var(--ink),1px 0 0 var(--line)}
.case-toggle{display:flex;gap:6px;align-items:baseline;width:100%;border:0;background:none;padding:0;text-align:left;cursor:pointer}
.case-toggle b{font-weight:600}
.case-name{min-width:0;line-height:1.35}.case-name b,.case-name .n{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:350px}.case-name .n{font-size:13px}
.rt td.cell .rate{display:block}
.probs{font-size:13px;color:var(--muted);margin-top:2px}.probs .e{color:var(--amber);font-weight:700}
.endnote{background:#fff;border-radius:6px;padding:8px 12px;margin-bottom:12px;font-size:14px}
.split{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:28px}
.split h4{margin-bottom:8px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.terr{font-size:13px;color:var(--red)}
.pill{display:inline-block;font-weight:700;font-size:13px;padding:2px 8px;border-radius:4px;white-space:nowrap}
.pill.passed{background:var(--t-pass);color:var(--t-pass-ink)}.pill.failed{background:var(--t-fail);color:var(--t-fail-ink)}.pill.skipped{background:var(--t-skip);color:var(--muted)}.pill.errored{background:var(--t-err);color:var(--amber)}
details summary{cursor:pointer;list-style:none}details summary::-webkit-details-marker{display:none}
.unmapped{margin-top:34px}.unmapped h2{font-size:20px;margin-bottom:6px}
.um{border-top:1px solid var(--line);padding:10px 0}.um-item{padding:6px 0 6px 16px;font-size:14px}.um-item pre{white-space:pre-wrap;font:13px var(--mono);margin:4px 0 0}
details.run{margin-top:34px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}details.run summary{font-weight:600;padding:12px 0}
.rd{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;padding:0 0 16px}.rd span{display:block;color:var(--muted);font-size:13px}
body.drawer-open{overflow:hidden}
.drawer-back{position:fixed;inset:0;z-index:60;background:rgba(23,33,38,.18)}
.drawer{position:fixed;top:0;right:0;bottom:0;z-index:61;width:min(1300px,calc(100vw - 80px));display:flex;flex-direction:column;background:#fff;border-left:1px solid var(--line);box-shadow:-12px 0 32px rgba(23,33,38,.12)}
.drawer-head{display:flex;align-items:center;gap:10px;padding:10px 18px;border-bottom:1px solid var(--line);font-size:14px}
.drawer-close{border:0;background:none;font-size:18px;color:var(--muted);cursor:pointer;padding:0 6px}
.drawer-body{flex:1;min-height:0;display:flex;flex-direction:column}
.drawer-main{overflow:auto;padding:18px 22px 28px}
.dm-head{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:12px}
.dm-head h3{font-size:19px}.dm-head p{max-width:760px;margin-top:2px}
.dt-scroll{overflow:auto;border:1px solid var(--line);border-radius:8px;margin-bottom:18px}
table.dt{border-collapse:separate;border-spacing:0;font-size:14px;min-width:100%}
.dt th,.dt td{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:middle;background:#fff}
.dt thead th{background:var(--soft);font-size:13px;color:var(--muted);font-weight:600;position:sticky;top:0}
.dt th.cc{width:112px;min-width:112px;max-width:112px;line-height:1.3;vertical-align:bottom}
.dt th.cc span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.dt th.cc.mark{background:var(--ink);color:#fff}
.dt .st-col{width:40px;text-align:center}.dt .st{display:block;margin:auto}
.dt .sum-col{width:420px;min-width:320px;max-width:520px}
.dt .sum-col b{display:block;font-weight:600}
.dt .first{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:500px}
.dt .end{display:block;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:500px}
.dt tr.trow{cursor:pointer}.dt tr.trow:hover td{background:var(--soft)}
.dt tr.trow.on td{background:#eef6f3}.dt tr.trow.on td.st-col{box-shadow:inset 3px 0 0 #087f73}
.dt td.pc{text-align:left}.dt td.pc.mark{background-image:linear-gradient(rgba(23,33,38,.05),rgba(23,33,38,.05))}
.trial-detail{border-top:1px solid var(--line);padding-top:14px}
.td-title{font-size:16px;margin-bottom:10px;color:var(--ink);text-transform:none;letter-spacing:0}
.dm-facts{display:flex;gap:28px;flex:0 0 auto}.dm-facts div{text-align:right}.dm-facts b{display:block;font-size:26px;line-height:1.1}.dm-facts span{font-size:13px;color:var(--muted)}
.dm-sec{display:flex;align-items:center;gap:8px;margin:18px 0 8px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.ci-list{border:1px solid var(--line);border-radius:8px;padding:4px 14px 8px;margin-bottom:6px}
.ci-row{display:grid;grid-template-columns:minmax(160px,260px) 52px minmax(260px,1fr) 78px 110px;gap:14px;align-items:center;padding:7px 0;border-bottom:1px solid #f0f2f2;font-size:14px}
.ci-row:last-child{border-bottom:0}.ci-row.mark{background:var(--tree);margin:0 -14px;padding:7px 14px}
.ci-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ci-rate{text-align:right;font-weight:700}.ci-num{color:var(--muted);font-size:13px}.ci-n{color:var(--muted);font-size:13px}
.ci-wide{position:relative;height:16px}.ci-wide .ci-track{top:7px}.ci-wide .ci-rng{top:3px;height:10px;border-radius:5px}.ci-wide .ci-tg{height:16px}.ci-wide .ci-pt{height:16px;top:0}
.ci-axis{border-bottom:1px solid var(--line);padding:4px 0 6px}.ci-wide.ticks{height:16px;font-size:12px;color:var(--muted)}
.ci-wide.ticks span{position:absolute;transform:translateX(-50%);white-space:nowrap}.ci-wide.ticks .first{transform:none}.ci-wide.ticks .last{transform:translateX(-100%)}
.ci-wide.ticks .tg-label{top:0;color:var(--red);font-weight:700;background:#fff;padding:0 3px}
.chat .exchange{padding:10px 0;border-top:1px solid #f0f2f2}
.chat .tn{display:block;font:600 12px var(--mono);color:var(--muted);margin-bottom:6px}
.say{max-width:78%;margin:0 0 8px}.say b{display:block;font-size:12px;color:var(--muted);font-weight:700;margin-bottom:2px}
.say p{font-size:14px;white-space:pre-wrap;overflow-wrap:anywhere}
.say.user{margin-left:auto;text-align:right}.say.agent{margin-right:auto}
.verdicts h4{display:flex;align-items:center;gap:8px}
.vtabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:4px 0 8px}
.vtab{border:0;background:none;padding:6px 10px;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer;font-weight:600;font-size:14px;color:var(--muted)}
.vtab.on{color:var(--ink);border-bottom-color:var(--ink)}.vtab.failed.on{border-bottom-color:var(--red);color:var(--red)}.vtab.errored.on{border-bottom-color:var(--amber);color:var(--amber)}.vtab.passed.on{border-bottom-color:#087f73;color:#087f73}
.vlead{margin-bottom:6px}
.why-row{padding:9px 0;border-top:1px solid #f0f2f2}.why-row.mark{background:#fff;margin:0 -8px;padding:9px 8px;box-shadow:inset 3px 0 0 var(--ink)}
.why-head{display:flex;justify-content:space-between;gap:12px;align-items:baseline}.why-head b{font-weight:600}
.why-row .why{margin-top:3px;font-size:14px;color:var(--ink);white-space:pre-wrap;overflow-wrap:anywhere}.why-row .raw{margin:2px 0 0;padding:6px 8px;background:#fff;border:1px solid var(--line);border-radius:4px;font:12px/1.4 var(--mono);white-space:pre-wrap}.why-label{color:var(--muted);font-weight:700}
@media(max-width:1000px){.inv{grid-template-columns:1fr;height:auto}.listwrap,.treewrap{max-height:70vh}.panel{overflow:visible}.panel{border-left:0;border-top:1px solid var(--line);padding-left:0}.split{grid-template-columns:1fr}.say{max-width:100%}.drawer{width:100vw}.score{flex-direction:column;align-items:flex-start}.score .facts{min-width:0;width:100%}.rd{grid-template-columns:1fr 1fr}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
"""
