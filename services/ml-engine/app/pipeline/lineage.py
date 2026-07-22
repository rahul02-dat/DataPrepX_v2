"""
Immutable, content-addressed lineage (CLAUDE.md §5.3 / planner Phase 2).

Scope for Phase 2: validation-gate steps only. Imputation/outlier/RL/MAML/HPO steps in later
phases will call the same `record_gate_step`-style primitive (a generalized `record_step` can be
factored out once a second step type exists — not done here to avoid speculative abstraction
before there's a second real caller).

Known scoping decisions (deliberate, not oversights):
- transform_code_hash = the process's git_sha (see get_git_sha), not a per-file content hash.
  An uncommitted local edit to validation_gates.py will NOT change the lineage hash. Replay
  reproducibility is guaranteed at "this git commit" granularity, not "these exact bytes on disk
  right now." Revisit if hot-reload dev runs start being used for anything lineage-sensitive.
- The lineage_hash() computed here is a content-derived fingerprint, distinct from `runs.id`
  (the random UUID primary key gateway-go mints in Phase 1). CLAUDE.md §6 describes run_id as
  "derivable purely from (dataset content_hash, config_hash, git_sha)" — Phase 1 already
  committed to a random UUID surrogate key instead. This module stores both: the UUID as the
  foreign key everything joins on, and lineage_hash() as the deterministic fingerprint recorded
  in audit_log for verification. If this seam matters beyond Phase 2's replay check, it should be
  resolved with an ADR, not silently patched.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras

from app.pipeline.validation_gates import GateResult


def get_git_sha() -> str:
    """Reads the commit SHA the running ml-engine-py process was built from.

    Must be injected at image build time, e.g.:
        docker build --build-arg GIT_SHA=$(git rev-parse HEAD) ...
        # and in the Dockerfile: ARG GIT_SHA \n ENV GIT_SHA=${GIT_SHA}

    This is NOT yet wired into services/ml-engine/Dockerfile as of Phase 2 — that's a required
    follow-up (infra change, out of this module's scope). Falls back to a loud sentinel so a
    missing build-arg is visible in every lineage row instead of silently hashing garbage.
    """
    return os.environ.get("GIT_SHA", "unknown-git-sha")


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_dataframe(df: pd.DataFrame) -> str:
    """Deterministic content hash of a dataframe's values. Columns are sorted before hashing so
    column reordering during I/O (e.g. a different CSV column order) doesn't change the hash;
    only actual content changes should."""
    ordered = df.reindex(sorted(df.columns), axis=1)
    csv_bytes = ordered.to_csv(index=False).encode("utf-8")
    return hash_bytes(csv_bytes)


def hash_config(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, sort_keys=True, default=str)
    return hash_bytes(canonical.encode("utf-8"))


@dataclass
class LineageContext:
    """Everything needed to log a gate-check step and later replay/verify it."""

    run_id: str  # Postgres runs.id (UUID) — the Phase 1 surrogate key
    dataset_content_hash: str
    config: dict[str, Any]
    seed: int | None = None

    @property
    def config_hash(self) -> str:
        return hash_config(self.config)

    @property
    def git_sha(self) -> str:
        return get_git_sha()

    def lineage_hash(self) -> str:
        combined = f"{self.dataset_content_hash}:{self.config_hash}:{self.git_sha}"
        return hash_bytes(combined.encode("utf-8"))


def record_gate_step(conn, ctx: LineageContext, gate_results: list[GateResult]) -> str:
    """Writes one pipeline_steps row + one transformations row for this gate-check, and a
    structured pass/fail summary into audit_log (per project decision: reuse audit_log's
    existing TEXT `action` column by storing a JSON-encoded structured payload in it, rather than
    adding a new table). Returns the new pipeline_steps.id.

    output_hash equals input_hash: gates check, they don't transform data. Later phases'
    imputation/outlier steps will produce a genuinely different output_hash once they mutate
    the dataframe.
    """
    passed = all(r.passed for r in gate_results)
    params = {"config": ctx.config, "gate_results": [r.to_dict() for r in gate_results]}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_steps (run_id, step_type, input_hash, output_hash, params_json, seed)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                ctx.run_id,
                "validation_gate_check",
                ctx.dataset_content_hash,
                ctx.dataset_content_hash,
                psycopg2.extras.Json(params),
                ctx.seed,
            ),
        )
        step_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO transformations (step_id, transform_code_hash, description)
            VALUES (%s, %s, %s)
            """,
            (
                step_id,
                ctx.git_sha,
                f"Phase 2 validation gates: {[r.gate_name for r in gate_results]}",
            ),
        )

        audit_payload = {
            "event": "gate_check_passed" if passed else "gate_check_rejected",
            "lineage_hash": ctx.lineage_hash(),
            "gate_results": [r.to_dict() for r in gate_results],
        }
        cur.execute(
            "INSERT INTO audit_log (run_id, actor, action) VALUES (%s, %s, %s)",
            (ctx.run_id, "ml-engine-py:validation_gates", json.dumps(audit_payload)),
        )

    return str(step_id)


def fetch_gate_step(conn, run_id: str) -> dict[str, Any]:
    """Fetches the most recent validation_gate_check step + its transformation record for
    run_id, for replay verification. Raises ValueError (caller's job to handle) if none exists —
    this is a real "nothing to replay" condition, not something to silently return None for."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT ps.id, ps.input_hash, ps.output_hash, ps.params_json, ps.seed,
                   t.transform_code_hash
            FROM pipeline_steps ps
            JOIN transformations t ON t.step_id = ps.id
            WHERE ps.run_id = %s AND ps.step_type = 'validation_gate_check'
            ORDER BY ps.created_at DESC
            LIMIT 1
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No validation_gate_check step found for run_id {run_id}")
        return dict(row)


def fetch_dataset_storage_uri(conn, run_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT d.storage_uri FROM runs r JOIN datasets d ON d.id = r.dataset_id WHERE r.id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No dataset found for run_id {run_id}")
        return row[0]