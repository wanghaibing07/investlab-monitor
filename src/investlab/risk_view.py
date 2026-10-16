"""Private standalone research report; no scripts, remote resources, or account edits."""
import html

LABELS={'C0_ORIGINAL':'原生产规则 C0','C1_SHORT_TERM_FILTER':'短期下跌过滤 C1',
        'C2_FAST_VOL_FILTER':'快速波动过滤 C2','C3_PORTFOLIO_RISK_BUDGET':'组合波动预算 C3',
        'C4_COMBINED':'组合过滤 C4'}
PORTFOLIOS={'LAST_CONFIRMED':'最后确认比例 · QQQ 60% / 现金40%',
            'NEXT_STEP':'单步参考 · QQQ 60% / TQQQ 5% / 现金35%',
            'TARGET':'长期目标 · QQQ 60% / TQQQ 40%'}


def pct(x):return '—' if x is None else f'{x:.2%}'


def primary(out):return [r for r in out['comparisons'] if r['cost_bps']==15 and r['slippage_bps']==0]


def markdown(out):
    risk=out['risk_conflict']; review=out['production_review']
    rows=['# InvestLab 风险研究报告','',f"行情：{out['session_date']} · 独立影子研究 · 尚未发布",'',
          '**生产规则：** '+('长期趋势开启；TQQQ最多增加5个百分点进入人工复核。' if review.get('actions',{}).get('TQQQ')=='INCREASE_REVIEW' else '见归档生产判断。'),
          '**研究分歧：** '+('跌破20日均线且连续3天下跌，C1暂停新增的研究条件成立。' if risk['risk_conflict'] else '短期过滤与生产加仓没有同时冲突。'),
          f"**执行准备：** 账户截至{review['account_as_of']}，份额、成本、汇率和个人回撤预算未齐，不产生订单。",
          '**证据质量：** 独立复权历史未验证；历史已参与研发；前瞻效果尚未建立。','',
          '## 同期对照','', '每边手续费15基点、额外滑点0；信号后下一交易日收盘假设成交。现金零息，税和汇率未计。','',
          '| 规则 | 年化收益 | 年化波动 | 最大回撤 | 最差5%日均值 | 最长回撤交易日 | 调仓次数 |',
          '|---|---:|---:|---:|---:|---:|---:|']
    for r in primary(out):
        rows.append(f"| {LABELS[r['model_id']]} | {pct(r['cagr'])} | {pct(r['annual_vol'])} | {pct(r['max_drawdown'])} | {pct(r['cvar95_daily'])} | {r['longest_underwater_sessions']} | {r['rebalances']} |")
    rows+=['','## 组合风险','', '| 组合 | 近似单日敞口 | 60日窗口年化波动 | TQQQ方差占比 |','|---|---:|---:|---:|']
    for name,r in out['portfolio_risk'].items():rows.append(f"| {name} | {r['approximate_daily_exposure']:.2f}倍 | {pct(r['annual_vol'])} | {pct(r['variance_contribution']['TQQQ'])} |")
    rows+=['','## 反例与失败','',
           f"找到 {out['counterexamples']['events']} 个短期过滤触发日。完整保留错过反弹和避免下跌的5日重叠窗口，不把这些窗口当独立样本。",
           'C3/C4允许降低QQQ并留现金，是未经审批的研究情景。风险改善须同时比较收益损失、上行参与和调仓成本。',
           '开盘成交仅为显式假设；没有可靠历史OHLC，不能把开盘敏感性当实际可成交回测。',
           '15%波动标准化使用整段历史估计，仅作描述性比较，不能作为可交易策略。','',
           '## 可复核证据','',f"- 预登记 {out['completed_registered_trials']} 个情景；参数搜索0次。",
           '- 两档费用下C0净值与交易列表逐项一致；C0—C4前缀因果检查通过。',
           f"- 账本前后SHA-256一致：`{out['account_database_after']}`。",
           f"- 输入哈希：`{out['input_hash']}`。",f"- 结果哈希：`{out['result_hash']}`。",
           '- 多时间点恢复、独立历史资格及前瞻观察按单独门槛验收；本报告不宣称总体验收完成。','']
    return '\n'.join(rows)


