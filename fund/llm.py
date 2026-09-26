import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .common import PRIVATE, config, digest, fail, load, save, utc_now


def parse_json(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end+1])
        raise


def call(role, prompt, run_id, step):
    spec = config()["models"][role]
    if len(prompt) > config()["model_budget"]["max_input_chars_per_call"]:
        return fail("system_input", "prompt_budget", f"{len(prompt)} chars exceeds fixed budget")
    command = ["modelctl", "run", "--runtime", "pi", "--provider", spec["provider"], "--model", spec["model"], "--mode", "text", "--json"]
    fallback_used=False
    for attempt in (1,2):
        et_day=datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        development="-draft" in run_id
        budget_path=PRIVATE/"usage"/f"{'development-' if development else ''}{et_day}.json"
        budget=load(budget_path,{"attempts":[]})
        count=sum(x["role"]==role for x in budget["attempts"])
        limit=spec["max_dev_calls_daily"] if development else spec["max_calls_daily"]
        if count>=limit:
            return fail("system_budget","daily_model_call_cap",f"{role} {count}/{limit} on {et_day} ({'development' if development else 'production'})")
        budget["attempts"].append({"role":role,"run_id":run_id,"step":step,"at":utc_now(),"prompt_sha256":digest(prompt)})
        save(budget_path,budget)
        try:
            if fallback_used:
                # Agent mode has filesystem tools. Keep it outside the repository and
                # pass only the bounded prompt; no source files or project path.
                with tempfile.TemporaryDirectory(prefix="fund-llm-") as isolated:
                    env={k:v for k,v in os.environ.items() if k in ("HOME","PATH","USER","LOGNAME","TMPDIR","LANG")}
                    process = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=180, cwd=isolated, env=env)
            else:
                process = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=180, cwd=Path(__file__).resolve().parents[1])
        except (OSError, subprocess.TimeoutExpired) as exc:
            return fail("system_runtime", "modelctl_launch", exc)
        envelope = {"role":role,"step":step,"attempt":attempt,"model":spec,"command":command,"fallback_used":fallback_used,"prompt_sha256":digest(prompt),"called_at":utc_now(),"exit_code":process.returncode,"stdout":process.stdout,"stderr":process.stderr[-3000:]}
        save(PRIVATE / "runs" / run_id / "llm" / f"{step}-attempt-{attempt}.json", envelope)
        error_text=process.stderr+process.stdout
        if process.returncode and attempt==1:
            if "429" in error_text and spec.get("fallback"):
                backup=spec["fallback"]
                command=["modelctl","run","--runtime",backup["runtime"],"--model",backup["model"],"--mode","agent","--json"]
                fallback_used=True
                continue
            if "503" in error_text:
                continue
        break
    if process.returncode:
        return fail("system_runtime", "modelctl_exit", process.stderr[-1000:] or process.stdout[-1000:])
    try:
        outer = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return fail("system_protocol", "modelctl_envelope", exc)
    if outer.get("status") != "completed":
        return fail("system_runtime", "modelctl_status", outer.get("status"))
    try:
        answer = parse_json(outer["text"])
    except (KeyError, json.JSONDecodeError) as exc:
        return fail("llm_instruction", "invalid_json", exc)
    if not isinstance(answer,dict):
        return fail("llm_instruction","json_not_object",type(answer).__name__)
    actual_model={"provider":outer.get("provider"),"model":outer.get("model"),"runtime":outer.get("runtime"),"fallback_used":fallback_used}
    return {"status":"completed","answer":answer,"usage":outer.get("usage",{}),"model":actual_model,"prompt_sha256":envelope["prompt_sha256"]}
