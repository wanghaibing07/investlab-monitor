"""Allocation review, not orders. Core maintenance and tactical entry are separate.

Uses the user's proposed allocation as a reference, without treating it as a fill,
an assessed personal risk budget, or evidence that timing outperforms holding.
"""
import hashlib
import json
import zlib
import statistics
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def config():
    return json.loads((ROOT / 'advisory_policy.json').read_text('utf8'))


def source_bundle():
    return {name: (ROOT/name).read_text('utf8') for name in
            ('advisory.py', 'advisory_policy.json', 'strategy.py', 'monitor.py')}


def price_inputs(candles, cutoff):
    import monitor as m
    return {symbol: [{'date':r['trade_date'], 'adjusted_close':r['adjusted_close'],
                      'raw_close':r['raw_close']} for r in rows if r['trade_date'] <= cutoff]
            for symbol, rows in candles.items() if symbol in m.ACTIVE_SYMBOLS}


def trend_history(rows, policy):
    """Replay hysteresis from available past closes; no dependence on run count."""
    n = policy['trend']['sma_sessions']; total = 0.; active = False; result = []
    for i, row in enumerate(rows):
        total += row['adjusted_close']
        if i >= n: total -= rows[i-n]['adjusted_close']
        sma = total/n if i >= n-1 else None
        if sma is not None:
            price = row['adjusted_close']
            if price > sma*(1+policy['trend']['entry_buffer']): active = True
            elif price < sma*(1-policy['trend']['exit_buffer']): active = False
        result.append({'active': active, 'sma': sma})
    return result


def full_reference(candles, policy, cutoff):
    """Model reference: existing 70% core, equal-risk split of a 20% sleeve.
    The selected universe is user-defined; these weights are model assumptions.
    """
    if policy.get('allocation_source','').startswith('USER_CONFIRMED_TARGET'):
        ref=dict(policy['strategic_reference'])
        if any(not math.isfinite(v) or v<0 for v in ref.values()) or abs(sum(ref.values())-1)>1e-8:
            raise ValueError('INVALID_USER_TARGET_WEIGHTS')
        return ref
    import monitor as m
    maps={s:{r['trade_date']:r['adjusted_close'] for r in candles[s] if r['trade_date']<=cutoff} for s in ('QLD','TQQQ')}
    dates=sorted(set(maps['QLD'])&set(maps['TQQQ']))[-61:]
    if len(dates)<61 or dates[-1]!=cutoff or m.missed_weekdays(dates[0],__import__('datetime').date.fromisoformat(cutoff))!=60:
        raise ValueError('QLD_OR_TQQQ_60_SESSION_HISTORY_INCOMPLETE')
    vol={s:statistics.stdev(maps[s][b]/maps[s][a]-1 for a,b in zip(dates,dates[1:])) for s in maps}
    if min(vol.values())<=0:raise ValueError('TACTICAL_VARIANCE_NOT_ESTIMABLE')
    fraction=vol['TQQQ']/(vol['QLD']+vol['TQQQ']);pool=policy['tactical_pool']
    q=policy['strategic_reference']['QQQ']
    return {'QQQ':q,'QLD':pool*fraction,'TQQQ':pool*(1-fraction),'CASH':1-q-pool}


