import os
import json
import glob
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks
import logging
from master_agent import GeminiMasterAgent

log = logging.getLogger("orchestrator.api")
router = APIRouter()

LOGS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "agent_logs"
STATUS_FILE = LOGS_DIR / "agent_status.json"

def read_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {
        "master": {"status": "idle", "last_run": None},
        "yield": {"status": "idle", "last_run": None, "last_result": None},
        "cfo": {"status": "idle", "last_run": None, "last_result": None},
        "network": {"status": "idle", "last_run": None, "last_result": None},
        "fuel": {"status": "idle", "last_run": None, "last_result": None},
    }

def write_status(data: dict):
    LOGS_DIR.mkdir(exist_ok=True)
    STATUS_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

async def execute_agent_ensemble():
    status = read_status()
    status["master"]["status"] = "running"
    write_status(status)
    log.info("Executing Agent Ensemble from Background Task...")
    try:
        agent = GeminiMasterAgent(status_callback=update_agent_status)
        await agent.run()
        status = read_status()
        status["master"]["status"] = "completed"
        from datetime import datetime
        status["master"]["last_run"] = datetime.now().isoformat()
        write_status(status)
        log.info("Agent Ensemble Execution Complete!")
    except Exception as e:
        status = read_status()
        status["master"]["status"] = "error"
        write_status(status)
        log.error(f"Agent Ensemble Execution Failed: {e}", exc_info=True)

def update_agent_status(agent_name: str, field: str, value):
    status = read_status()
    if agent_name not in status:
        status[agent_name] = {"status": "idle", "last_run": None, "last_result": None}
    status[agent_name][field] = value
    write_status(status)

@router.post("/run")
async def trigger_orchestrator(background_tasks: BackgroundTasks):
    background_tasks.add_task(execute_agent_ensemble)
    return {"status": "success", "message": "Ensemble triggered."}

@router.get("/status")
async def get_status():
    return read_status()

@router.get("/logs")
async def get_logs():
    if not LOGS_DIR.exists():
        return {"logs": []}
    log_files = sorted(glob.glob(str(LOGS_DIR / "master_log_*.md")), reverse=True)
    logs_data = []
    for lf in log_files:
        p = Path(lf)
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
            logs_data.append({"filename": p.name, "timestamp": p.stat().st_ctime, "content": content})
        except:
            pass
    return {"logs": logs_data}

@router.get("/logs/{agent_name}")
async def get_agent_logs(agent_name: str):
    if agent_name not in ("yield", "cfo", "network", "fuel", "master"):
        return {"error": "Unknown agent"}
    if not LOGS_DIR.exists():
        return {"logs": []}
    pattern = f"{agent_name}_log_*.md"
    log_files = sorted(glob.glob(str(LOGS_DIR / pattern)), reverse=True)
    logs_data = []
    for lf in log_files:
        p = Path(lf)
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
            logs_data.append({"filename": p.name, "timestamp": p.stat().st_ctime, "content": content})
        except:
            pass
    return {"logs": logs_data}
