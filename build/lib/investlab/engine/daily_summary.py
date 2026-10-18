"""Plain-language daily decisions; engineering checks stay separate from returns."""
import os
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DATA_ROOT=Path(os.environ.get('INVESTLAB_HOME',str(ROOT))).expanduser().resolve()/'data'


def decision_lines(run):
    review=run.get('allocation_review',{});target=review.get('next_review_weights')
    if review.get('status')!='ALLOCATION_REVIEW' or not target:
        action=('行情有冲突，先核对价格' if run.get('data_evidence_grade')=='SOURCE_CONFLICT'
                else '仅复算已有行情，暂不生成新的调整建议' if review.get('status')=='CACHE_REPLAY_ONLY'
                else '本轮数据不足，暂不生成新的调整建议')
        return ['今日：'+action+'。','目标：QQQ 60%、TQQQ 40%。']
    actions=[]
    for symbol in ('QQQ','TQQQ'):
        code=review['actions'][symbol]
        if code=='HOLD':actions.append(symbol+'维持')
        else:
            verb='分批增加至' if code=='INCREASE_REVIEW' else '减少至'
            actions.append(f'{symbol}{verb}{target[symbol]:.0%}')
    reason=review.get('tactical_reason')
    if reason=='VOLATILITY_PAUSE_ADDITIONS':explanation='近期波动较高，暂停增加TQQQ。'
    elif reason=='VOLATILITY_EXIT':explanation='近期波动达到退出门槛，降低杠杆。'
    elif reason=='TREND_EXIT':explanation='长期趋势转弱，降低杠杆。'
    elif reason=='TREND_ENTRY_STEP':explanation='长期趋势向上，近期波动低于加仓门槛。'
    else:explanation='仓位按目标和偏差范围维护。'
    return ['今日：'+'；'.join(actions)+'（占总资产）。',
            f'目标：QQQ 60%、TQQQ 40%；本步现金{target["CASH"]:.0%}。',
            '原因：'+explanation]


def build_summary(run,health=None,*,saved=False):
    health=health or {};lines=decision_lines(run)
    dates={v.get('last_date') for v in run.get('market',{}).values()}
    date=next(iter(dates)) if len(dates)==1 else '部分日期不一致'
    online=run.get('mode')=='ONLINE_2_OF_2' and set(run.get('market',{}))=={'QQQ','TQQQ'} and all(v.get('quality')=='CURRENT' for v in run['market'].values())
    updates='已更新至'+str(date)+'收盘' if online else '本轮未完整更新，保留缓存'
    independent=all(run.get('fetch',{}).get(s,{}).get('independent_status')=='MATCH' for s in ('QQQ','TQQQ'))
    continuity=health.get('continuity',{}).get('consecutive_verified_distinct_sessions_after_readback')
    stable=f'{continuity}/5个交易日' if continuity is not None else '待核对'
    lines.append(f'运行：{updates}；稳定性观察{stable}。')
    if not independent:lines.append('待补：备用行情核对；策略效果继续检验。')
    missing=[]
    for key,label in (('quant','概率与情景'),('mature','成熟模型'),('research','历史研究')):
        if run.get(key+'_persistence_error'):missing.append(label+'记录未保存')
    for key,label in (('quant_analysis','概率与情景'),('mature_models','成熟模型')):
        if run.get(key,{}).get('status','').endswith('_ERROR'):missing.append(label+'计算失败')
    if missing:lines.append('本轮缺口：'+'；'.join(missing)+'。')
    lines.append('账户截至'+run['portfolio']['as_of']+'；建议不会自动记为成交。')
    if saved:lines.append('文件：已保存并核对。')
    return '\n'.join(lines)


def research_lines(run):
    obj=run.get('quant_analysis',{});risk=obj.get('risk_contributions',{}).get('FULL_TARGET_REFERENCE')
    out=['## 量化模型与路径推演']
    if risk:
        out.append(f'60/40目标组合近{risk["window"]}日估计年化波动：{risk["annual_volatility"]:.1%}；TQQQ贡献约{risk["variance_contribution_share"]["TQQQ"]:.0%}的组合波动风险。')
        out.append('目标组合约有1.8倍单日纳指敞口：指数单日跌5%，组合粗略跌9%；多日收益取决于实际路径。')
    validation=obj.get('historical_validation')
    if validation and validation.get('brier_skill',0)<=0:
        out.append('概率预测仍未在历史检验中胜过简单的历史频率，只用于观察，不触发交易。')
    elif obj.get('risk_forecast'):
        out.append('概率预测继续观察与检验，不触发交易。')
    out.append('风险平价、波动目标、均值回归、动量与宏观模型继续比较；它们的研究仓位不覆盖你确认的60/40目标。')
    return out


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--saved',action='store_true',help='仅在本轮保存和实际取回核验成功后使用')
    args=parser.parse_args();run=json.loads((DATA_ROOT/'latest.json').read_text())
    path=DATA_ROOT/'automation_health.json';health=json.loads(path.read_text()) if path.exists() else {}
    print(build_summary(run,health,saved=args.saved))


if __name__=='__main__':main()
