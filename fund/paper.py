"""Paper fills at Yahoo's daily Open and close-to-close account ledger."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas_market_calendars as mcal

from .common import PRIVATE, config, fail, load, save, utc_now


def _bar(symbol, day):
    cfg=config()["price"]
    frame=yf.Ticker(symbol).history(start=day,end=(date.fromisoformat(day)+timedelta(days=1)).isoformat(),interval="1d",auto_adjust=False,actions=True,repair=False)
    if len(frame)!=1 or frame.index[0].date().isoformat()!=day:
        raise RuntimeError(f"missing exact-date Yahoo bar {symbol} {day}")
    row=frame.iloc[0]
    bar={k:float(row.get(k,0)) for k in ("Open","High","Low","Close","Volume","Dividends","Stock Splits")}
    if not (bar["Low"]<=min(bar["Open"],bar["Close"])<=max(bar["Open"],bar["Close"])<=bar["High"] and bar["Open"]>0 and bar["Volume"]>0):
        raise RuntimeError(f"invalid exact-date bar {symbol} {day}")
    return bar


def close_day(day):
    run=load(PRIVATE/"runs"/day/"result.json")
    decision_valid=bool(run and run.get("status")=="decision_frozen")
    target=PRIVATE/"runs"/day/"fill_and_pnl.json"
    state_path=PRIVATE/"paper_account.json"
    previous_report=load(target)
    if previous_report:
        current=load(state_path)
        if current and current.get("last_day")>=day:
            return previous_report
        after=previous_report.get("account_after")
        if after and after.get("last_day")==day:
            save(state_path,after)
            return previous_report
        return fail("system_accounting","orphaned_report_without_recovery_state",day)
    try:
        cost=_bar("COST",day)
        spy=_bar("SPY",day)
    except Exception as exc:
        return fail("system_data","market_bar_unavailable",exc)
    account=load(state_path,{"cash":config()["initial_cash_usd"],"shares":0,"last_day":None,"risk_cap":config()["max_stock_weight"],"benchmark_cost_shares":0,"benchmark_cost_cash":0,"benchmark_spy_shares":0,"benchmark_spy_cash":0})
    if account["last_day"] and account["last_day"]>=day:
        return fail("system_workflow","out_of_order_close",account["last_day"])
    if account["last_day"]:
        skipped=mcal.get_calendar("NYSE").valid_days(start_date=(date.fromisoformat(account["last_day"])+timedelta(days=1)).isoformat(),end_date=(date.fromisoformat(day)-timedelta(days=1)).isoformat()) if (date.fromisoformat(day)-date.fromisoformat(account["last_day"])).days>1 else []
        if len(skipped):
            return fail("system_workflow","unprocessed_prior_session",skipped[0].date().isoformat())
    split=cost["Stock Splits"]
    if split and split>0:
        account["shares"]*=split
        account["benchmark_cost_shares"]*=split
    if spy["Stock Splits"] and spy["Stock Splits"]>0:
        account["benchmark_spy_shares"]*=spy["Stock Splits"]
    if account["shares"]:
        account["cash"]+=account["shares"]*cost["Dividends"]
    account["benchmark_cost_cash"]+=account["benchmark_cost_shares"]*cost["Dividends"]
    account["benchmark_spy_cash"]+=account["benchmark_spy_shares"]*spy["Dividends"]
    portfolio_at_open=account["cash"]+account["shares"]*cost["Open"]
    decision=run["pm_decision"] if decision_valid else {"action":"HOLD","target_weight":None,"decision_id":None}
    weight=decision.get("target_weight") or 0
    if decision["action"]=="WATCH": weight=account["shares"]*cost["Open"]/portfolio_at_open
    if decision["action"]=="HOLD": weight=account["shares"]*cost["Open"]/portfolio_at_open
    max_weight=run.get("stages",{}).get("pm_decision",{}).get("risk_cap",account["risk_cap"]) if decision_valid else account["risk_cap"]
    account["risk_cap"]=max_weight
    above_cap=account["shares"]*cost["Open"]/portfolio_at_open>max_weight+1e-8
    if weight>max_weight+1e-8:
        weight=max_weight
    bps=config()["one_way_cost_bps"]/10000
    desired_shares=int(portfolio_at_open*weight/cost["Open"])
    if decision["action"] in ("HOLD","WATCH") and account["shares"]*cost["Open"]/portfolio_at_open<=max_weight:
        desired_shares=account["shares"]
    if decision["action"]=="BUY" and desired_shares<account["shares"] and account["shares"]*cost["Open"]/portfolio_at_open<=max_weight:
        desired_shares=account["shares"]
    if decision["action"]=="SELL" and desired_shares>account["shares"]:
        desired_shares=account["shares"]
    trade=desired_shares-account["shares"]
    if trade>0:
        trade=min(trade,int(account["cash"]/(cost["Open"]*(1+bps))))
    fee=abs(trade)*cost["Open"]*bps
    account["cash"]-=trade*cost["Open"]+fee
    account["shares"]+=trade
    if account["cash"] < -1e-6 or account["shares"]<0:
        return fail("system_accounting","negative_cash_or_short",account)
    if account["benchmark_cost_shares"]==0:
        account["benchmark_cost_shares"]=config()["initial_cash_usd"]/cost["Open"]
        account["benchmark_spy_shares"]=config()["initial_cash_usd"]/spy["Open"]
    nav=account["cash"]+account["shares"]*cost["Close"]
    account["last_day"]=day
    report={"status":"completed","day":day,"recorded_at":utc_now(),"backfilled_from_later_snapshot":day<datetime.now(ZoneInfo("America/New_York")).date().isoformat(),"decision_id":decision.get("decision_id"),"decision_status":run.get("status") if run else "missing","new_discretionary_trade_suppressed":not decision_valid,"risk_forced_reduction":above_cap and trade<0,"cost_bar":cost,"spy_bar":spy,"yfinance_version":yf.__version__,"trade_shares":trade,"fill_proxy_open":cost["Open"],"one_way_cost":fee,"cash":account["cash"],"shares":account["shares"],"nav":nav,"return_from_initial":nav/config()["initial_cash_usd"]-1,"cost_buy_hold_proxy":account["benchmark_cost_shares"]*cost["Close"]+account["benchmark_cost_cash"],"spy_buy_hold_proxy":account["benchmark_spy_shares"]*spy["Close"]+account["benchmark_spy_cash"],"account_after":dict(account)}
    save(target,report)
    save(state_path,account)
    return report


def close_through(day):
    """Book every missed NYSE session in order before processing the target day."""
    account=load(PRIVATE/"paper_account.json")
    if account and account.get("last_day"):
        start=(date.fromisoformat(account["last_day"])+timedelta(days=1)).isoformat()
        if start>day:
            return load(PRIVATE/"runs"/day/"fill_and_pnl.json",fail("system_workflow","already_past_day",day))
    else:
        production_runs=[p.parent.name for p in (PRIVATE/"runs").glob("*/result.json") if "-draft" not in p.parent.name and p.parent.name<=day]
        start=min(production_runs) if production_runs else day
    sessions=mcal.get_calendar("NYSE").valid_days(start_date=start,end_date=day)
    if len(sessions)==0:
        return {"status":"skipped","reason":"no NYSE session to close","through":day}
    reports=[]
    for session in sessions:
        result=close_day(session.date().isoformat())
        if result.get("status")!="completed":
            save(PRIVATE/"runs"/session.date().isoformat()/"paper_failure.json",result)
            return result
        reports.append(result)
    return {"status":"completed","through":day,"sessions_processed":[x["day"] for x in reports],"latest":reports[-1]}
