import numpy as np
import pandas as pd
import pytest

from app.pipeline.validation_gates import (
    DriftGate,
    GateResult,
    MaxNullRateGate,
    SchemaConformanceGate,
    all_passed,
    run_gates,
)


# ---------- MaxNullRateGate ----------

def test_max_null_rate_passes_under_threshold():
    df = pd.DataFrame({"a": [1, 2, None, 4], "b": [1, 2, 3, 4]})
    gate = MaxNullRateGate(threshold=0.5)
    result = gate.check(df)
    assert result.passed
    assert result.details["null_rates"]["a"] == 0.25


def test_max_null_rate_rejects_over_threshold():
    df = pd.DataFrame({"a": [None, None, None, 4], "b": [1, 2, 3, 4]})
    gate = MaxNullRateGate(threshold=0.5)
    result = gate.check(df)
    assert not result.passed
    assert result.reason == "null_rate_exceeded"
    assert "a" in result.details["violations"]
    assert "b" not in result.details["violations"]


def test_max_null_rate_rejects_missing_configured_column():
    df = pd.DataFrame({"a": [1, 2, 3]})
    gate = MaxNullRateGate(threshold=0.5, columns=["a", "nonexistent"])
    result = gate.check(df)
    assert not result.passed
    assert result.reason == "configured_column_missing"


def test_max_null_rate_rejects_empty_dataset():
    df = pd.DataFrame({"a": []})
    gate = MaxNullRateGate(threshold=0.5)
    result = gate.check(df)
    assert not result.passed
    assert result.reason == "empty_dataset"


def test_max_null_rate_invalid_threshold_raises_at_construction():
    with pytest.raises(ValueError):
        MaxNullRateGate(threshold=1.5)


# ---------- SchemaConformanceGate ----------

def test_schema_conformance_passes_on_match():
    df = pd.DataFrame({"age": [1, 2], "income": [1.0, 2.0]})
    gate = SchemaConformanceGate(reference_schema={"age": "i", "income": "f"})
    result = gate.check(df)
    assert result.passed


def test_schema_conformance_rejects_missing_column():
    df = pd.DataFrame({"age": [1, 2]})
    gate = SchemaConformanceGate(reference_schema={"age": "i", "income": "f"})
    result = gate.check(df)
    assert not result.passed
    assert result.details["missing_columns"] == ["income"]


def test_schema_conformance_rejects_extra_column():
    df = pd.DataFrame({"age": [1, 2], "extra": [1, 2]})
    gate = SchemaConformanceGate(reference_schema={"age": "i"})
    result = gate.check(df)
    assert not result.passed
    assert result.details["extra_columns"] == ["extra"]


def test_schema_conformance_rejects_dtype_mismatch():
    df = pd.DataFrame({"age": ["a", "b"]})  # object, not int
    gate = SchemaConformanceGate(reference_schema={"age": "i"})
    result = gate.check(df)
    assert not result.passed
    assert "age" in result.details["dtype_mismatches"]


def test_schema_conformance_rejects_empty_reference_schema():
    with pytest.raises(ValueError):
        SchemaConformanceGate(reference_schema={})


# ---------- DriftGate ----------

def test_drift_gate_requires_reference_df():
    with pytest.raises(ValueError):
        DriftGate(reference_df=pd.DataFrame())


def test_drift_gate_passes_on_identical_distribution():
    rng = np.random.default_rng(42)
    ref = pd.DataFrame({"x": rng.normal(0, 1, 1000)})
    cur = pd.DataFrame({"x": rng.normal(0, 1, 1000)})
    gate = DriftGate(reference_df=ref, psi_threshold=0.2)
    result = gate.check(cur)
    assert result.passed


def test_drift_gate_rejects_on_shifted_distribution():
    rng = np.random.default_rng(42)
    ref = pd.DataFrame({"x": rng.normal(0, 1, 1000)})
    cur = pd.DataFrame({"x": rng.normal(5, 1, 1000)})  # large mean shift
    gate = DriftGate(reference_df=ref, psi_threshold=0.2)
    result = gate.check(cur)
    assert not result.passed
    assert result.reason == "drift_detected"
    assert "x" in result.details["violations"]


def test_drift_gate_no_comparable_columns_rejects():
    ref = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    cur = pd.DataFrame({"y": [1.0, 2.0, 3.0]})
    gate = DriftGate(reference_df=ref)
    result = gate.check(cur)
    assert not result.passed
    assert result.reason == "no_comparable_numeric_columns"


# ---------- fail-closed wrapper ----------

class _BrokenGate(MaxNullRateGate):
    def check(self, df):
        raise RuntimeError("boom")


def test_safe_check_fails_closed_on_exception():
    gate = _BrokenGate(threshold=0.5)
    result = gate.safe_check(pd.DataFrame({"a": [1]}))
    assert not result.passed
    assert result.reason == "gate_evaluation_error"
    assert "boom" in result.details["error"]


# ---------- run_gates / all_passed ----------

def test_run_gates_runs_all_gates_even_after_a_failure():
    df = pd.DataFrame({"a": [None, None, 1]})
    gates = [MaxNullRateGate(threshold=0.1), SchemaConformanceGate(reference_schema={"a": "f"})]
    results = run_gates(df, gates)
    assert len(results) == 2
    assert not all_passed(results)


def test_all_passed_true_when_every_gate_passes():
    results = [GateResult(gate_name="g1", passed=True), GateResult(gate_name="g2", passed=True)]
    assert all_passed(results)