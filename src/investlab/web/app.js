'use strict';
const $=id=>document.getElementById(id), pct=v=>v==null?'—':`${(v*100).toFixed(1)}%`;
const names={B_QQQ100:'纯QQQ',B_FIXED60_40:'固定60/40',VOL_TARGET_QQQ:'波动目标',TSMOM12_QQQ:'12个月动量',RP_VOL_TARGET_QQQ_TQQQ:'风险平价＋波动目标',RP_QQQ_TQQQ:'风险平价',MR_Z_OU_QQQ:'统计均值回归',TSMOM12_MULTI:'双ETF动量',B_QQQ90:'90% QQQ',B_QQQ25:'25% QQQ'};
const reasons={TREND_ENTRY_STEP:'长期趋势向上，波动低于增加门槛；从最后确认持仓分步调整。',TREND_EXIT:'长期趋势关闭，复核降低TQQQ仓位。',VOLATILITY_EXIT:'波动达到退出门槛，复核降低杠杆。',VOLATILITY_PAUSE_ADDITIONS:'波动升高，暂停增加TQQQ。',WITHIN_TACTICAL_BAND:'仓位在偏差范围内。',TRIM_ABOVE_REFERENCE:'仓位超出目标，复核超出部分。'};
let last;
function text(id,value){$(id).textContent=value;}
function element(tag,value,cls){const e=document.createElement(tag);if(value!==undefined)e.textContent=value;if(cls)e.className=cls;return e;}
function row(parent,left,right,warn=false){const e=element('div',undefined,'check');e.append(element('span',left),element('span',right,warn?'warn':''));parent.append(e);}
function table(id,rows){const p=$(id);p.replaceChildren();for(const cells of rows){const tr=element('tr');for(const cell of cells)tr.append(element('td',String(cell??'—')));p.append(tr);}if(!rows.length){const tr=element('tr');const td=element('td','尚无记录');td.colSpan=8;tr.append(td);p.append(tr);}}
async function get(path){const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw new Error('读取记录失败：'+r.status);return r.json();}
function render(v){last=v;if(!v){text('headline','尚未生成报告');text('updated','在终端运行 investlab run，再刷新本页。');return;}
const r=v.review,t=r.next_review_weights,current=r.current_baseline_weights;
const attemptOK=v.latest_attempt?.status==='SUCCEEDED';
const ageHours=(Date.now()-Date.parse(v.created_at))/3600000;
const demoAgeLabel=v.demo
  ? (Number.isFinite(ageHours)&&ageHours>36 ? '演示快照已超过36小时，不会自动更新' : '部署时生成的固定演示快照')
  : (v.stale_for_today?'报告生成已超过36小时':'报告时间已记录');
$('refresh').textContent=v.demo?'重新读取快照 ↻':'刷新记录 ↻';
text('mode',v.demo?'虚构数据演示':v.qualified_online?'在线计算':'缓存复算');text('updated',`行情日 ${v.session_date} · 计算于 ${new Date(v.created_at).toLocaleString('zh-CN')} · ${v.version}`);
const action=!attemptOK?'最近一轮失败或未完成，保留历史报告':v.demo?'演示：查看规则怎样改变仓位':!v.market_session_current?'行情落后于最新完整交易日':r.status==='ALLOCATION_REVIEW'?r.headline:r.status==='CACHE_REPLAY_ONLY'?'缓存复算，查看已满足的条件':'数据校验阻断了新判断';text('headline',action);text('reason',reasons[r.tactical_reason]||(r.blockers||[]).join('；')||'研究输出与真实交易分开保存。');
$('flags').replaceChildren();for(const [label,warn] of [[v.demo?'全部行情均为虚构':'人工执行',false],[attemptOK?'最近一轮已保存并完成本地备份':'最近一轮失败或未完成',!attemptOK],[demoAgeLabel,v.demo?Number.isFinite(ageHours)&&ageHours>36:v.stale_for_today]])$('flags').append(element('span',label,'flag'+(warn?' warn':'')));
text('account',new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY',maximumFractionDigits:0}).format(v.portfolio.total_cny));text('account-date',`确认日期 ${v.portfolio.as_of}`);text('volatility',pct(v.risk.annual_volatility));text('continuity',v.demo?'演示不计数':`${v.distinct_verified_sessions} 个交易日`);text('operation',attemptOK?'计算、数据库回读与本地备份成功':'最近一轮未完成，请查看运行记录');
$('allocations').replaceChildren();for(const s of ['QQQ','TQQQ','CASH']){const e=element('div',undefined,'allocation');e.append(element('strong',s==='CASH'?'现金':s));const bar=element('div',undefined,'bar'),inner=element('div');inner.style.width=`${(current?.[s]||0)*100}%`;bar.append(inner);e.append(bar,element('span',`${pct(current?.[s])} → ${pct(t?.[s])} → ${pct({QQQ:.6,TQQQ:.4,CASH:0}[s])}`));$('allocations').append(e);}
text('account-warning',`账户截至 ${v.portfolio.as_of}。未确认新的估值或成交前，重复日报不会自动推进下一步；股数与成本未知时不推算实际盈亏。`);
$('conditions').replaceChildren();for(const c of r.entry_conditions||[])row($('conditions'),c.rule,c.met?'满足':'未满足',!c.met);if(!r.entry_conditions?.length)row($('conditions'),'输入状态',r.status,true);
$('checks').replaceChildren();row($('checks'),'行情模式',v.demo?'虚构演示':v.mode);row($('checks'),'数据库报告回读',v.checks.database_report_readback?'一致':'待核对');const independent=Object.values(v.checks.independent_quotes).every(x=>x==='MATCH');row($('checks'),'备用收盘价核对',independent?'同日相符':'尚未全部核对',!independent);row($('checks'),'策略未来效果','持续积累证据',true);row($('checks'),'完整本地备份',attemptOK?'已核验':'本轮未完成',!attemptOK);text('identity',`记录 ${v.review_id.slice(0,12)}`);
text('summary',[v.demo?'演示报告：虚构行情与账户。':action,'目标：QQQ 60%＋TQQQ 40%。',t?`本步：QQQ ${pct(t.QQQ)}／TQQQ ${pct(t.TQQQ)}／现金 ${pct(t.CASH)}。`:'暂不生成新步骤。',`行情截至 ${v.session_date}；账户截至 ${v.portfolio.as_of}。`,'建议不会记成成交；策略效果继续检验。'].join('\n'));
}
const palette=['#90b4ff','#74dec4','#ffcb8b','#c4a3ff','#ff8eae'];
function chart(curves){const svg=$('curve'),legend=$('chart-labels');svg.replaceChildren();legend.replaceChildren();const all=Object.values(curves);if(!all.length)return;const ns='http://www.w3.org/2000/svg',width=920,height=235,left=60,top=20;let max=Math.max(...all.flatMap(x=>x.equity)),min=0;
function node(tag,attrs,label){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(label)e.textContent=label;svg.append(e);return e;}
for(let i=0;i<5;i++){const value=max*i/4,y=top+height-height*i/4;node('line',{x1:left,y1:y,x2:left+width,y2:y,stroke:'#273548'});node('text',{x:0,y:y+4},value.toFixed(1));}
Object.entries(curves).forEach(([name,series],j)=>{const points=series.equity.map((v,i)=>`${left+width*i/Math.max(1,series.equity.length-1)},${top+height-(v-min)/(max-min||1)*height}`).join(' ');node('polyline',{points,fill:'none',stroke:palette[j%palette.length],'stroke-width':2});const label=element('span'),dot=element('i');dot.style.background=palette[j%palette.length];label.append(dot,document.createTextNode(names[name]||name));legend.append(label);});const dates=all[0].dates;node('text',{x:left,y:290},dates[0]);node('text',{x:left+width-85,y:290},dates.at(-1));}
async function loadDailyHealth(){
  const panel=$('daily-health');
  if(!panel)return;
  try{
    const r=await fetch('/api/daily-status',{cache:'no-store'});
    if(!r.ok){panel.hidden=true;return;}
    const v=await r.json();
    if(v.status==='NOT_RUN'){panel.hidden=true;return;}
    panel.hidden=false;
    const names={SUCCEEDED:'已完成',FAILED:'执行失败',DEGRADED:'部分环节失败',RUNNING:'运行中'};
    text('daily-health-state',names[v.status]||v.status);
    const box=$('daily-health-details');box.replaceChildren();
    row(box,'阶段',v.stage||'—',v.status!=='SUCCEEDED');
    row(box,'最后更新',v.completed_at?new Date(v.completed_at).toLocaleString('zh-CN'):'尚未结束');
    row(box,'在线数据验证',v.qualified_online?'通过':'未通过',!v.qualified_online);
    if(v.issue_code)row(box,'问题代码',v.issue_code,true);
  }catch{panel.hidden=true;}
}
async function load(){loadDailyHealth();try{$('error').hidden=true;const [v,research,history,journal]=await Promise.all(['/api/latest','/api/research','/api/history','/api/journal'].map(get));render(v);table('models',(research.comparisons||[]).map(r=>[names[r.model_id]||r.model_id,r.cost_bps+' bp',r.summary.cagr_pct.toFixed(2)+'%',r.summary.max_drawdown_pct.toFixed(2)+'%',r.summary.annual_vol_pct.toFixed(2)+'%',r.max_relative_equity_error.toExponential(1)]));chart(research.curves||{});text('research-status',research.status==='PASS'?`独立复算通过：${research.comparisons.length}组比较，行情截至${research.data_end}。历史已用于开发，分段结果不冒充未见样本。`:'尚未完成独立复核。运行 investlab verify 后刷新。');table('operations',history.map(r=>[new Date(r.started_at).toLocaleString('zh-CN'),r.command,r.status,r.completed_at?new Date(r.completed_at).toLocaleString('zh-CN'):'未完成']));table('journal',journal.map(r=>[r.occurred_at,r.account,r.kind,r.symbol||'—',r.quantity||r.amount]));}catch(e){text('error',e.message);$('error').hidden=false;}}
function renderScenario(){
  const shock=Number($('scenario-index').value),tqqq=Number($('scenario-tqqq').value)/100;
  const qqq=1-tqqq, exposure=qqq+3*tqqq, impact=exposure*shock;
  text('scenario-index-label',shock>0?'+'+shock+'%':shock+'%');
  text('scenario-tqqq-label',Math.round(tqqq*100)+'%');
  text('scenario-weights',Math.round(qqq*100)+'% / '+Math.round(tqqq*100)+'%');
  text('scenario-exposure',exposure.toFixed(2)+'倍');
  text('scenario-impact',(impact>0?'+':'')+impact.toFixed(1)+'%');
}
for(const id of ['scenario-index','scenario-tqqq'])$(id).addEventListener('input',renderScenario);
renderScenario();
for(const b of document.querySelectorAll('.tab'))b.addEventListener('click',()=>{for(const p of document.querySelectorAll('.panel'))p.hidden=p.id!==b.dataset.tab;for(const t of document.querySelectorAll('.tab'))t.classList.toggle('active',t===b);});$('refresh').addEventListener('click',load);$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('summary').textContent);text('copy','已复制');}catch{text('copy','请选中文本复制');}});let localToken=null;
async function initLocalEditor(){
  try{
    const response=await fetch('/api/local-session',{cache:'no-store'});
    if(!response.ok)return;
    const state=await response.json();
    if(!state.local_edit || typeof state.csrf_token!=='string')return;
    localToken=state.csrf_token;
    $('local-editor').hidden=false;
    $('local-as-of').value=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
  }catch{ /* Public static demo has no private editing API. */ }
}
function localBusy(busy){
  for(const id of ['local-save','local-run-cached','local-run-online'])$(id).disabled=busy;
}
async function localPost(path,body){
  if(!localToken)throw new Error('仅允许在已开启私有编辑的本地页面操作');
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-InvestLab-CSRF':localToken},body:JSON.stringify(body)});
  const v=await r.json();
  if(!r.ok)throw new Error(v.error||'操作失败 '+r.status);
  return v;
}
$('valuation-form').addEventListener('submit',async e=>{
  e.preventDefault();
  if(!e.currentTarget.reportValidity())return;
  const values={QQQ:$('local-qqq').value,TQQQ:$('local-tqqq').value,QLD:$('local-qld').value,CASH:$('local-cash').value};
  const total=Object.values(values).reduce((a,b)=>a+Number(b),0);
  if(!Number.isFinite(total)||total<=0){text('local-status','请填写大于0的总资产估值');return;}
  const payload={valuation_id:crypto.randomUUID(),account:'default',as_of:$('local-as-of').value,
    currency:'CNY',values,confirmed:$('local-confirm').checked,note:$('local-note').value.trim()};
  localBusy(true);text('local-status','正在保存已确认估值…');
  try{await localPost('/api/valuation',payload);text('local-status','估值已保存；尚未重新计算。请点击下方计算按钮。');$('local-confirm').checked=false;}
  catch(err){text('local-status','保存失败：'+err.message);}
  finally{localBusy(false);}
});
for(const [id,online] of [['local-run-cached',false],['local-run-online',true]]){
  $(id).addEventListener('click',async()=>{
    localBusy(true);text('local-status',online?'正在获取并核验行情，然后保存计算结果…':'正在使用已保存的行情计算…');
    try{
      const result=await localPost('/api/recalculate',{online});
      await load();
      text('local-status',result.qualified_online?'在线计算完成，结果已更新。':'计算完成；请核对数据是否及时，未把缓存结果认定为在线行情。');
    }catch(err){text('local-status','计算失败：'+err.message);}
    finally{localBusy(false);}
  });
}
initLocalEditor();
load();
