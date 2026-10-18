"""Fixed, registered policy comparison; historical diagnostics, never model selection."""
import json
import statistics
from pathlib import Path
import advisory
import monitor as m
import strategy
from research.common import read_protocol
from research.dataset import from_candles, features
from research.engine import metrics, simulate


def simulate_review(data, fs, policy, cost_bps=15, core_only=False):
    dates = data['dates']; prices = {k:[r['adjusted_close'] for r in data[k]] for k in m.LEGACY_SYMBOLS}
    trends = advisory.trend_history(data['QQQ'], policy)
    values = [0.,0.,1.]; curve = [1.]; events = []; exposures = []; weights = []
    for i in range(252, len(dates)):
        total = sum(values); current = dict(zip(('QQQ','TQQQ','CASH'), [v/total for v in values]))
        target, reason = advisory.review_weights(current, trends[i-1]['active'], fs[i-1]['vol20_pct'], policy)
        if core_only: target = {'QQQ':target['QQQ'], 'TQQQ':0., 'CASH':1-target['QQQ']}
        exposures.append(current['QQQ']+3*current['TQQQ']); weights.append(list(current.values()))
        values[0] *= prices['QQQ'][i]/prices['QQQ'][i-1]
        values[1] *= prices['TQQQ'][i]/prices['TQQQ'][i-1]
        if any(abs(target[k]-current[k]) > 1e-9 for k in ('QQQ','TQQQ')):
            values, fee, traded = strategy.rebalance(values, target['QQQ'], target['TQQQ'], cost_bps/10000)
            events.append({'signal_session':dates[i-1], 'execute_session':dates[i],
                           'target':target, 'reason':reason, 'fee':fee, 'traded':traded})
        curve.append(sum(values))
    summary = metrics(curve, dates[251:], events, exposures)
    summary['average_cash_weight'] = statistics.mean(w[2] for w in weights)
    summary['tqqq_zero_fraction'] = statistics.mean(w[1] < 1e-9 for w in weights)
    summary['yearly_return_pct'] = yearly(curve, dates[251:])
    return {'summary':summary, 'dates':dates[251:], 'curve':curve, 'trades':events}


def yearly(curve, dates):
    out = {}
    for year in sorted({d[:4] for d in dates[1:]}):
        indices = [i for i,d in enumerate(dates) if i and d.startswith(year)]
        out[year] = (curve[indices[-1]]/curve[indices[0]-1]-1)*100
    return out


def run(db=m.DB, output=None):
    policy = advisory.config(); p = read_protocol(); output = Path(output or m.ROOT/'data/advisory_v52')
    output.mkdir(parents=True, exist_ok=True)
    registry = {'policy':policy, 'policy_sha256':advisory.digest(policy),
                'source_sha256':advisory.digest(advisory.source_bundle()),
                'registered_before_comparison':True, 'historical_data_already_seen':True,
                'parameter_search_trials':0, 'claim':'POLICY_TRADEOFF_NOT_PROVEN_ALPHA'}
    # Registration is written before reading/comparing the historical paths.
    m.atomic_write(output/'registered_protocol.json', json.dumps(registry,ensure_ascii=False,indent=2).encode())
    data = from_candles(m.price_data(db), m.expected_close_session().isoformat()); fs = features(data,p)
    result = {'registry':registry, 'data_sha256':data['data_sha256'], 'start':data['dates'][251],
              'end':data['dates'][-1], 'comparisons':{},
              'limits':['SINGLE_ADJUSTED_PROVIDER','HISTORY_ALREADY_SEEN_NOT_BLIND',
                        'NOT_RISK_MATCHED','CASH_ZERO_YIELD_TAX_FX_OMITTED',
                        'HYPOTHETICAL_FILLS_NO_REAL_ACCOUNT_PNL','NO_PRE_2010_TQQQ_HISTORY'],
              'selection':'NO_OPTIMIZATION_USER_ALLOCATION_REFERENCE_WITH_MANUAL_STEPS'}
    for cost in policy['comparison_cost_bps']:
        runs = {'LEGACY_PULLBACK':simulate(data,fs,p,'C0_TACTICAL_ANCHORED',cost),
                'FIXED70_20_10':simulate(data,fs,p,'B_USER70_20_10_STRESS',cost),
                'CORE70_CASH30':simulate_review(data,fs,policy,cost,True),
                'CORE70_STAGED_TREND':simulate_review(data,fs,policy,cost)}
        for r in runs.values():
            r['summary']['yearly_return_pct'] = yearly(r['curve'],r['dates'])
        result['comparisons'][str(cost)] = {name:r['summary'] for name,r in runs.items()}
    m.atomic_write(output/'comparison.json',json.dumps(result,ensure_ascii=False,indent=2).encode())
    lines = ['# 配置策略取舍｜v5.2','',f'历史窗口：{result["start"]}至{result["end"]}。已见历史，不是盲测；不据此宣称最优。','',
             '| 配置规则 | 单边费用bp | 年化收益% | 最大回撤% | 年化波动% | 2022收益% |',
             '|---|---:|---:|---:|---:|---:|']
    for cost, runs in result['comparisons'].items():
        for name,r in runs.items():
            lines.append(f'| {name} | {cost} | {r["cagr_pct"]:.2f} | {r["max_drawdown_pct"]:.2f} | {r["annual_vol_pct"]:.2f} | {r["yearly_return_pct"].get("2022",0):.2f} |')
    lines += ['', 'QQQ核心70%为长期配置，不因战术趋势关闭而清空；因此熊市中仍会承受QQQ的大幅回撤。',
              'TQQQ每次按确认仓位增加最多5个百分点，20%只是用户计划参考上限。模拟假定每次次日收盘成交，真实日报不假定成交。',
              '比较包含不同敞口和风险，不能把收益差直接解释为择时能力；现金计零息、未扣税和汇率成本。',
              '真实TQQQ样本不覆盖2000和2008，不编造实际ETF业绩。']
    (output/'COMPARISON.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return result


if __name__ == '__main__':
    result = run()
    print(json.dumps({'start':result['start'],'end':result['end'],
                      'comparisons':result['comparisons']},ensure_ascii=False,indent=2))
