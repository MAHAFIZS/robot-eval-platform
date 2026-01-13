from fastapi import FastAPI
from packages.backend.db import ping_db

app = FastAPI(title="Robot Eval Orchestrator API")

@app.get("/health")
def health():
    return {"status": "ok", "db": "ok" if ping_db() else "down"}
