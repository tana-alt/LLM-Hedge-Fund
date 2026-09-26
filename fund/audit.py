"""Evidence-based daily cycle audit. It never alters a decision or paper account."""
from .common import PRIVATE, load, save, utc_now


def audit_day(day):
    folder=PRIVATE/"runs"/day
    run=load(folder/"result.json")
    review=load(folder/"review.json")
    paper=load(folder/"fill_and_pnl.json")
    paper_failure=load(folder/"paper_failure.json")
    stages=(run or {}).get("stages",{})
    failures=[]
    for name,stage in stages.items():
        if stage.get("status") in ("failed","skipped"):
            failures.append({"stage":name,"class":stage.get("failure_class") or "system_workflow","code":stage.get("code")})
    if not run:
        failures.append({"stage":"research","class":"system_schedule","code":"missing_run"})
    elif run.get("status")!="decision_frozen":
        failures.append({"stage":"decision","class":"system_workflow","code":run.get("status")})
    if not paper or paper.get("status")!="completed":
        failures.append({"stage":"paper","class":paper_failure.get("failure_class","system_workflow") if paper_failure else "system_workflow","code":paper_failure.get("code","missing_or_incomplete_pnl") if paper_failure else "missing_or_incomplete_pnl"})
    needs_review=bool(run and run.get("research_level") in ("L2","L3") and run.get("status")=="decision_frozen")
    quality_failures=[]
    if needs_review and (not review or review.get("status")!="completed"):
        failures.append({"stage":"review","class":review.get("failure_class","system_workflow") if review else "system_workflow","code":review.get("code","missing_review") if review else "missing_review"})
    elif needs_review and review["review"].get("gate")!="pass":
        quality_failures.append({"stage":"review","code":"review_gate_failed","verified_defects":review["review"].get("verified_defects",[])})
    system_failures=[x for x in failures if x["class"].startswith("system")]
    llm_failures=[x for x in failures if x["class"].startswith("llm")]
    ops_loop_ran=bool(run and stages.get("data",{}).get("status")=="passed" and paper and paper.get("status")=="completed")
    audit={"day":day,"audited_at":utc_now(),"status":"passed" if not failures and not quality_failures else "failed","research_status":run.get("status") if run else "missing","research_level":run.get("research_level") if run else None,"review_gate":review.get("review",{}).get("gate") if review and review.get("status")=="completed" else None,"paper_status":paper.get("status") if paper else "missing","operations_loop_ran":ops_loop_ran,"system_failures":system_failures,"llm_failures":llm_failures,"quality_failures":quality_failures,"decision_id":run.get("pm_decision",{}).get("decision_id") if run else None,"nav":paper.get("nav") if paper else None}
    save(folder/"cycle_audit.json",audit)
    return audit
