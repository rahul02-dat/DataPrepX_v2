"""
Validates job payloads against the canonical shared/schemas/job.schema.json.

Per ADR-0002, the schema is defined once at repo root. Rather than
maintaining a second embedded copy (as gateway-go does, out of Go's
go:embed constraints), ml-engine-py reads the canonical file directly via a
path relative to the repo root, or from SHARED_SCHEMAS_DIR if set. In
Docker Compose, mount shared/schemas as a read-only volume into this
service rather than copying it, so drift between services is structurally
impossible on the Python side.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jsonschema

_DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "shared" / "schemas"


def _schema_dir() -> Path:
    override = os.environ.get("SHARED_SCHEMAS_DIR")
    return Path(override) if override else _DEFAULT_SCHEMA_DIR


def _load_schema(filename: str) -> dict[str, Any]:
    path = _schema_dir() / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_job_schema = None
_job_status_schema = None


def validate_job(payload: dict[str, Any]) -> list[str]:
    """Returns a list of validation error strings; empty if valid."""
    global _job_schema
    if _job_schema is None:
        _job_schema = _load_schema("job.schema.json")
    validator = jsonschema.Draft7Validator(_job_schema)
    return [e.message for e in validator.iter_errors(payload)]


def validate_job_status(payload: dict[str, Any]) -> list[str]:
    global _job_status_schema
    if _job_status_schema is None:
        _job_status_schema = _load_schema("job_status.schema.json")
    validator = jsonschema.Draft7Validator(_job_status_schema)
    return [e.message for e in validator.iter_errors(payload)]