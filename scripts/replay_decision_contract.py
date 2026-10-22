"""Read-only decision replay; public code, private input/output.

Usage: PYTHONPATH=src python scripts/replay_decision_contract.py --home PATH --output NEW_DIRECTORY
"""
from pathlib import Path
import argparse
from copy import deepcopy
import hashlib
import json
import sqlite3
import statistics
import sys

from investlab.core import ENGINE, digest
from investlab.decision import account_evidence, decide
from investlab.engine.advisory import config, review_weights, trend_history

p = argparse.ArgumentParser()
p.add_argument("--home", required=True); p.add_argument("--output", required=True)
args = p.parse_args(); home = Path(args.home).resolve(); output = Path(args.output).resolve()
if output.exists(): raise SystemExit("Output must be a new directory")
if output.is_relative_to(home): raise SystemExit("Research output must start outside the runtime")
output.mkdir(parents=True)
spec = {"candidate": "ACCOUNT_FACTS_AND_EXECUTION_GATES_ONLY", "new_market_parameters": 0,
        "outcome": "Remove false zero-position and conflicting executable advice",
        "historical_evidence": "ALREADY_SEEN_SINGLE_PROVIDER_NOT_ALPHA_VALIDATION",
        "example_selection": "FIRST_CHRONOLOGICAL_MATCH_PER_PREDECLARED_CONDITION",
        "conditions": ["RSI2_GT70_THEN_5D_GAIN", "RSI2_GT70_THEN_5D_LOSS",
                       "THREE_DROPS_BELOW_SMA20_THEN_5D_GAIN", "TREND_EXIT_THEN_5D_GAIN"],
        "cost_bps": [15, 50], "signal": "CLOSE_T", "execution": "CLOSE_T_PLUS_1",
        "stopping_rule": "Structural tests and reference numerical equality; no parameter search"}
