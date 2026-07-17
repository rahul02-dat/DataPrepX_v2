"""
ml-engine-py entrypoint.

Phase 0 scope only: expose /healthz so gateway-go and CI can confirm the service boots.
No pipeline logic (gates, lineage, imputation, RL, MAML, Optuna) belongs here yet — see
docs/01_IMPLEMENTATION_PLANNER.md for phase-by-phase build order. Do not import pandas/sklearn
logic into this file beyond what's needed for the health endpoint.
"""

from fastapi import FastAPI

app = FastAPI(title="dataprepx-ml-engine", version="0.0.1")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "ml-engine-py"}