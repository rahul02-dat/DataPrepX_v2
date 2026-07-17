"""
agent-orchestrator entrypoint.

Phase 0 scope only: expose /healthz. The LangGraph summarizer graph (compute_stats ->
retrieve_grounding_facts -> draft_claim -> verify_claim_against_stats -> score_confidence ->
emit_or_flag) is Phase 7 work — see docs/01_IMPLEMENTATION_PLANNER.md. Nothing here touches
Ollama yet beyond confirming the configured URL, and this service must never receive raw
dataframes (CLAUDE.md §2) — only pre-computed, gate-approved statistics, once that wiring exists.
"""

import os

from fastapi import FastAPI

app = FastAPI(title="dataprepx-agent-orchestrator", version="0.0.1")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "service": "agent-orchestrator",
        "ollama_url_configured": OLLAMA_URL,
    }