(output / "registered_protocol.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
db = home / "data/monitor.sqlite3"; before = hashlib.sha256(db.read_bytes()).hexdigest()
with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as c:
    c.row_factory = sqlite3.Row
    raw = {s: [dict(r) for r in c.execute("SELECT * FROM daily_prices WHERE symbol=? ORDER BY trade_date", (s,))]
           for s in ("QQQ", "TQQQ")}
    last = json.loads(c.execute("SELECT report_json FROM monitor_runs ORDER BY rowid DESC LIMIT 1").fetchone()[0])
policy = config()
last["allocation_review"]["status"] = "ALLOCATION_REVIEW"
last["mode"] = "ONLINE_2_OF_2"  # Explicit frozen replay assumption, never persisted as a new online run.
a = account_evidence(db, last["portfolio"], last["as_of_expected_session"])
cfg = json.loads((home / "settings.json").read_text())
frozen = decide(last, a, cfg.get("risk_budget"), policy)
sys.path.insert(0, str(ENGINE))
import monitor as m
from research.common import read_protocol
from research.dataset import from_candles, features
from advisory_compare import simulate_review
from research.engine import metrics
from investlab.engine import strategy
from investlab.verification import replay_trade_schedule
data = from_candles(raw, last["as_of_expected_session"]); fs = features(data, read_protocol())
with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as c:
    archived = json.loads(c.execute("SELECT source_json FROM allocation_policy_versions ORDER BY rowid DESC LIMIT 1").fetchone()[0])
unchanged = {name: (ENGINE / name).read_text() == text for name, text in archived.items()}
if not all(unchanged.values()): raise SystemExit("C0 reference source differs from archived baseline")


def simulate_candidate(data, fs, cost):
    dates = data["dates"]; trends = trend_history(data["QQQ"], policy)
    values = [0., 0., 1.]; curve = [1.]; events = []; exposures = []
    synthetic_budget = dict(confirmed=True, source="SYNTHETIC_HISTORICAL_REPLAY_NOT_USER_BUDGET",
        confirmed_at="2026-10-01", emergency_reserve_cny="0", reserve_location="OUTSIDE_ACCOUNT",
        investable_capital_cny="1000000000000", max_acceptable_loss_cny="1000000000000",
        minimum_cash_cny="0", maximum_daily_ndx_exposure=1.8, maximum_tqqq_weight=.4)
    for i in range(252, len(dates)):
        total=sum(values); current=dict(zip(("QQQ","TQQQ","CASH"), [v/total for v in values]))
        ref, reason=review_weights(current,trends[i-1]["active"],fs[i-1]["vol20_pct"],policy)
        reference={"status":"ALLOCATION_REVIEW","trend_active":trends[i-1]["active"],
                   "qqq_vol20_pct":fs[i-1]["vol20_pct"],"next_review_weights":ref}
        synthetic_account={"blockers":[],"current_values_cny":dict(zip(("QQQ","TQQQ","CASH"),values))|{"QLD":0.},
                           "evidence_id":digest(current),"reconciliation_required":False}
        r={"as_of_expected_session":dates[i-1],"mode":"ONLINE_2_OF_2",
           "data_evidence_grade":"CURRENT_SINGLE_SOURCE","allocation_review":reference,
           "market":{s:{"quality":"CURRENT","last_date":dates[i-1]} for s in ("QQQ","TQQQ")}}
        decision=decide(r,synthetic_account,synthetic_budget,policy)
        target=decision["target_weights"] or current
        exposures.append(current["QQQ"]+3*current["TQQQ"])
        for k,symbol in enumerate(("QQQ","TQQQ")):
            values[k] *= data[symbol][i]["adjusted_close"]/data[symbol][i-1]["adjusted_close"]
        if any(abs(target[k]-current[k])>1e-9 for k in ("QQQ","TQQQ")):
            values,fee,traded=strategy.rebalance(values,target["QQQ"],target["TQQQ"],cost/10000)
            events.append({"signal_session":dates[i-1],"execute_session":dates[i],
                           "target":target,"reason":decision["status"],"fee":fee,"traded":traded})
        curve.append(sum(values))
    return {"summary":metrics(curve,dates[251:],events,exposures),"dates":dates[251:],"curve":curve,"trades":events}

paths = {}
for cost in spec["cost_bps"]:
    baseline = simulate_review(data, fs, policy, cost)
    candidate = simulate_candidate(data, fs, cost)
    prices={"dates":data["dates"],"prices":{s:[r["adjusted_close"] for r in data[s]] for s in ("QQQ","TQQQ")}}
    independent=replay_trade_schedule(prices,candidate,cost)
    error=max(abs(a-b)/max(abs(a),1e-15) for a,b in zip(independent,candidate["curve"]))
    if error>1e-9: raise SystemExit("Candidate independent accounting mismatch")
    prefix={k:v[:-20] if isinstance(v,list) else v for k,v in data.items()}
    shorter=simulate_candidate(prefix,fs[:-20],cost)
    if candidate["curve"][:len(shorter["curve"])]!=shorter["curve"]:
        raise SystemExit("Candidate future-price leakage")
    paths[str(cost)] = {"c0_reference": baseline["summary"],
                        "candidate_with_synthetic_complete_account": candidate["summary"],
                        "full_path_equal": baseline["curve"]==candidate["curve"],
                        "independent_accounting_max_relative_error":error,"prefix_causality_passed":True,
                        "candidate_curve_sha256":digest(candidate["curve"]),
                        "candidate_trades_sha256":digest(candidate["trades"])}
# Simple holding references share dates, prices, costs and next-session initial execution.
from investlab.verification import piecewise_rebalance
def holding(qw, tw, cost):
    dates = data["dates"]; values = [0., 0., 1.]; curve = [1.]; events = []
    for i in range(252, len(dates)):
        for k, symbol in enumerate(("QQQ", "TQQQ")):
            values[k] *= data[symbol][i]["adjusted_close"] / data[symbol][i-1]["adjusted_close"]
        if i == 252:
            values, fee = piecewise_rebalance(values, [qw, tw, 1-qw-tw], cost)
            events.append({"signal_session": dates[i-1], "execute_session": dates[i], "fee": fee})
        curve.append(sum(values))
    peak=curve[0]; worst=0.
    for v in curve: peak=max(peak,v);worst=min(worst,v/peak-1)
    n=len(curve)-1
    return {"total_return_pct": (curve[-1]-1)*100,
            "cagr_pct": (curve[-1]**(252/n)-1)*100, "max_drawdown_pct": worst*100,
            "transactions": len(events), "scope": "BUY_ONCE_HOLD_NO_REBALANCE_NOT_RISK_MATCHED"}
for cost in paths:
    paths[cost]["simple_holding"] = {"QQQ100":holding(1,0,float(cost)),
                                    "INITIAL60_40":holding(.6,.4,float(cost))}
q = data["QQQ"]; closes = [r["adjusted_close"] for r in q]; trends = trend_history(q, policy)
rsi = [None]*len(q); gain=loss=None
for i in range(2,len(q)):
    if i==2:
        changes=[closes[j]-closes[j-1] for j in (1,2)]
        gain=sum(max(x,0) for x in changes)/2;loss=sum(max(-x,0) for x in changes)/2
    else:
        d=closes[i]-closes[i-1];gain=(gain+max(d,0))/2;loss=(loss+max(-d,0))/2
    rsi[i]=100 if loss==0 else 100-100/(1+gain/loss)
examples={}; counts={k:0 for k in spec["conditions"]}
for i in range(252,len(q)-5):
    fwd=closes[i+5]/closes[i]-1
    conditions={"RSI2_GT70_THEN_5D_GAIN":rsi[i]>70 and fwd>0,
                "RSI2_GT70_THEN_5D_LOSS":rsi[i]>70 and fwd<0,
                "THREE_DROPS_BELOW_SMA20_THEN_5D_GAIN":closes[i]<statistics.mean(closes[i-19:i+1]) and all(closes[j]<closes[j-1] for j in range(i-2,i+1)) and fwd>0,
                "TREND_EXIT_THEN_5D_GAIN":trends[i-1]["active"] and not trends[i]["active"] and fwd>0}
    for name,met in conditions.items():
        if not met:continue
        counts[name]+=1
        examples.setdefault(name,{"session":data["dates"][i],"rsi2":rsi[i],
                                "next_5_session_return_pct":fwd*100,
                                "forward_end":data["dates"][i+5]})
after=hashlib.sha256(db.read_bytes()).hexdigest()
if before != after: raise SystemExit("Read-only replay changed the database")
result={"protocol_sha256":digest(spec),"data_sha256":data["data_sha256"],
        "database_sha256":before,"read_only_unchanged":True,
        "start":data["dates"][251],"end":data["dates"][-1],
        "c0_reference_sources_unchanged":unchanged,
        "cost_comparisons":paths,"counterexamples":examples,"condition_counts":counts,
        "frozen_decision":{"scope":"FROZEN_REPLAY_NOT_NEW_ONLINE_SIGNAL","account_state":a,"decision":frozen},
        "conclusion":"C0 formulas unchanged. Candidate uses actual decision gates with synthetic complete accounts; its paths may differ. Real partial account is blocked. No alpha claim.",
        "limits":["SINGLE_PROVIDER_ADJUSTED_HISTORY_NOT_INDEPENDENTLY_VERIFIED",
                  "HISTORY_ALREADY_SEEN","NO_TAX_FX_OR_CASH_YIELD","NOT_REAL_ACCOUNT_PNL",
                  "NO_STRATEGY_PROFITABILITY_OR_LOSS_CAP_PROVEN"]}
(output / "replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=2,allow_nan=False))
print(json.dumps({"output":str(output),"read_only_unchanged":True,
                  "status":frozen["status"],"examples":len(examples),
                  "c0_reference_sources_unchanged":all(unchanged.values()),
                  "candidate_prefix_and_accounting_passed":True},ensure_ascii=False))

