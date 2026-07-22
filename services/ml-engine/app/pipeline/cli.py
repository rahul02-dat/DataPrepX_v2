"""
CLI entrypoints for Phase 2: run gate checks against a dataset and log lineage, and replay a
prior run's gate step to verify byte-identical reproducibility (planner Phase 2 acceptance
criterion).

Usage:
    python -m app.pipeline.cli gate-check --run-id <uuid> --dataset <path.csv> \
        --config <gates.yaml> [--reference <reference.csv>]

    python -m app.pipeline.cli replay --run-id <uuid>

`replay` re-reads the dataset from the `datasets.storage_uri` path recorded in Postgres by
gateway-go. In the containerized deployment this requires ml-engine-py to have read access to
the same upload directory gateway-go writes to — see the docker-compose.yml volume mount shipped
alongside this code. Without that mount, replay fails explicitly with a message saying so, not a
silent false pass.
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd
import yaml

from .db import get_connection
from .lineage import (
    LineageContext,
    fetch_dataset_storage_uri,
    fetch_gate_step,
    hash_dataframe,
    record_gate_step,
)
from .validation_gates import DriftGate, MaxNullRateGate, SchemaConformanceGate, run_gates


def _build_gates(config: dict, reference_df: pd.DataFrame | None) -> list:
    gates = []
    if "max_null_rate" in config:
        gates.append(
            MaxNullRateGate(
                threshold=config["max_null_rate"]["threshold"],
                columns=config["max_null_rate"].get("columns"),
            )
        )
    if "schema_conformance" in config:
        gates.append(SchemaConformanceGate(reference_schema=config["schema_conformance"]["reference_schema"]))
    if "drift" in config:
        if reference_df is None:
            raise ValueError(
                "drift gate is configured but no --reference dataset was supplied. Per ADR-0004, "
                "the drift reference distribution is always user-supplied — there is no "
                "first-run-baseline fallback."
            )
        gates.append(
            DriftGate(
                reference_df=reference_df,
                psi_threshold=config["drift"].get("psi_threshold", 0.2),
                columns=config["drift"].get("columns"),
            )
        )
    return gates


def cmd_gate_check(args: argparse.Namespace) -> int:
    df = pd.read_csv(args.dataset)
    reference_df = pd.read_csv(args.reference) if args.reference else None

    with open(args.config) as f:
        config = yaml.safe_load(f)

    gates = _build_gates(config, reference_df)
    results = run_gates(df, gates)

    dataset_hash = hash_dataframe(df)
    ctx = LineageContext(run_id=args.run_id, dataset_content_hash=dataset_hash, config=config)

    with get_connection() as conn:
        step_id = record_gate_step(conn, ctx, results)

    passed = all(r.passed for r in results)
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "step_id": step_id,
                "passed": passed,
                "lineage_hash": ctx.lineage_hash(),
                "gate_results": [r.to_dict() for r in results],
            },
            indent=2,
        )
    )
    return 0 if passed else 1


def cmd_replay(args: argparse.Namespace) -> int:
    with get_connection() as conn:
        step = fetch_gate_step(conn, args.run_id)
        storage_uri = fetch_dataset_storage_uri(conn, args.run_id)

    try:
        df = pd.read_csv(storage_uri)
    except FileNotFoundError:
        print(
            json.dumps(
                {
                    "error": (
                        f"dataset file not found at {storage_uri} from this container. "
                        "ml-engine-py needs a shared volume mount to gateway-go's upload "
                        "directory for replay to work — see docker-compose.yml."
                    )
                }
            )
        )
        return 1

    recomputed_hash = hash_dataframe(df)
    original_input_hash = step["input_hash"]
    original_output_hash = step["output_hash"]
    match = recomputed_hash == original_input_hash == original_output_hash

    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "original_input_hash": original_input_hash,
                "original_output_hash": original_output_hash,
                "recomputed_hash": recomputed_hash,
                "byte_identical": match,
            },
            indent=2,
        )
    )
    return 0 if match else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="DataPrepX v2 — Phase 2 lineage CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    gc = sub.add_parser("gate-check", help="Run validation gates against a dataset and log lineage")
    gc.add_argument("--run-id", required=True)
    gc.add_argument("--dataset", required=True)
    gc.add_argument("--config", required=True)
    gc.add_argument("--reference", required=False)
    gc.set_defaults(func=cmd_gate_check)

    rp = sub.add_parser("replay", help="Replay a run's gate step and verify output hash equality")
    rp.add_argument("--run-id", required=True)
    rp.set_defaults(func=cmd_replay)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())