def review_weights(current, trend_on, vol_pct, policy, reference=None):
    """One next step from confirmed weights. Repeated reports never imply fills."""
    if 'QLD' in current:
        ref=reference or policy['strategic_reference'];q=current['QQQ'];l=current['QLD'];t=current['TQQQ']
        q_next=ref['QQQ'] if abs(q-ref['QQQ'])>=policy['core_drift_band']-1e-10 else q
        total=l+t;pool=policy['tactical_pool']
        if not trend_on or vol_pct>=policy['volatility']['exit_at_pct']:
            l_next=t_next=0.;reason='TREND_EXIT' if not trend_on else 'VOLATILITY_EXIT'
        elif vol_pct<policy['volatility']['entry_max_pct']:
            new_total=min(pool,total+policy['tactical_add_step']) if pool-total>=policy['tactical_drift_band']-1e-10 else min(pool,total)
            ratio=ref.get('QLD',0)/(ref.get('QLD',0)+ref['TQQQ'])
            l_next=new_total*ratio;t_next=new_total*(1-ratio)
            reason='TREND_ENTRY_STEP' if new_total>total else ('TRIM_ABOVE_REFERENCE' if total>pool else 'WITHIN_TACTICAL_BAND')
        else:
            scale=min(1.,pool/total) if total else 1.;l_next=l*scale;t_next=t*scale;reason='VOLATILITY_PAUSE_ADDITIONS'
        q_next=max(0.,min(q_next,1-policy['minimum_cash']-l_next-t_next,
                         policy['maximum_daily_ndx_exposure']-2*l_next-3*t_next))
        return {'QQQ':q_next,'QLD':l_next,'TQQQ':t_next,'CASH':1-q_next-l_next-t_next},reason
    ref = policy['strategic_reference']; q = current['QQQ']; t = current['TQQQ']
    q_next = ref['QQQ'] if abs(q-ref['QQQ']) >= policy['core_drift_band']-1e-10 else q
    if not trend_on or vol_pct >= policy['volatility']['exit_at_pct']:
        t_next = 0.; reason = 'TREND_EXIT' if not trend_on else 'VOLATILITY_EXIT'
    elif t > ref['TQQQ']:
        t_next = ref['TQQQ']; reason = 'TRIM_ABOVE_REFERENCE'
    elif vol_pct < policy['volatility']['entry_max_pct']:
        gap = ref['TQQQ']-t
        t_next = min(ref['TQQQ'], t+policy['tactical_add_step']) if gap >= policy['tactical_drift_band']-1e-10 else t
        reason = 'TREND_ENTRY_STEP' if t_next > t else 'WITHIN_TACTICAL_BAND'
    else:
        t_next = t; reason = 'VOLATILITY_PAUSE_ADDITIONS'
    # Hard reference envelopes apply even when an existing overweight position drifts.
    t_next = min(t_next, ref['TQQQ'])
    q_next = min(q_next, 1-policy['minimum_cash']-t_next,
                 policy['maximum_daily_ndx_exposure']-3*t_next)
    q_next = max(0., q_next)
    return {'QQQ': q_next, 'TQQQ': t_next, 'CASH': 1-q_next-t_next}, reason


def leg_action(before, after):
    return 'INCREASE_REVIEW' if after > before+1e-9 else (
        'REDUCE_REVIEW' if after < before-1e-9 else 'HOLD')


def opportunity_diagnostic(report, candles, policy):
    """Signed counterfactual for a fixed baseline slice, not actual account PnL."""
    p = report['portfolio']; anchor = p['as_of']; cutoff = report['as_of_expected_session']
    rows = {r['trade_date']: r for r in candles['QQQ'] if r['trade_date'] <= cutoff}
    if anchor not in rows or cutoff not in rows or p['total_cny'] <= 0:
        return {'status': 'UNAVAILABLE', 'reason': 'BASELINE_CLOSE_OR_EQUITY_MISSING'}
    q_weight = p['qqq_value_cny']/p['total_cny']
    slice_weight = max(0., policy['strategic_reference']['QQQ']-q_weight)
    change = rows[cutoff]['adjusted_close']/rows[anchor]['adjusted_close']-1
    return {'status': 'COUNTERFACTUAL_NOT_ACTUAL_PNL', 'baseline_date': anchor,
            'end_date': cutoff, 'qqq_total_return_pct': change*100,
            'baseline_equity_slice_weight': slice_weight,
            'qqq_instead_of_zero_yield_cash_difference_cny': p['total_cny']*slice_weight*change,
            'cash_yield_assumption': 0, 'fees_and_fx_included': False,
            'interpretation': '正数表示该固定资金片段买QQQ更高，负数表示持现金更高；不推算真实账户收益'}