def render(out):
    risk=out['risk_conflict'];review=out['production_review']; esc=html.escape
    cells=[]
    for r in primary(out):
        cells.append('<tr><th>'+esc(LABELS[r['model_id']])+'</th>'+''.join('<td>'+esc(str(x))+'</td>' for x in
                    (pct(r['cagr']),pct(r['annual_vol']),pct(r['max_drawdown']),pct(r['cvar95_daily']),r['rebalances']))+'</tr>')
    port=''.join('<div class="metric"><small>'+esc(PORTFOLIOS[n])+'</small><strong>'+pct(r['annual_vol'])+'</strong><span>60日窗口年化波动 · '+f"{r['approximate_daily_exposure']:.2f}倍单日近似敞口"+'</span></div>' for n,r in out['portfolio_risk'].items())
    blocked=out['data_qualification']['status']=='DATA_BLOCKED'
    offline=out.get('runtime_mode')=='OFFLINE'
    state=('行情校验未通过' if blocked else '离线研究快照' if offline else
           '存在风险分歧' if risk['risk_conflict'] else '账户估值待更新' if risk.get('account_stale') else '待人工确认，尚未成交')
    action={'INCREASE_REVIEW':'评估增加','REDUCE_REVIEW':'评估减少','HOLD':'维持'}.get(review.get('actions',{}).get('TQQQ'),'数据待补齐')
    production_note=('数据不足，暂停新的调整复核。' if blocked else
                     '仅显示归档判断，联网更新后再复核。' if offline else
                     '归档生产判断：'+action+'；最多新增5个百分点进入人工复核，尚未成交。')
    short='收盘低于20日均线，且连续3天下跌。C1研究条件要求暂停新增。' if risk['risk_conflict'] else '短期过滤条件未与生产加仓同时成立。'
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>InvestLab · 风险研究</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f5f6;color:#172c33;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1160px;margin:auto;padding:44px 24px}header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #d3dddf;padding-bottom:22px}.brand{font-weight:800;letter-spacing:.08em}.tag{font-size:12px;background:#dce9e5;padding:5px 10px;border-radius:5px}h1{font-size:clamp(29px,5vw,48px);line-height:1.2;margin:35px 0 12px}h2{font-size:24px;margin-top:38px}p{margin:8px 0;color:#4f646a}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:28px 0}.card{background:white;padding:24px;border:1px solid #dce4e5;border-radius:12px}.card.warning{border-top:4px solid #ca8d31}.card strong{font-size:20px}.eyebrow{font-size:12px;letter-spacing:.12em;color:#61767a}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.metric{background:#173f43;color:white;border-radius:12px;padding:22px}.metric strong{display:block;font-size:34px}.metric span{display:block;font-size:13px;color:#c7dddc}.scroll{overflow:auto;background:white;border:1px solid #dce4e5;border-radius:12px}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{text-align:right;padding:16px;border-bottom:1px solid #e7eded}th:first-child{text-align:left}thead{background:#e9eeee}details{background:white;margin-top:20px;padding:20px;border-radius:10px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}footer{margin-top:40px;border-top:1px solid #d3dddf;padding-top:18px;font-size:13px;color:#61767a}@media(max-width:640px){main{padding:24px 16px}.grid,.metrics{grid-template-columns:1fr}.card{padding:20px}header{gap:15px}th,td{padding:12px}}</style>
<main><header><div class="brand">INVESTLAB / RESEARCH</div><span class="tag">PAPER · 未发布</span></header>'''+f'''
<h1>{state}</h1><p>行情截至 {esc(out['session_date'])}。生产判断、研究观察与执行条件放在一起核对。</p>
<div class="grid"><section class="card"><div class="eyebrow">01 / 生产规则</div><strong>长期趋势：{'开启' if review.get('trend_active') else '关闭'}</strong><p>{esc(production_note)}</p></section>
<section class="card warning"><div class="eyebrow">02 / 研究观察</div><strong>短期风险独立展示</strong><p>{short}</p></section>
<section class="card"><div class="eyebrow">03 / 执行条件</div><strong>尚未就绪</strong><p>账户截至 {esc(review['account_as_of'])}。份额、成本、汇率和个人回撤预算尚未齐备。没有金额、股数或订单。</p></section>
<section class="card"><div class="eyebrow">04 / 研究证据</div><strong>历史诊断 · 需要前瞻观察</strong><p>独立复权历史仍有缺口；已有历史参与过研发。影子结果不修改生产规则与通知。</p></section></div>
<h2>同一个纳指风险，不同杠杆比例</h2><div class="metrics">{port}</div>
<h2>同成本、同时间的规则对照</h2><p>每边15基点费用，额外滑点0；下一交易日收盘假设成交。均为历史研究。</p>
<div class="scroll"><table><thead><tr><th>规则</th><th>年化收益</th><th>年化波动</th><th>最大回撤</th><th>最差5%日均值</th><th>调仓次数</th></tr></thead><tbody>{''.join(cells)}</tbody></table></div>
<h2>看清代价，再做判断</h2><p>暂停加仓也可能错过反弹；降低波动可能牺牲上涨参与。所有候选、成本情景和反例都已留档，历史表现不直接决定生产上线。</p>
<details><summary>参数、限制与验证证据</summary><pre>{esc(markdown(out))}</pre></details>
<footer>独立研究版 · 原账户与生产规则保留 · 本报告没有创建或执行证券订单</footer></main></html>'''
