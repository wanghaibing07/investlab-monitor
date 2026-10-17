"use strict";
(function(){
  const $ = function(id){ return document.getElementById(id); };
  const $$ = function(selector){ return Array.from(document.querySelectorAll(selector)); };
  const meta = [
    {symbol:"QQQ",name:"纳斯达克100 ETF",kind:"股票 ETF",color:"#93adff",css:"qqq",target:60},
    {symbol:"TQQQ",name:"纳指每日3倍杠杆 ETF",kind:"杠杆 ETF",color:"#72d5c4",css:"tqqq",target:40},
    {symbol:"QLD",name:"纳指每日2倍杠杆 ETF",kind:"杠杆 ETF",color:"#b39afd",css:"qld",target:0},
    {symbol:"CASH",name:"人民币现金",kind:"现金",color:"#f0bd7d",css:"cash",target:0}
  ];
  const state = {account:null,history:[],historyReady:false,status:null,report:null,brief:null,briefError:null,period:"all",busy:false,mutating:false,initial:true};
  const nformat = new Intl.NumberFormat("zh-CN",{maximumFractionDigits:0});
  const dateformat = new Intl.DateTimeFormat("zh-CN",{year:"numeric",month:"long",day:"numeric",timeZone:"Asia/Shanghai"});
  const pages = {overview:"资产总览",portfolio:"投资组合",research:"策略与风险",runs:"运行报告",settings:"账户与设置"};
  function icon(name){return '<svg class="icon" aria-hidden="true"><use href="#i-'+name+'"/></svg>';}
  function number(v){const n=Number(v);return Number.isSafeInteger(n)&&n>=0?n:0;}
  function amount(v){return "¥"+nformat.format(number(v));}
  function percent(v){return (Math.round(v*10)/10).toLocaleString("zh-CN",{maximumFractionDigits:1})+"%";}
  function dateText(v){if(!v||typeof v!=="string")return "—";const d=new Date(v.slice(0,10)+"T12:00:00+08:00");return Number.isNaN(d.getTime())?v:dateformat.format(d);}
  function timeText(v){if(!v)return "—";const d=new Date(v);return Number.isNaN(d.getTime())?"—":new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",dateStyle:"medium",timeStyle:"short",hour12:false}).format(d);}
  function setText(id,val){const n=$(id);if(n)n.textContent=val==null?"—":String(val);}
  function element(tag,cl,text){const n=document.createElement(tag);if(cl)n.className=cl;if(text!==undefined)n.textContent=text;return n;}
  function clear(node){node.replaceChildren();}
  function makeIcon(name){const wrapper=element("span");wrapper.innerHTML=icon(name);return wrapper.firstElementChild;}
  function moneyValues(account){return account&&account.account_initialized===true&&account.values?account.values:null;}
  function total(account){const v=moneyValues(account);return v?meta.reduce((s,m)=>s+number(v[m.symbol]),0):0;}
  function weights(account){const v=moneyValues(account);const t=total(account);return Object.fromEntries(meta.map(m=>[m.symbol,t?100*number(v[m.symbol])/t:0]));}
  function showToast(message,error){const el=$("toast");el.textContent=String(message);el.classList.toggle("error",!!error);el.hidden=false;window.clearTimeout(showToast.timeoutId);showToast.timeoutId=window.setTimeout(()=>{el.hidden=true;},6600);}
  function busyButton(button,isBusy,label){if(!button)return;button.disabled=isBusy;button.classList.toggle("is-spinning",!!isBusy);if(label){const target=button.querySelector("span");if(target)target.textContent=label;else button.textContent=label;}}
  async function api(path,options){
    const opts=Object.assign({credentials:"same-origin",cache:"no-store"},options||{});
    let response;
    try{response=await fetch(path,opts);}catch(e){throw new Error("网络请求失败，请检查登录或连接。");}
    let payload;
    try{payload=await response.json();}catch(e){throw new Error("服务器未返回有效数据，请检查会话是否过期。");}
    if(!response.ok){
      const reason=payload.detail||payload.issue_code||payload.status||("HTTP "+response.status);
      const error=new Error(typeof reason==="string"?reason:"HTTP "+response.status);
      error.status=response.status;error.payload=payload;throw error;
    }
    return payload;
  }
  async function apiOptional(path){
    try{return await api(path);}catch(e){
      if(e.status===404&&["NEEDS_FIRST_ONLINE_RUN","SETUP_REQUIRED"].includes(e.message))return null;
      throw e;
    }
  }
  function loading(on){state.busy=on;$("app-loading").hidden=!on;const button=$("refresh-button");button.classList.toggle("is-spinning",on);button.disabled=on;}
  async function loadAll(){
    if(state.busy)return;
    loading(true);
    $("global-error").hidden=true;
    const result=await Promise.allSettled([
      api("/api/account"),api("/api/status"),api("/api/history"),apiOptional("/api/latest"),api("/api/brief")
    ]);
    if(result[0].status==="fulfilled")state.account=result[0].value;
    else{state.account=null;$("global-error").hidden=false;setText("global-error-detail","账户读取失败："+result[0].reason.message+"。请确认 Vercel 登录仍有效。");}
    state.status=result[1].status==="fulfilled"?result[1].value:{status:"STORAGE_ERROR",storage_verified:false};
    state.historyReady=result[2].status==="fulfilled";
    state.history=state.historyReady&&Array.isArray(result[2].value.history)?result[2].value.history:[];
    state.report=result[3].status==="fulfilled"?result[3].value:null;
    state.brief=result[4].status==="fulfilled"?result[4].value:null;
    state.briefError=result[4].status==="rejected"?result[4].reason.message:null;
    if(result[2].status==="rejected"&&state.account)showToast("历史记录暂时读取失败，其他账户信息可以正常查看。",true);
    if(result[1].status==="rejected"&&state.account)showToast("最新监控状态读取失败，请稍后重试。",true);
    render();
    loading(false);
    if(state.initial){
      state.initial=false;
      if(window.location.pathname==="/setup"){window.location.hash="settings";openEditor();}
    }
  }
  function render(){
    renderDecision();renderOverview();renderPortfolio();renderResearch();renderRuns();renderSettings();
    for(const b of $$("[data-open-editor]"))b.disabled=!state.account;
    for(const b of $$("[data-open-run]"))b.disabled=!(state.account&&state.account.account_initialized&&state.status&&state.status.storage_verified);
  }
  function renderDecision(){
    const b=state.brief||null;
    let headline,explanation,next,status="等待证据",verified=false,actionable=false,when="最近报告：尚未运行";
    if(!b){
      headline=state.briefError?"当前无法生成可靠结论":"正在等待可信的研究报告";
      explanation=state.briefError?"结论接口读取失败："+state.briefError+"。技术检查结果不能替代策略复核。":"先保存真实账户并通过在线行情核验，才会提供可解释的人工复核意见。";
      next=state.briefError?"检查登录和监控报告，再尝试刷新。":"进入运行报告，完成首次在线监控。";
    }else{
      headline=b.headline||"暂无可用结论";
      explanation=b.explanation||"当前还没有足够的信息推导新建议。";
      next=b.next_step||"检查报告状态。";
      verified=b.verified_run===true;
      actionable=b.actionable===true&&b.status==="ACTION_REVIEW";
      status=actionable?(b.priority==="HOLD"?"维持观察":"可供人工复核"):(verified?"已核验·暂缓建议":"等待验证");
      when=b.report_created_at?"报告生成："+timeText(b.report_created_at):"尚无合格研究报告";
    }
    setText("decision-headline",headline);setText("decision-description",explanation);
    setText("decision-next-step",next);setText("decision-report-time",when);
    const badge=$("decision-badge");
    badge.textContent=status;badge.className="decision-status"+(actionable?"":verified?" is-wait":" is-blocked");
    setText("decision-proof-status",actionable?"可以复核配置":verified?"检查通过，但不可执行":"尚未达到行动条件");
    setText("decision-proof-sub",actionable?"数据质量与配置条件均已核对，仍需本人决定":"技术 PASS 仅证实数据与审计，当前策略意见需另行判断");
    $("decision-proof-status").parentElement.dataset.verified=String(actionable);
    setText("decision-session",b&&b.report_session?dateText(b.report_session):"待核验");
    setText("decision-account-date",state.account&&state.account.account_initialized?dateText(state.account.as_of):"未保存");
    const actualPortfolio=state.account&&state.account.account_initialized===true;
    setText("decision-proof-total",actualPortfolio?amount(total(state.account)):"—");
    setText("decision-proof-total-date",actualPortfolio?"已确认估值日 "+dateText(state.account.as_of):"尚未读取真实资产");
    setText("decision-evidence",verified?"在线核验通过":"待通过");
    setText("decision-applicable",actionable?"与当前账户一致":b&&b.status==="ACCOUNT_MISMATCH"?"需更新结论":"不生成交易建议");
    const tickets=$("decision-action-tickets");clear(tickets);
    if(actionable&&Array.isArray(b.steps)){
      for(const step of b.steps){
        if(!["QQQ","TQQQ"].includes(step.symbol))continue;
        const item=element("div","action-ticket"),body=element("div"),change=element("span","ticket-arrow");
        body.appendChild(element("strong","",step.symbol+" · "+step.label));
        const curr=typeof step.current_weight==="number"?percent(step.current_weight*100):"—";
        const target=typeof step.reference_weight==="number"?percent(step.reference_weight*100):"—";
        body.appendChild(element("small","",curr+" → 本步 "+target));
        change.textContent=step.action==="HOLD"?"＝":step.action==="REDUCE_REVIEW"?"↘":"↗";
        item.appendChild(body);item.appendChild(change);tickets.appendChild(item);
      }
    }
    if(!tickets.childElementCount){
      const placeholder=element("div","action-ticket ticket-wait");
      const details=element("div");
      details.appendChild(element("strong","",verified?"没有获得当前可用的配置意见":"待行情与账户核验"));
      details.appendChild(element("small","",verified?"本轮暂不输出配置比例":"先验证再判断，不猜测行情。"));
      placeholder.appendChild(details);tickets.appendChild(placeholder);
    }
    renderDecisionAllocation(b,actionable);
    renderHistoricalSignal(b,actionable);
    renderDecisionEvidence();
  }
  function renderDecisionAllocation(brief,actionable){
    const panel=$("decision-allocation"),container=$("decision-allocation-rows");
    clear(container);
    const steps=brief&&brief.steps;
    const totalCny=brief&&brief.portfolio_total_cny;
    const valid=actionable&&Array.isArray(steps)&&
      Number.isSafeInteger(totalCny)&&totalCny>0&&
      steps.length>=2&&steps.every(step=>["QQQ","TQQQ"].includes(step.symbol)&&
        Number.isSafeInteger(step.current_value_cny)&&
        Number.isSafeInteger(step.step_reference_value_cny)&&
        Number.isSafeInteger(step.estimated_difference_cny)&&
        typeof step.current_weight==="number"&&
        typeof step.reference_weight==="number");
    panel.hidden=!valid;
    if(!valid)return;
    for(const step of steps){
      const row=element("div","decision-allocation-row");
      const heading=element("div","decision-allocation-info");
      const title=element("strong","",step.symbol);
      const action=element("span","action-verdict",step.label);
      heading.appendChild(title);heading.appendChild(action);
      row.appendChild(heading);
      const bar=element("div","decision-allocation-track");
      const base=element("span","decision-allocation-current");
      const ref=element("span","decision-allocation-next");
      base.style.width=Math.min(100,Math.max(0,100*step.current_weight)).toFixed(2)+"%";
      ref.style.width=Math.min(100,Math.max(0,100*step.reference_weight)).toFixed(2)+"%";
      bar.appendChild(base);bar.appendChild(ref);row.appendChild(bar);
      const metrics=element("div","decision-allocation-metrics");
      metrics.appendChild(element("span","",percent(step.current_weight*100)+" → "+percent(step.reference_weight*100)));
      const difference=step.estimated_difference_cny;
      const delta=element("strong","decision-amount"+(difference>0?" is-add":difference<0?" is-reduce":""),
        difference>0?"参考多配约 "+amount(difference):difference<0?"参考少配约 "+amount(Math.abs(difference)):"参考金额基本不变");
      metrics.appendChild(delta);row.appendChild(metrics);container.appendChild(row);
    }
    const footer=element("div","decision-allocation-cash");
    const currentCash=brief.cash_current_cny, nextCash=brief.cash_step_reference_cny;
    if(Number.isSafeInteger(currentCash)&&Number.isSafeInteger(nextCash)){
      footer.appendChild(element("span","", "现金参考："+amount(currentCash)+" → "+amount(nextCash)));
      footer.appendChild(element("strong","", "仅用于检视配置，不是可执行买卖金额"));
      container.appendChild(footer);
    }
  }
  function renderHistoricalSignal(brief,actionable){
    const section=$("historical-signal");
    const signal=brief&&brief.historical_signal;
    const visible=!actionable&&signal&&signal.not_current_advice===true&&
      typeof signal.headline==="string"&&typeof signal.explanation==="string";
    section.hidden=!visible;
    if(!visible)return;
    setText("historical-signal-title",signal.headline);
    setText("historical-signal-date",signal.session?dateText(signal.session):"记录日期待核验");
    setText("historical-signal-description",signal.explanation);
  }
  function renderDecisionEvidence(){
    const b=state.brief,valid=b&&b.actionable===true&&b.status==="ACTION_REVIEW";
    setText("model-gate-label",valid?"有条件可复核":b&&b.verified_run?"技术已通过，意见暂缓":"等待可信证据");
    $("model-gate-label").className="logic-label"+(valid?"":" blocked");
    setText("model-reason-title",b?b.headline:"尚未得到完整研究结论");
    setText("model-reason-explanation",b?b.explanation:"先保存持仓并完成行情核验。");
    setText("model-next",b?b.next_step:"进入运行报告启动一次可信的在线监控。");
    const list=$("model-conditions");clear(list);
    if(valid&&Array.isArray(b.conditions)&&b.conditions.length){
      for(const cond of b.conditions){
        const card=element("div","condition-item"+(cond.met?"":" unmet"));
        card.appendChild(makeIcon(cond.met?"check":"clock"));
        const description=element("span","",cond.label+" · "+(cond.met?"满足":"未满足"));
        card.appendChild(description);list.appendChild(card);
      }
    }else{
      const card=element("div","condition-item unmet");
      card.appendChild(makeIcon("info"));
      card.appendChild(element("span","","未具备当次可用的市场与账户证据，不推导本步目标比例。"));
      list.appendChild(card);
    }
    setText("run-action-headline",b?b.headline:"等待研究报告");
    setText("run-action-explanation",b?b.explanation+" 下一步："+b.next_step:"运行检查通过后，还需核对当前账户、行情日期及策略门槛。");
  }
  function readiness(){
    const a=state.account,s=state.status;
    if(!a)return {kind:"danger",heading:"账户读取失败",copy:"无法从私有存储读取账户，请重新登录并刷新。"};
    if(!a.account_initialized)return {kind:"info",heading:"还没有保存真实账户",copy:"先在「账户与设置」中确认人民币估值，才能开始行情核验。"};
    if(!s||s.storage_verified!==true)return {kind:"danger",heading:"存储或监控状态未通过检查",copy:"账户存在，但尚未确认本次存储读写检查是否成功。"};
    if(s.status==="SUCCEEDED"&&s.qualified_online===true)return {kind:state.brief&&state.brief.actionable?"ready":"info",heading:state.brief&&state.brief.actionable?"行情与策略结论已核对":"技术核验通过，策略仍需复核",copy:state.brief&&state.brief.headline?state.brief.headline:"技术 PASS 不代表立即调仓，先查看报告时点和账户一致性。"};
    if(s.status==="FAILED"||s.status==="STORAGE_ERROR"||s.status==="STATE_INCONSISTENT")return {kind:"danger",heading:"最近一次监控尚未通过",copy:"请到运行报告查看失败状态。本页面不会把未经验证的数据标记为成功。"};
    return {kind:"info",heading:"账户已就绪，等待首次行情核验",copy:"持仓已保存并可读取；运行一次真实监控后才会出现可信的分析报告。"};
  }
  function renderOverview(){
    const a=state.account,valid=!!moneyValues(a),vals=valid?a.values:null;
    const sum=total(a),invested=valid?sum-number(vals.CASH):0;
    setText("metric-total",valid?amount(sum):"—");
    setText("metric-invested",valid?amount(invested):"—");
    setText("metric-cash",valid?amount(vals.CASH):"—");
    setText("metric-total-sub",valid?"估值日 "+dateText(a.as_of):"尚未初始化");
    setText("metric-invested-sub",valid?percent(invested/sum*100)+" · 股票及杠杆 ETF":"等待账户数据");
    setText("metric-cash-sub",valid?percent(number(vals.CASH)/sum*100)+" · 资金缓冲":"等待账户数据");
    const latest=state.status;
    let quality="等待行情验证",qualitySub="尚无合格的在线行情报告";
    if(latest&&latest.status==="SUCCEEDED"&&latest.qualified_online===true){quality="核验通过";qualitySub="最近一轮在线行情已通过独立检查";}
    else if(latest&&["FAILED","STORAGE_ERROR","STATE_INCONSISTENT"].includes(latest.status)){quality="需要检查";qualitySub="最近运行或存储校验未通过";}
    setText("metric-quality",quality);setText("metric-quality-sub",qualitySub);
    const ready=readiness(),banner=$("readiness-banner");
    banner.className="notice notice-"+ready.kind;
    setText("readiness-title",ready.heading);setText("readiness-subtitle",ready.copy);
    setText("allocation-date",valid?"截至 "+dateText(a.as_of):"暂无估值");
    renderDonut();
    renderOverviewHoldings();
    renderChart();
    renderMonitor();
  }
  function renderDonut(){
    const a=state.account,values=moneyValues(a),sum=total(a);
    const pie=$("allocation-donut"),legend=$("allocation-legend");clear(legend);
    if(!values||sum<=0){pie.style.background="#263447";setText("equity-percentage","—");
      const message=element("div","empty-chart");message.textContent="保存账户后显示实际资产分布";legend.appendChild(message);return;}
    const w=weights(a);let begin=0;const segments=[];
    for(const m of meta){const end=begin+w[m.symbol];segments.push(m.color+" "+begin.toFixed(4)+"% "+end.toFixed(4)+"%");begin=end;}
    pie.style.background="conic-gradient("+segments.join(", ")+")";
    setText("equity-percentage",percent(100-w.CASH));
    pie.setAttribute("aria-label","QQQ "+percent(w.QQQ)+"，TQQQ "+percent(w.TQQQ)+"，QLD "+percent(w.QLD)+"，现金 "+percent(w.CASH));
    for(const m of meta){
      const row=element("div","legend-row"),name=element("span","legend-name"),dot=element("span","legend-color");
      dot.style.background=m.color;name.appendChild(dot);name.appendChild(document.createTextNode(m.symbol==="CASH"?"现金":m.symbol));
      row.appendChild(name);row.appendChild(element("strong","",percent(w[m.symbol])));legend.appendChild(row);
    }
  }
  function renderOverviewHoldings(){
    const box=$("overview-holdings");clear(box);
    const a=state.account,vals=moneyValues(a),sum=total(a);
    if(!vals){box.appendChild(emptyMessage("尚无已确认持仓","请先在账户设置中保存一次真实估值。"));return;}
    for(const m of meta){
      const row=element("div","holding-item"),left=element("div","holding-left"),mark=element("span","ticker-icon "+m.css,m.symbol==="CASH"?"¥":m.symbol.slice(0,1)),copy=element("span","ticker-data");
      copy.appendChild(element("strong","",m.symbol==="CASH"?"现金":m.symbol));copy.appendChild(element("span","",m.name));
      left.appendChild(mark);left.appendChild(copy);
      const progress=element("div","holding-progress"),inner=element("span");
      inner.style.width=(sum?100*number(vals[m.symbol])/sum:0).toFixed(3)+"%";inner.style.background=m.color;progress.appendChild(inner);
      const value=element("div","holding-value");
      value.appendChild(element("strong","",amount(vals[m.symbol])));value.appendChild(element("span","",percent(sum?number(vals[m.symbol])/sum*100:0)));
      row.appendChild(left);row.appendChild(progress);row.appendChild(value);box.appendChild(row);
    }
  }
  function emptyMessage(title,subtitle){
    const item=element("div","empty-chart"),glyph=element("div","empty-chart-icon");
    glyph.appendChild(makeIcon("chart"));item.appendChild(glyph);item.appendChild(element("strong","",title));item.appendChild(element("span","",subtitle));return item;
  }
  function entriesByDate(){
    if(!state.historyReady)return [];
    const dayMap=new Map();
    for(const item of state.history){
      if(!item||typeof item.as_of!=="string"||!item.values)continue;
      const sums=meta.reduce((v,m)=>v+number(item.values[m.symbol]),0);
      if(sums>0&&!dayMap.has(item.as_of))dayMap.set(item.as_of,{date:item.as_of,total:sums});
    }
    const rows=Array.from(dayMap.values()).sort((x,y)=>x.date.localeCompare(y.date));
    if(state.period==="all")return rows;
    const days=Number(state.period),today=new Date(),cutoff=new Date(today.getTime()-(days-1)*86400000).toISOString().slice(0,10);
    return rows.filter(x=>x.date>=cutoff);
  }
  function renderChart(){
    const box=$("history-chart");clear(box);
    const rows=entriesByDate();
    setText("history-count",state.historyReady?rows.length+" 个不同日期的真实估值":"历史记录未完成读取");
    if(!state.historyReady){box.appendChild(emptyMessage("历史记录暂时不可用","请刷新后检查私有存储连接。"));return;}
    if(rows.length<2){box.appendChild(emptyMessage("需要更多真实记录","至少保存两个不同日期的估值后，才绘制资产轨迹。"));return;}
    const values=rows.map(x=>x.total),min=Math.min(...values),max=Math.max(...values),pad=Math.max((max-min)*.16,max*.035,1),yMin=Math.max(0,min-pad),yMax=max+pad;
    const svgNS="http://www.w3.org/2000/svg",width=720,height=260,l=73,r=14,t=19,b=35,pw=width-l-r,ph=height-t-b;
    const X=i=>l+pw*i/(rows.length-1),Y=v=>t+(yMax-v)*ph/(yMax-yMin);
    const svg=document.createElementNS(svgNS,"svg");svg.setAttribute("viewBox","0 0 "+width+" "+height);svg.setAttribute("role","img");svg.setAttribute("aria-label",rows.length+" 个确认日期的账户总额走势，非投资回报率");
    const def=document.createElementNS(svgNS,"defs");def.innerHTML='<linearGradient id="line-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8da9ff" stop-opacity=".2"/><stop offset="1" stop-color="#8da9ff" stop-opacity="0"/></linearGradient>';svg.appendChild(def);
    for(let i=0;i<=3;i++){
      const y=t+ph*i/3,grid=document.createElementNS(svgNS,"line");grid.setAttribute("x1",l);grid.setAttribute("x2",width-r);grid.setAttribute("y1",y);grid.setAttribute("y2",y);grid.setAttribute("class","chart-grid");svg.appendChild(grid);
      const label=document.createElementNS(svgNS,"text");label.setAttribute("x",l-12);label.setAttribute("y",y+4);label.setAttribute("text-anchor","end");label.setAttribute("class","chart-axis");label.textContent=amount(yMax-(yMax-yMin)*i/3);svg.appendChild(label);
    }
    const pairs=rows.map((p,i)=>[X(i),Y(p.total)]);
    const points=pairs.map(p=>p.map(n=>n.toFixed(2)).join(",")).join(" ");
    const area=document.createElementNS(svgNS,"polygon");area.setAttribute("points",l+","+(height-b)+" "+points+" "+(width-r)+","+(height-b));area.setAttribute("class","chart-area");svg.appendChild(area);
    const line=document.createElementNS(svgNS,"polyline");line.setAttribute("points",points);line.setAttribute("class","chart-line");svg.appendChild(line);
    for(const i of [0,rows.length-1]){
      const circle=document.createElementNS(svgNS,"circle");circle.setAttribute("cx",X(i));circle.setAttribute("cy",Y(rows[i].total));circle.setAttribute("r",i===rows.length-1?5.5:3.6);circle.setAttribute("class","chart-dot");svg.appendChild(circle);
      const label=document.createElementNS(svgNS,"text");label.setAttribute("x",X(i));label.setAttribute("y",height-9);label.setAttribute("text-anchor",i===0?"start":"end");label.setAttribute("class","chart-axis");label.textContent=rows[i].date.slice(5);svg.appendChild(label);
    }
    box.appendChild(svg);
  }
  function reportQuality(){
    const s=state.status;
    return !!(s&&s.status==="SUCCEEDED"&&s.qualified_online===true&&s.audit==="PASS"&&s.research_verification==="PASS");
  }
  function renderMonitor(){
    const box=$("overview-report");clear(box);
    const s=state.status,pass=reportQuality();
    const top=element("div","monitor-state"),circle=element("div","monitor-circle");
    circle.appendChild(makeIcon(pass?"check":"clock"));
    const desc=element("div");
    desc.appendChild(element("strong","",pass?"最新行情核验成功":s&&s.status==="FAILED"?"最新运行未通过":"尚无已验证的监控报告"));
    desc.appendChild(element("small","",pass?"已检查独立报价与账本一致性":"系统不会把尚未验证的数据标记为成功"));
    top.appendChild(circle);top.appendChild(desc);box.appendChild(top);
    box.appendChild(element("p","monitor-explainer",pass?"你可以在「运行报告」查看本次行情截止日期、计算校验和风险指标。":s&&s.status==="FAILED"?"上次运行失败或数据质量不足。可以查看失败类型，再决定是否重新运行。":"资产记录已保存；还需要第一份合格的在线行情才能产生风险和策略结论。"));
    const rows=[
      ["账户估值已确认",!!(state.account&&state.account.account_initialized)],
      ["私有存储已核验",!!(s&&s.storage_verified===true)],
      ["行情与研究独立核验",pass]
    ];
    for(const [title,ok] of rows){const item=element("div","mini-check"+(ok?"":" wait"));item.appendChild(makeIcon(ok?"check":"clock"));item.appendChild(element("span","",title+(ok?" · 完成":" · 待完成")));box.appendChild(item);}
  }
  function renderPortfolio(){
    const a=state.account,v=moneyValues(a),sum=total(a);
    setText("portfolio-total",v?amount(sum):"—");setText("portfolio-asof",v?"估值日期 "+dateText(a.as_of):"尚未保存真实资产");
    const t=$("portfolio-rows");clear(t);
    if(!v){const row=element("tr");const cell=element("td","empty-table","请在「账户与设置」中初始化真实估值");cell.colSpan=4;row.appendChild(cell);t.appendChild(row);}
    else for(const m of meta){
      const row=element("tr"),tkr=element("td"),unit=element("div","table-ticker");
      unit.appendChild(element("span","ticker-icon "+m.css,m.symbol==="CASH"?"¥":m.symbol.slice(0,1)));
      const names=element("div");names.appendChild(element("strong","",m.symbol==="CASH"?"现金":m.symbol));names.appendChild(element("span","subline",m.name));unit.appendChild(names);tkr.appendChild(unit);row.appendChild(tkr);
      row.appendChild(element("td","",m.kind));row.appendChild(element("td","align-right",amount(v[m.symbol])));row.appendChild(element("td","align-right",percent(sum?number(v[m.symbol])/sum*100:0)));t.appendChild(row);
    }
    renderHistoryTable();
  }
  function renderHistoryTable(){
    const tbody=$("history-rows");clear(tbody);setText("history-total-count",state.historyReady?state.history.length+" 条记录":"无法读取");
    if(!state.historyReady||state.history.length===0){const tr=element("tr");const td=element("td","empty-table",state.historyReady?"暂无估值历史":"历史记录无法读取");td.colSpan=6;tr.appendChild(td);tbody.appendChild(tr);return;}
    for(const item of state.history){
      const tr=element("tr"),v=item.values||{};
      tr.appendChild(element("td","",dateText(item.as_of)));
      tr.appendChild(element("td","align-right",amount(item.total_value_cny)));
      tr.appendChild(element("td","align-right",amount(v.QQQ)));
      tr.appendChild(element("td","align-right",amount(v.TQQQ)));
      tr.appendChild(element("td","align-right",amount(v.CASH)));
      tr.appendChild(element("td","note-cell",item.note||"—"));
      tbody.appendChild(tr);
    }
  }
  function renderResearch(){
    const a=state.account,v=moneyValues(a),sum=total(a),w=weights(a),box=$("weights-comparison");clear(box);
    if(!v){box.appendChild(emptyMessage("先保存账户估值","才能对比当前与目标配置"));}else{
      for(const m of meta){
        if(m.symbol==="QLD"&&w.QLD===0)continue;
        const item=element("div","compare-item"),head=element("div","compare-header");
        head.appendChild(element("strong","",m.symbol==="CASH"?"现金":m.symbol));
        head.appendChild(element("span","",percent(w[m.symbol])+" 当前 / "+percent(m.target)+" 目标"));item.appendChild(head);
        const bars=element("div","compare-bars");
        for(const kind of ["current","target"]){
          const track=element("div","compare-track"),fill=element("div",kind);
          fill.style.width=(kind==="current"?w[m.symbol]:m.target).toFixed(3)+"%";track.appendChild(fill);bars.appendChild(track);
        }
        item.appendChild(bars);box.appendChild(item);
      }
      const key=element("div","compare-key");
      for(const [name,color] of [["上：当前占比","#92aaff"],["下：策略目标","#6cbeac"]]){const node=element("span");const dot=element("i","legend-color");dot.style.background=color;node.appendChild(dot);node.appendChild(document.createTextNode(name));key.appendChild(node);}box.appendChild(key);
    }
    const risk=$("risk-report");clear(risk);
    const trusted=state.brief&&state.brief.actionable===true&&state.brief.status==="ACTION_REVIEW"&&reportQuality();
    const metrics=trusted&&state.brief.metrics?state.brief.metrics:{};
    const actualExposure=v&&sum>0?
      100*(number(v.QQQ)+3*number(v.TQQQ)+2*number(v.QLD))/sum:null;
    const verifiedVol=typeof metrics.qqq_vol20_pct==="number"?
      percent(metrics.qqq_vol20_pct):"等待有效模型报告";
    const modelVol=typeof metrics.risk_annual_volatility==="number"?
      percent(metrics.risk_annual_volatility*100):"等待有效模型报告";
    const riskShare=typeof metrics.risk_tqqq_variance_share==="number"?
      percent(metrics.risk_tqqq_variance_share*100):"等待有效模型报告";
    const rows=[
      {label:"当前名义纳指敞口",value:actualExposure!==null?percent(actualExposure):"—",
       detail:"按已确认 QQQ×1 + QLD×2 + TQQQ×3 的当日倍数粗算，不是实际收益率"},
      {label:"60/40 目标参考敞口",value:"180%",detail:"这是战略目标的每日名义敞口，不代表你现在的持仓"},
      {label:"QQQ 20 日年化波动",value:verifiedVol,detail:"来自本轮有效策略复核；行情不合格时不展示旧数值"},
      {label:"目标组合估计年化波动",value:modelVol,detail:"基于历史行情的模型估计，不预测未来收益"},
      {label:"TQQQ 对目标组合的方差风险贡献",value:riskShare,detail:"参考模型风险贡献；不等于当前账户的真实风险占比"}
    ];
    for(const row of rows){const div=element("div","risk-metric");div.appendChild(element("span","",row.label));div.appendChild(element("strong","",row.value));div.appendChild(element("small","",row.detail));risk.appendChild(div);}
  }
  function statusText(s){
    const map={SETUP_REQUIRED:"等待账户初始化",READY_FOR_FIRST_RUN:"账户就绪，尚未运行",SUCCEEDED:"已通过在线验证",FAILED:"运行失败",STORAGE_ERROR:"存储读取异常",STATE_INCONSISTENT:"账户状态不一致",NEEDS_FIRST_ONLINE_RUN:"等待首次运行"};
    return map[s]||"待确认";
  }
  function renderRuns(){
    const s=state.status,account=state.account,report=state.report,passed=reportQuality(),label=s?statusText(s.status):"等待运行状态";
    setText("run-status-title",label);
    setText("run-status-copy",passed?"已通过独立行情核验、账本审计与研究验证。":s&&s.status==="FAILED"?"本次未完成合格报告，不会将失败结果当作投资信号。":account&&account.account_initialized?"账户已保存，现在可以手动执行首次在线监控。":"请先保存真实账户估值。");
    const pill=$("run-status-tag");pill.className="status-pill"+(passed?" good":s&&s.status==="FAILED"?" bad":"");pill.textContent=passed?"验证通过":s&&s.status==="FAILED"?"未通过":"等待中";
    const checks=$("run-checks");clear(checks);
    const items=[
      ["账户已确认",account&&account.account_initialized,"从私有账户快照核对估值"],
      ["私有存储已连接",s&&s.storage_verified===true,"持久化存储的读取校验"],
      ["双来源在线行情",passed,"必须通过独立行情核验"],
      ["账本和研究检查",passed&&s.audit==="PASS"&&s.research_verification==="PASS","一致性、独立验证与风险研究"]
    ];
    for(const [name,done,detail] of items){const row=element("div","check-row"+(done?"":" wait"));row.appendChild(makeIcon(done?"check":"clock"));const content=element("div");content.appendChild(element("strong","",name+(done?" · 已通过":" · 等待")));content.appendChild(element("small","",detail));row.appendChild(content);checks.appendChild(row);}
    const detail=$("run-detail");clear(detail);
    const fields=[
      ["当前状态",label],
      ["行情截至",passed&&report&&report.session_date?dateText(report.session_date):"等待验证"],
      ["最近运行完成",s&&s.completed_at?timeText(s.completed_at):"尚未运行"],
      ["行情合格",passed?"是":"尚未通过"],
      ["自动交易", "关闭"],
      ["每日自动任务", "尚未启用"]
    ];
    if(s&&s.issue_code)fields.push(["故障代号",s.issue_code]);
    if(s&&s.failure_type)fields.push(["故障类型",s.failure_type]);
    for(const [label,value] of fields){const line=element("dl","detail-line");line.appendChild(element("dt","",label));line.appendChild(element("dd","",value));detail.appendChild(line);}
  }
  function renderSettings(){
    const a=state.account,valid=!!moneyValues(a);
    setText("settings-account-status",valid?"已确认并持久化":"尚未初始化");
    setText("settings-account-date",valid?dateText(a.as_of):"—");
    setText("settings-account-total",valid?amount(total(a)):"—");
    setText("settings-confirmed",valid?timeText(a.recorded_at):"—");
    setText("settings-note",valid?a.note||"未填写":"—");
    setText("settings-storage-status",state.status&&state.status.storage_verified===true?"已核验":"待验证");
  }
  function navigate(){
    let key=window.location.hash.replace("#","");
    if(!pages[key])key="overview";
    for(const panel of $$("[data-page]")){const active=panel.dataset.page===key;panel.hidden=!active;panel.classList.toggle("is-current",active);}
    for(const item of $$("[data-route]")){const active=item.dataset.route===key;item.classList.toggle("is-active",active);if(active)item.setAttribute("aria-current","page");else item.removeAttribute("aria-current");}
    setText("topbar-title",pages[key]);document.title="InvestLab — "+pages[key];
    $("sidebar").classList.remove("is-open");$("mobile-scrim").hidden=true;$("mobile-menu").setAttribute("aria-expanded","false");
    window.scrollTo({top:0,behavior:"instant"});
  }
  function openModal(dialog){if(typeof dialog.showModal==="function")dialog.showModal();else dialog.setAttribute("open","");}
  function closeModal(dialog){if(typeof dialog.close==="function")dialog.close();else dialog.removeAttribute("open");}
  function openEditor(){
    const a=state.account;
    if(!a){showToast("账户状态尚未读取完成，无法保存。",true);return;}
    const form=$("valuation-form");form.reset();$("valuation-error").hidden=true;
    const now=new Date();const iso=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(now);
    $("valuation-date").value=a.account_initialized?a.as_of:iso;
    for(const m of meta)$("valuation-"+m.symbol.toLowerCase()).value=a.account_initialized?String(a.values[m.symbol]):"0";
    setText("valuation-dialog-title",a.account_initialized?"记录新的账户估值":"创建真实投资账户");
    setText("form-total",amount(total(a)));
    openModal($("valuation-dialog"));$("valuation-date").focus();
  }
  function validateValuation(){
    const values={},max=999999999999;
    for(const m of meta){const input=$("valuation-"+m.symbol.toLowerCase());const raw=input.value.trim();const n=Number(raw);
      if(!/^(0|[1-9]\d{0,11})$/.test(raw)||!Number.isSafeInteger(n)||n<0||n>max)throw new Error(m.symbol+" 必须是非负整数人民币金额。");
      values[m.symbol]=raw;
    }
    if(meta.reduce((sum,m)=>sum+Number(values[m.symbol]),0)<=0)throw new Error("总资产必须大于零。");
    const date=$("valuation-date").value,remark=$("valuation-note").value.trim();
    if(!/^\d{4}-\d\d-\d\d$/.test(date))throw new Error("请填写有效的估值日期。");
    if(remark.length<5||remark.length>160)throw new Error("请填写 5 至 160 字的估值来源说明。");
    if(!$("valuation-confirmed").checked)throw new Error("请先确认本次估值准确无误。");
    return {as_of:date,values,note:remark,confirmed:true};
  }
  async function submitValuation(event){
    event.preventDefault();if(state.mutating)return;
    const error=$("valuation-error");error.hidden=true;
    let payload;try{payload=validateValuation();}catch(e){error.textContent=e.message;error.hidden=false;return;}
    const a=state.account,updating=a&&a.account_initialized===true;
    if(!a){error.textContent="账户尚未加载";error.hidden=false;return;}
    if(updating)payload.expected_state_version=a.state_version;
    state.mutating=true;const btn=$("save-valuation");busyButton(btn,true,"正在保存并回读…");
    try{
      const data=await api(updating?"/api/valuation":"/api/initialize",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      if(!["INITIALIZED","UPDATED"].includes(data.status)||!data.readback||data.readback.verified!==true)throw new Error("服务器没有完成持久化验收。");
      const saved=data.readback;
      if(saved.as_of!==payload.as_of||meta.some(m=>String(saved.values[m.symbol])!==payload.values[m.symbol]))throw new Error("服务器回读金额与本次确认值不一致。");
      const check=await api("/api/account");
      if(!check.account_initialized||check.state_version!==data.state_version||check.as_of!==payload.as_of||
        meta.some(m=>String(check.values[m.symbol])!==payload.values[m.symbol]))throw new Error("第二次独立读取未能确认当前快照。");
      closeModal($("valuation-dialog"));showToast("已保存并独立回读验证："+amount(saved.total_value_cny)+"。历史版本已保留。",false);
      await loadAll();
    }catch(e){error.textContent="尚未确认保存成功："+e.message+"。请先刷新账户，不要连续提交。";error.hidden=false;}
    finally{state.mutating=false;busyButton(btn,false,"保存并验证");}
  }
  function openRun(){
    if(!state.account||!state.account.account_initialized){showToast("请先保存真实账户估值。",true);return;}
    if(state.mutating){showToast("另一个操作仍在执行，请稍后。",true);return;}
    openModal($("run-dialog"));
  }
  async function submitRun(){
    if(state.mutating||!state.account||!state.account.state_version)return;
    state.mutating=true;const btn=$("confirm-run");busyButton(btn,true,"正在核验行情…");
    const version=state.account.state_version;
    closeModal($("run-dialog"));
    showToast("在线计算已提交。请保持页面打开，系统正在进行质量检查。",false);
    try{
      const result=await api("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmed:true,expected_state_version:version})});
      if(result.status!=="SUCCEEDED"||result.qualified_online!==true)throw new Error("本轮未达到合格在线运行标准。");
      showToast("在线行情与独立验证通过。请查看运行报告。",false);
    }catch(e){
      showToast("本次监控未验收成功："+e.message+"。请先查看运行状态，不要立即重复运行。",true);
    }finally{state.mutating=false;busyButton(btn,false,"确认运行");await loadAll();window.location.hash="runs";}
  }
  async function diagnoseResearch(){
    const btn=$("diagnose-research"),out=$("research-diagnostic-result");
    if(!btn||!out||btn.disabled)return;
    btn.disabled=true;
    out.textContent="正在重新采集真实行情并做隔离计算，可能需要数十秒…";
    try{
      let data;
      try{
        data=await api("/api/diagnostics/research",{method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({confirmed:true})});
      }catch(error){
        if(!error.payload||!error.payload.status)throw error;
        data=error.payload;
      }
      if(data.status==="QUALIFIED"){
        out.textContent="本次独立重测已通过行情和研究校验。诊断未保存为正式日报；请核对定时任务的下一次运行记录。";
      }else if(data.status==="FAILED"){
        const market=data.market||{};
        const summary=["QQQ","TQQQ"].map(t=>{
          const x=market[t];
          if(!x)return t+"：没有可用采集记录";
          const status=x.online_success?"在线历史已获取":"在线历史未成功获取";
          const quote=x.independent_source||"NOT_VERIFIED";
          const date=x.latest_price_session||"无日期";
          const errors=(x.source_status||[]).filter(y=>y.status==="ERROR")
            .map(y=>y.source).join("、");
          return t+"："+status+"；行情 "+date+"；独立来源 "+quote+
            (errors?"；采集错误来源 "+errors:"");
        });
        const checks=Array.isArray(data.failed_audit_checks)?data.failed_audit_checks:[];
        out.textContent="本次失败类型："+(data.failure_category||"RESEARCH_EXECUTION_FAILED")+
          "。"+(checks.length?"未通过的审计项目："+checks.join("、")+"。":"")+
          summary.join("。")+"。诊断没有更改账户。";
      }else{
        out.textContent="诊断未能完成："+(data.failure_category||data.status||"UNKNOWN");
      }
    }catch(error){
      out.textContent="诊断请求未完成："+error.message;
    }finally{btn.disabled=false;}
  }
  async function loadSchedulerState(){
    const out=$("scheduler-state"),alert=$("scheduler-alert-state");
    if(!out||!alert)return;
    out.textContent="正在查询每日运行记录…";
    try{
      const x=await api("/api/scheduler/status");
      const status=x.last_result==="SUCCEEDED"?
        "上次运行已通过":x.last_result==="NOT_YET_RUN"?
        "尚无每日任务运行记录":x.last_result==="FAILED"?
        "上次自动监控失败":"最近状态："+String(x.last_result||"UNKNOWN");
      out.textContent=(x.configured?"定时功能已配置。":"定时执行尚未启用。")+
        " "+status+(x.last_session?"（美股 "+x.last_session+"）":"")+
        "。只有连续实际运行记录才能证明长期稳定。";
      alert.textContent=x.smtp_configured?
        "故障邮件已配置；是否实际送达，需要进行一次通知测试。":
        "故障邮件尚未配置，运行失败不会自动发邮件。";
    }catch(error){
      out.textContent="未能读取调度状态，不代表已启用。请检查登录和云端运行状态。";
      alert.textContent="邮件通知状态未知。";
    }
  }
  async function checkRecovery(){
    const btn=$("check-recovery"),out=$("recovery-result");
    if(!btn||!out||btn.disabled)return;
    btn.disabled=true;
    out.textContent="正在隔离校验最近两份私有快照…";
    try{
      const data=await api("/api/recovery");
      if(data.current_restorable===true){
        out.textContent=data.older_restorable===true?
          "最新和上一份快照均通过恢复校验（仅同一存储）。独立备份与自动恢复尚未验证。":
          "最新快照可恢复，但未验证上一份有效快照。独立备份与自动恢复尚未验证。";
      }else{
        out.textContent="最新快照未通过恢复校验。请保留现有版本，停止并发更新并人工排查。";
      }
    }catch(error){
      if(error.payload&&error.payload.status==="CURRENT_SNAPSHOT_NOT_RESTORABLE"){
        out.textContent="最新快照恢复失败"+(error.payload.older_restorable===true?"；上一份有效，但不会自动回退。":"，且尚无确认可用的旧版本。")+"请先人工核对。";
      }else if(error.payload&&error.payload.status==="NO_ACCOUNT_SNAPSHOTS"){
        out.textContent="尚无已确认的账户快照，无法验证恢复。";
      }else{
        out.textContent="恢复检查未完成，不能据此认定备份可用。请检查登录或存储状态。";
      }
    }finally{btn.disabled=false;}
  }
  function wire(){
    window.addEventListener("hashchange",navigate);navigate();
    $("mobile-menu").addEventListener("click",()=>{const open=!$("sidebar").classList.contains("is-open");$("sidebar").classList.toggle("is-open",open);$("mobile-scrim").hidden=!open;$("mobile-menu").setAttribute("aria-expanded",String(open));});
    $("mobile-scrim").addEventListener("click",()=>{$("sidebar").classList.remove("is-open");$("mobile-scrim").hidden=true;$("mobile-menu").setAttribute("aria-expanded","false");});
    $("refresh-button").addEventListener("click",loadAll);$("error-retry").addEventListener("click",loadAll);
    $("check-recovery").addEventListener("click",checkRecovery);
    $("diagnose-research").addEventListener("click",diagnoseResearch);
    $("refresh-scheduler-status").addEventListener("click",loadSchedulerState);
    for(const b of $$("[data-open-editor]"))b.addEventListener("click",openEditor);
    for(const b of $$("[data-open-run]"))b.addEventListener("click",openRun);
    for(const b of $$("[data-close-dialog]"))b.addEventListener("click",()=>closeModal(b.closest("dialog")));
    for(const b of $$("[data-period]"))b.addEventListener("click",()=>{state.period=b.dataset.period;for(const x of $$("[data-period]")){const active=x===b;x.classList.toggle("is-selected",active);x.setAttribute("aria-pressed",String(active));}renderChart();});
    for(const m of meta)$("valuation-"+m.symbol.toLowerCase()).addEventListener("input",()=>{let sum=0;for(const x of meta)sum+=number($("valuation-"+x.symbol.toLowerCase()).value);setText("form-total",amount(sum));});
    $("valuation-form").addEventListener("submit",submitValuation);$("confirm-run").addEventListener("click",submitRun);
    window.addEventListener("beforeunload",event=>{if(state.mutating){event.preventDefault();event.returnValue="";}});
  }
  wire();loadAll();loadSchedulerState();
})();