def observe(report, candles):
    policy = config(); bundle = source_bundle(); cutoff = report['as_of_expected_session']
    legacy = report['strategy_observation']; p = report['portfolio']
    out = {'version': policy['version'], 'policy_id': policy['policy_id'], 'scope': policy['scope'],
           'policy_sha256': digest(policy), 'source_sha256': digest(bundle),
           'price_input_sha256': digest(price_inputs(candles,cutoff)),
           'session_date': cutoff, 'status': 'DATA_BLOCKED', 'orders': [],
           'trading_enabled': False, 'strategic_reference': policy['strategic_reference'],
           'allocation_source': policy['allocation_source'], 'personal_suitability': 'NOT_ASSESSED',
           'executable_delta_cny': None, 'executable_shares': None,
           'account_as_of': p['as_of'], 'account_valuation_current': p['as_of'] == cutoff,
           'legacy_comparison_only': True, 'actions': {}, 'next_review_weights': None,
           'data_limit': '最新原价跨网站核对不等于完整复权历史独立验证'}
    if legacy['data_blockers']:
        out['blockers'] = legacy['data_blockers']; out['headline'] = '行情校验未通过，暂停新配置复核'
    elif p['total_cny'] <= 0:
        out['blockers'] = ['ZERO_ACCOUNT_VALUE']; out['headline'] = '缺少可比较的账户基线'
    else:
        try:reference=full_reference(candles,policy,cutoff)
        except ValueError as exc:
            out.update(blockers=[str(exc)],headline='QLD/杠杆历史尚不完整，待数据更新后复核')
            out['signal_id']=digest(out)[:24]
            return out
        out['strategic_reference']=reference
        rows = [r for r in candles['QQQ'] if r['trade_date'] <= cutoff]
        trend = trend_history(rows, policy)[-1]; m = legacy['qqq_indicators']; vol = m['vol20_pct']
        current = {'QQQ': p['qqq_value_cny']/p['total_cny'],
                   'QLD': p.get('qld_value_cny',0)/p['total_cny'],
                   'TQQQ': p['tqqq_value_cny']/p['total_cny'], 'CASH': p['cash_cny']/p['total_cny']}
        target, reason = review_weights(current, trend['active'], vol, policy,reference)
        import monitor as monitor
        fresh = report['mode'] == f'ONLINE_{len(monitor.ACTIVE_SYMBOLS)}_OF_{len(monitor.ACTIVE_SYMBOLS)}'
        out.update(status='ALLOCATION_REVIEW' if fresh else 'CACHE_REPLAY_ONLY',
                   current_baseline_weights=current, next_review_weights=target,
                   actions={k: leg_action(current[k], target[k]) for k in policy['asset_universe']},
                   tactical_reason=reason, trend_active=trend['active'], qqq_vol20_pct=vol,
                   signal_source='QQQ_ADJUSTED_CLOSE', execution_timing=policy['execution'],
                   next_qqq_trend_entry_price=trend['sma']*(1+policy['trend']['entry_buffer']),
                   next_qqq_trend_exit_price=trend['sma']*(1-policy['trend']['exit_buffer']),
                   price_threshold_note='随每日SMA变化，不是固定止损价；跳空可能越过阈值',
                   full_reference_daily_exposure=reference['QQQ']+2*reference['QLD']+3*reference['TQQQ'],
                   next_review_daily_exposure=target['QQQ']+2*target['QLD']+3*target['TQQQ'],
                   repeat_policy='未收到新的持仓确认前，重复运行只重复同一待复核步骤，不累加买入',
                   entry_conditions=[
                       {'rule': 'QQQ趋势已开启：上穿SMA200的103%，下穿98%退出', 'met': trend['active']},
                       {'rule': 'QQQ的20日年化波动低于25%才能增加TQQQ', 'met': vol < policy['volatility']['entry_max_pct']},
                       {'rule': f'TQQQ距{policy["tactical_pool"]:.0%}目标至少2个百分点', 'met': policy['tactical_pool']-current['QLD']-current['TQQQ'] >= policy['tactical_drift_band']-1e-10}],
                   legacy_pullback_condition={'required_qqq_drawdown_pct': [-12, -5],
                       'actual_qqq_drawdown_pct': m['drawdown252_pct'],
                       'met': -12 <= m['drawdown252_pct'] <= -5,
                       'blocks_current_advisory': False},
                   opportunity_diagnostic=opportunity_diagnostic(report, candles, policy))
        changed = any(v != 'HOLD' for v in out['actions'].values())
        out['headline'] = '按60% QQQ、40% TQQQ目标分步调整' if changed else '当前仓位无需调整'
        if not fresh: out['headline'] = '缓存复算：'+out['headline']+'，不能当本轮在线信号'
        out['amount_status'] = ('AGGREGATE_ESTIMATE_ONLY_NO_SHARES_OR_LIVE_FX' if out['account_valuation_current']
                                else 'REFRESH_ACCOUNT_VALUATION_BEFORE_ORDER_SIZING')
    # Price timestamps and tiny revisions are not new decisions. Evidence is saved in the run.
    out['signal_id'] = digest({k: out.get(k) for k in
        ('source_sha256', 'session_date', 'status', 'account_as_of', 'current_baseline_weights',
         'actions', 'tactical_reason', 'trend_active', 'blockers')} | {
             'target': {k: round(v, 4) for k,v in (out['next_review_weights'] or {}).items()}})[:24]
    return out


