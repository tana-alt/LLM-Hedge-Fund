import argparse
import json
import fcntl
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas_market_calendars as mcal

from .common import PRIVATE, config, load, save, utc_now
from .experiment import review, run_research, retry_shadow
from .paper import close_through
from .audit import audit_day


def tick():
    PRIVATE.mkdir(parents=True,exist_ok=True)
    lockfile=open(PRIVATE/"tick.lock","w")
    try:
        fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        return {"status":"skipped","reason":"previous tick still running"}
    try:
        return _tick_locked()
    finally:
        fcntl.flock(lockfile,fcntl.LOCK_UN)
        lockfile.close()


def _tick_locked():
    now=datetime.now(ZoneInfo("America/New_York"))
    day=now.date().isoformat()
    if now.weekday()>=5:
        return {"status":"skipped","reason":"weekend","et":now.isoformat()}
    if len(mcal.get_calendar("NYSE").valid_days(start_date=day,end_date=day))==0:
        return {"status":"skipped","reason":"NYSE closed","et":now.isoformat()}
    hhmm=now.strftime("%H:%M")
    if hhmm>="09:00" and not (PRIVATE/"runs"/day/"result.json").exists():
        save(PRIVATE/"runs"/day/"result.json",{"run_id":day,"decision_date":day,"created_at":utc_now(),"draft":False,"status":"late_not_frozen","stages":{"scheduler":{"status":"failed","failure_class":"system_schedule","code":"missed_preopen_window"}}})
    if "08:00"<=hhmm<"09:00":
        result=run_research(day)
        # Work completed after the freeze deadline cannot create a paper order.
        if datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M")>="09:00" and result.get("status")=="decision_frozen":
            result["status"]="late_not_frozen"
            save(PRIVATE/"runs"/day/"result.json",result)
        return result
    if "09:05"<=hhmm<"10:00":
        return review(day)
    if "17:00"<=hhmm<"20:00":
        return close_through(day)
    if "20:00"<=hhmm<"21:00":
        return audit_day(day)
    return {"status":"skipped","reason":"outside scheduled windows","et":now.isoformat()}


def main():
    parser=argparse.ArgumentParser(description="Paper-only COST research experiment")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("research");p.add_argument("--date",required=True);p.add_argument("--draft",action="store_true");p.add_argument("--label");p.add_argument("--force",action="store_true")
    p=sub.add_parser("review");p.add_argument("run_id");p.add_argument("--force",action="store_true")
    p=sub.add_parser("retry-shadow");p.add_argument("run_id")
    p=sub.add_parser("close");p.add_argument("--date",required=True)
    p=sub.add_parser("audit");p.add_argument("--date",required=True)
    sub.add_parser("tick")
    sub.add_parser("status")
    args=parser.parse_args()
    if args.command=="research": result=run_research(args.date,args.draft,args.force,args.label)
    elif args.command=="review":result=review(args.run_id,args.force)
    elif args.command=="retry-shadow":result=retry_shadow(args.run_id)
    elif args.command=="close":result=close_through(args.date)
    elif args.command=="audit":result=audit_day(args.date)
    elif args.command=="tick":result=tick()
    else:
        service=subprocess.run(["launchctl","print",f"gui/{os.getuid()}/com.tana-alt.llm-hedge-fund"],text=True,capture_output=True)
        scheduler={"installed":service.returncode==0,"state":next((line.strip().split("=",1)[1].strip() for line in service.stdout.splitlines() if line.strip().startswith("state =")),None)}
        result={"config_version":config()["version"],"runs":[{"id":p.parent.name,"status":load(p,{}).get("status"),"stages":load(p,{}).get("stages")} for p in sorted((PRIVATE/"runs").glob("*/result.json"))],"paper":load(PRIVATE/"paper_account.json"),"scheduler":scheduler}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get("status")=="failed":raise SystemExit(1)


if __name__=="__main__":main()
