"""
Validation gates — pluggable, fail-closed data quality checks that must pass before a dataset
reaches imputation/estimation (CLAUDE.md §5.3 / planner Phase 2).

Fail-closed means two things here:
1. A gate that raises during evaluation is treated as a rejection, not skipped and not silently
   passed through (`safe_check` catches and converts to a failing GateResult).
2. All configured gates run against a dataset regardless of earlier failures, so a rejected
   dataset still gets a complete structured report instead of an early-exit that hides other
   problems.

Rejection reasons are structured (GateResult.reason is a short machine-readable code,
GateResult.details is a dict of the actual numbers) per the planner's explicit requirement that
rejections not be a free-text log line.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class GateResult:
    gate_name: str
    passed: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


class ValidationGate(ABC):
    name: str

    @abstractmethod
    def check(self, df: pd.DataFrame) -> GateResult: ...

    def safe_check(self, df: pd.DataFrame) -> GateResult:
        try:
            return self.check(df)
        except Exception as exc:  # noqa: BLE001 - deliberate: any gate error must fail closed
            return GateResult(
                gate_name=self.name,
                passed=False,
                reason="gate_evaluation_error",
                details={"error": str(exc), "error_type": type(exc).__name__},
            )


class MaxNullRateGate(ValidationGate):
    """Rejects if any single column's null rate exceeds `threshold`. Checked per-column, not as
    a dataset-wide average, so one badly-missing column can't hide behind healthy ones."""

    name = "MaxNullRateGate"

    def __init__(self, threshold: float, columns: list[str] | None = None):
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0,1], got {threshold}")
        self.threshold = threshold
        self.columns = columns

    def check(self, df: pd.DataFrame) -> GateResult:
        cols = self.columns or list(df.columns)
        missing_cols = [c for c in cols if c not in df.columns]
        if missing_cols:
            return GateResult(
                gate_name=self.name,
                passed=False,
                reason="configured_column_missing",
                details={"missing_columns": missing_cols},
            )

        if len(df) == 0:
            return GateResult(gate_name=self.name, passed=False, reason="empty_dataset", details={})

        null_rates = {c: float(df[c].isna().mean()) for c in cols}
        violations = {c: r for c, r in null_rates.items() if r > self.threshold}

        return GateResult(
            gate_name=self.name,
            passed=len(violations) == 0,
            reason="null_rate_exceeded" if violations else None,
            details={"null_rates": null_rates, "threshold": self.threshold, "violations": violations},
        )


class SchemaConformanceGate(ValidationGate):
    """Rejects if the dataframe's column set or coarse dtypes don't match a reference schema.

    reference_schema format: {"column_name": "dtype_kind"} using pandas' coarse dtype kind codes
    ("i" int, "f" float, "O" object/string, "b" bool, "M" datetime64).
    """

    name = "SchemaConformanceGate"

    def __init__(self, reference_schema: dict[str, str]):
        if not reference_schema:
            raise ValueError("reference_schema must be non-empty")
        self.reference_schema = reference_schema

    def check(self, df: pd.DataFrame) -> GateResult:
        expected_cols = set(self.reference_schema.keys())
        actual_cols = set(df.columns)

        missing = sorted(expected_cols - actual_cols)
        extra = sorted(actual_cols - expected_cols)

        dtype_mismatches = {}
        for col in expected_cols & actual_cols:
            actual_kind = df[col].dtype.kind
            expected_kind = self.reference_schema[col]
            if actual_kind != expected_kind:
                dtype_mismatches[col] = {"expected": expected_kind, "actual": actual_kind}

        passed = not missing and not extra and not dtype_mismatches

        return GateResult(
            gate_name=self.name,
            passed=passed,
            reason=None if passed else "schema_mismatch",
            details={
                "missing_columns": missing,
                "extra_columns": extra,
                "dtype_mismatches": dtype_mismatches,
            },
        )


def _psi(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """Population Stability Index between two numeric series, using reference-derived
    quantile bin edges. Returns inf for degenerate cases (empty series) rather than raising,
    since DriftGate.check must produce a GateResult, not propagate an exception for an ordinary
    "not enough data" situation. Genuine coding errors still raise and get caught by
    safe_check's fail-closed wrapper."""
    ref = reference.dropna().astype(float)
    cur = current.dropna().astype(float)
    if len(ref) == 0 or len(cur) == 0:
        return float("inf")

    quantiles = [i / bins for i in range(bins + 1)]
    edges = sorted(set(ref.quantile(quantiles).tolist()))
    if len(edges) < 2:
        return 0.0 if cur.nunique() <= 1 and float(cur.iloc[0]) == float(ref.iloc[0]) else float("inf")

    edges[0], edges[-1] = -math.inf, math.inf

    ref_counts = pd.cut(ref, bins=edges, include_lowest=True).value_counts(sort=False)
    ref_props = (ref_counts / len(ref)).clip(lower=1e-6)
    cur_counts = pd.cut(cur, bins=edges, include_lowest=True).value_counts(sort=False)
    cur_props = (cur_counts / len(cur)).clip(lower=1e-6)

    ref_props, cur_props = ref_props.align(cur_props, fill_value=1e-6)
    psi = float(((cur_props - ref_props) * (cur_props / ref_props).apply(math.log)).sum())
    return psi


class DriftGate(ValidationGate):
    """Compares numeric columns against a user-supplied reference distribution using
    Population Stability Index (PSI).

    Per ADR-0004: the reference distribution is ALWAYS user-supplied. There is no
    first-run-becomes-baseline fallback in this implementation — the caller must construct this
    gate with a real reference_df or not configure a drift gate at all. Categorical/KS-test drift
    is not implemented in Phase 2 (PSI covers numeric columns only) — flagged as a scoping
    decision, not an oversight; revisit if a research need for categorical drift arises.
    """

    name = "DriftGate"

    def __init__(self, reference_df: pd.DataFrame, psi_threshold: float = 0.2, columns: list[str] | None = None):
        if reference_df is None or len(reference_df) == 0:
            raise ValueError("DriftGate requires a non-empty user-supplied reference_df (ADR-0004)")
        self.reference_df = reference_df
        self.psi_threshold = psi_threshold
        self.columns = columns

    def check(self, df: pd.DataFrame) -> GateResult:
        candidate_cols = self.columns or [
            c for c in df.columns
            if c in self.reference_df.columns and pd.api.types.is_numeric_dtype(df[c])
        ]

        if not candidate_cols:
            return GateResult(gate_name=self.name, passed=False, reason="no_comparable_numeric_columns", details={})

        psi_scores = {col: _psi(self.reference_df[col], df[col]) for col in candidate_cols}
        violations = {c: v for c, v in psi_scores.items() if v > self.psi_threshold}

        return GateResult(
            gate_name=self.name,
            passed=len(violations) == 0,
            reason="drift_detected" if violations else None,
            details={"psi_scores": psi_scores, "threshold": self.psi_threshold, "violations": violations},
        )


def run_gates(df: pd.DataFrame, gates: list[ValidationGate]) -> list[GateResult]:
    return [gate.safe_check(df) for gate in gates]


def all_passed(results: list[GateResult]) -> bool:
    return all(r.passed for r in results)