def persist(signal, created_at, db):
    import monitor as m
    with m.conn(db) as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS allocation_policy_versions (
            source_sha256 TEXT PRIMARY KEY, registered_at TEXT NOT NULL, source_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS allocation_reviews (
            signal_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL REFERENCES allocation_policy_versions(source_sha256),
            session_date TEXT NOT NULL, created_at TEXT NOT NULL, signal_json TEXT NOT NULL, signal_sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS allocation_price_inputs (
            input_sha256 TEXT PRIMARY KEY, compressed_prices BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS allocation_review_observations (
            signal_id TEXT NOT NULL REFERENCES allocation_reviews(signal_id),
            input_sha256 TEXT NOT NULL REFERENCES allocation_price_inputs(input_sha256),
            observed_at TEXT NOT NULL, PRIMARY KEY(signal_id,input_sha256,observed_at));''')
        bundle = source_bundle()
        if digest(bundle) != signal['source_sha256']: raise ValueError('Allocation review source changed before persistence')
        prices = price_inputs(m.price_data(db),signal['session_date'])
        if digest(prices) != signal['price_input_sha256']: raise ValueError('Allocation price inputs changed before persistence')
        c.execute('INSERT OR IGNORE INTO allocation_policy_versions VALUES(?,?,?)',
                  (signal['source_sha256'], created_at, m.canonical(bundle)))
        c.execute('INSERT OR IGNORE INTO allocation_reviews VALUES(?,?,?,?,?,?)',
                  (signal['signal_id'], signal['source_sha256'], signal['session_date'], created_at,
                   m.canonical(signal), digest(signal)))
        c.execute('INSERT OR IGNORE INTO allocation_price_inputs VALUES(?,?)',
                  (signal['price_input_sha256'],zlib.compress(m.canonical(prices).encode(),9)))
        c.execute('INSERT OR IGNORE INTO allocation_review_observations VALUES(?,?,?)',
                  (signal['signal_id'],signal['price_input_sha256'],created_at))


def audit(db):
    import monitor as m
    with m.conn(db) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='allocation_reviews'").fetchone():
            return {'reviews': 0, 'signal_hash_errors': 0, 'source_hash_errors': 0, 'input_hash_errors':0}
        rows = c.execute('SELECT signal_json,signal_sha256 FROM allocation_reviews').fetchall()
        versions = c.execute('SELECT source_sha256,source_json FROM allocation_policy_versions').fetchall()
        has_inputs=c.execute("SELECT 1 FROM sqlite_master WHERE name='allocation_price_inputs'").fetchone()
        inputs = c.execute('SELECT input_sha256,compressed_prices FROM allocation_price_inputs').fetchall() if has_inputs else []
        archived_inputs = {x[0] for x in inputs}
    input_errors = 0
    for sha, payload in inputs:
        try: input_errors += digest(json.loads(zlib.decompress(payload))) != sha
        except (ValueError,zlib.error,UnicodeError): input_errors += 1
    return {'reviews': len(rows), 'signal_hash_errors': sum(digest(json.loads(a)) != b for a,b in rows),
            'source_hash_errors': sum(digest(json.loads(b)) != a for a,b in versions),
            'input_hash_errors':input_errors,
            'qualified_reviews_missing_inputs':sum(bool(json.loads(a).get('price_input_sha256')) and
                json.loads(a)['price_input_sha256'] not in archived_inputs for a,b in rows),
            'excluded_development_reviews_without_input_hash':sum(not json.loads(a).get('price_input_sha256') for a,b in rows)}


LABEL = {'INCREASE_REVIEW': '评估增加', 'REDUCE_REVIEW': '评估减少', 'HOLD': '维持'}
REASONS = {'TREND_ENTRY_STEP': '趋势和波动条件满足，分步增加', 'TREND_EXIT': '趋势关闭，退出战术仓',
           'VOLATILITY_EXIT': '波动达到退出阈值', 'VOLATILITY_PAUSE_ADDITIONS': '波动升高，暂停增加',
           'TRIM_ABOVE_REFERENCE': '仓位超过参考上限，减少超出部分', 'WITHIN_TACTICAL_BAND': '仓位处于偏差容忍范围'}


def report_lines(signal):
    out = ['## 配置复核｜QQQ、TQQQ', signal['headline']]
    target = signal.get('next_review_weights'); current = signal.get('current_baseline_weights')
    if target:
        for k in signal['actions']:
            out.append(f'{k}：{LABEL[signal["actions"][k]]}；最后确认基线 {current[k]:.0%} → 本步参考 {target[k]:.0%}。')
        ref=signal['strategic_reference']
        out.append(f'你确认的最终目标：QQQ {ref["QQQ"]:.0%} / TQQQ {ref["TQQQ"]:.0%} / 现金 {ref["CASH"]:.0%}。目标尚未登记为实际成交。')
        out.append(f'趋势状态：'+('开启' if signal['trend_active'] else '关闭')+f'；QQQ年化波动 {signal["qqq_vol20_pct"]:.2f}%；TQQQ原因：{REASONS[signal["tactical_reason"]]}。')
        for condition in signal['entry_conditions']:
            out.append(('满足：' if condition['met'] else '未满足：')+condition['rule'])
        out.append(f'下一次趋势参考：QQQ上穿 ${signal["next_qqq_trend_entry_price"]:.2f} 开启，下穿 ${signal["next_qqq_trend_exit_price"]:.2f} 关闭；均随SMA变化。波动达35%触发TQQQ退出复核，25%–35%暂停增加。')
        old = signal['legacy_pullback_condition']
        out.append(f'旧回调规则对照：QQQ回撤 {old["actual_qqq_drawdown_pct"]:.2f}%，要求5%–12%；'+('满足' if old['met'] else '未满足')+'，已不拦截当前配置复核。')
        d = signal['opportunity_diagnostic']
        if d['status'] == 'COUNTERFACTUAL_NOT_ACTUAL_PNL':
            out.append(f'等待对照（非实际盈亏）：从{d["baseline_date"]}至{d["end_date"]}，将基线资产的{d["baseline_equity_slice_weight"]:.0%}改持QQQ而非零息现金，差额约 ¥{d["qqq_instead_of_zero_yield_cash_difference_cny"]:+.2f}；不含费用及汇率，正数买QQQ较高，负数现金较高。')
        out.append('账户估值截至'+signal['account_as_of']+'；先更新持仓估值再确定下单金额。只有成交或持仓确认才推进下一步，重复日报不会自动加仓。')
    else:
        out.append('原因：'+'；'.join(signal.get('blockers',[])))
    out.append('规则支持人工配置复核；尚未证明择时优于持有，个人资金用途与可承受回撤尚未评估。')
    return out
