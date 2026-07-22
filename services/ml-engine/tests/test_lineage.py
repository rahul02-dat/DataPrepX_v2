import os

import pandas as pd

from app.pipeline.lineage import (
    LineageContext,
    get_git_sha,
    hash_config,
    hash_dataframe,
)


def test_hash_dataframe_deterministic_for_identical_content():
    df1 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    df2 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    assert hash_dataframe(df1) == hash_dataframe(df2)


def test_hash_dataframe_ignores_column_order():
    df1 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    df2 = pd.DataFrame({"b": [3, 4], "a": [1, 2]})
    assert hash_dataframe(df1) == hash_dataframe(df2)


def test_hash_dataframe_differs_on_content_change():
    df1 = pd.DataFrame({"a": [1, 2]})
    df2 = pd.DataFrame({"a": [1, 3]})
    assert hash_dataframe(df1) != hash_dataframe(df2)


def test_hash_config_deterministic_regardless_of_key_order():
    c1 = {"threshold": 0.3, "columns": ["a", "b"]}
    c2 = {"columns": ["a", "b"], "threshold": 0.3}
    assert hash_config(c1) == hash_config(c2)


def test_hash_config_differs_on_value_change():
    assert hash_config({"threshold": 0.3}) != hash_config({"threshold": 0.4})


def test_get_git_sha_falls_back_to_sentinel_when_unset(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    assert get_git_sha() == "unknown-git-sha"


def test_get_git_sha_reads_env_var(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc123")
    assert get_git_sha() == "abc123"


def test_lineage_context_hash_is_deterministic(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "fixed-sha")
    ctx1 = LineageContext(run_id="r1", dataset_content_hash="d1", config={"threshold": 0.3})
    ctx2 = LineageContext(run_id="r1", dataset_content_hash="d1", config={"threshold": 0.3})
    assert ctx1.lineage_hash() == ctx2.lineage_hash()


def test_lineage_context_hash_changes_with_dataset(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "fixed-sha")
    ctx1 = LineageContext(run_id="r1", dataset_content_hash="d1", config={"threshold": 0.3})
    ctx2 = LineageContext(run_id="r1", dataset_content_hash="d2", config={"threshold": 0.3})
    assert ctx1.lineage_hash() != ctx2.lineage_hash()


def test_lineage_context_hash_changes_with_config():
    ctx1 = LineageContext(run_id="r1", dataset_content_hash="d1", config={"threshold": 0.3})
    ctx2 = LineageContext(run_id="r1", dataset_content_hash="d1", config={"threshold": 0.4})
    assert ctx1.lineage_hash() != ctx2.lineage_hash()


def test_lineage_context_hash_independent_of_run_id():
    # run_id is the Postgres surrogate key, deliberately NOT part of the content fingerprint —
    # two different runs against identical dataset+config+code should get the same lineage hash.
    ctx1 = LineageContext(run_id="r1", dataset_content_hash="d1", config={"threshold": 0.3})
    ctx2 = LineageContext(run_id="r2", dataset_content_hash="d1", config={"threshold": 0.3})
    assert ctx1.lineage_hash() == ctx2.lineage_hash()