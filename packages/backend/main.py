from fastapi import FastAPI

app = FastAPI(title="Robot Eval Orchestrator API")

@app.get("/health")
def health():
    return {"status": "ok"}
