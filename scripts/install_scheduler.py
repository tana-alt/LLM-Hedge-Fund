"""Install a per-user launchd runner; schedule gates are evaluated in New York time."""
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LABEL="com.tana-alt.llm-hedge-fund"
DEST=Path.home()/"Library"/"LaunchAgents"/(LABEL+".plist")


def main():
    (ROOT/"logs").mkdir(exist_ok=True)
    DEST.parent.mkdir(parents=True,exist_ok=True)
    modelctl=shutil.which("modelctl")
    if not modelctl: raise RuntimeError("modelctl missing from install environment")
    search_path=str(Path(modelctl).parent)+":"+os.environ.get("PATH","/usr/bin:/bin")
    spec={"Label":LABEL,"ProgramArguments":[sys.executable,"-m","fund.cli","tick"],"WorkingDirectory":str(ROOT),"StartInterval":300,"RunAtLoad":True,"StandardOutPath":str(ROOT/"logs"/"scheduler.out"),"StandardErrorPath":str(ROOT/"logs"/"scheduler.err"),"EnvironmentVariables":{"PYTHONUNBUFFERED":"1","PATH":search_path}}
    DEST.write_bytes(plistlib.dumps(spec))
    domain=f"gui/{os.getuid()}"
    subprocess.run(["launchctl","bootout",domain,str(DEST)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(20):
        if subprocess.run(["launchctl","print",domain+"/"+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
            break
        time.sleep(.1)
    for attempt in range(3):
        result=subprocess.run(["launchctl","bootstrap",domain,str(DEST)],text=True,capture_output=True)
        if result.returncode==0:break
        if attempt==2:raise RuntimeError(result.stderr)
        time.sleep(.25)
    check=subprocess.run(["launchctl","print",domain+"/"+LABEL],text=True,capture_output=True)
    if check.returncode:
        raise RuntimeError(check.stderr)
    print(f"installed {LABEL} at {DEST}")
    print("verified launchctl service entry")


if __name__=="__main__":main()
