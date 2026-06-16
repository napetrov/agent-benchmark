"""Tests for model × harness evaluation cells (ADR Phase B, §2.2)."""

from __future__ import annotations

import pytest

from agent_benchmarks.eval.cells import (
    Cell,
    CrossCellDeltaError,
    group_by_cell,
    is_known_harness,
    safe_delta,
    same_cell,
)


def test_cell_key_is_stable_and_distinguishing():
    a = Cell("gpt-4o", "single-shot")
    b = Cell("gpt-4o", "single-shot")
    c = Cell("gpt-4o", "agent")
    assert a.key == b.key
    assert a.key != c.key
    assert a == b and a != c


def test_cell_from_row_defaults_plugin_set_to_none():
    cell = Cell.from_row({"model": "m", "harness": "agent"})
    assert cell.plugin_set == "none"
    assert cell.key == "m|agent|none"


def test_is_known_harness():
    assert is_known_harness("single-shot")
    assert is_known_harness("agent")
    assert is_known_harness("terminal-bench")
    assert is_known_harness("terminal-bench:terminus")  # concrete instance
    assert not is_known_harness("made-up-harness")


def test_same_cell_accepts_rows_and_cells():
    r1 = {"model": "m", "harness": "agent", "plugin_set": "none"}
    r2 = {"model": "m", "harness": "agent"}  # plugin_set defaulted
    assert same_cell(r1, r2)
    assert same_cell(Cell.from_row(r1), r2)
    assert not same_cell(r1, {"model": "m", "harness": "single-shot"})


def test_safe_delta_within_cell():
    treated = {"model": "m", "harness": "agent"}
    baseline = {"model": "m", "harness": "agent"}
    assert safe_delta(treated, baseline, 4.2, 3.8) == 0.4
    assert safe_delta(treated, baseline, None, 3.8) is None  # missing score


def test_safe_delta_refuses_across_models():
    treated = {"model": "model-b", "harness": "agent"}
    baseline = {"model": "model-a", "harness": "agent"}
    with pytest.raises(CrossCellDeltaError):
        safe_delta(treated, baseline, 4.2, 3.8)


def test_safe_delta_refuses_across_harnesses():
    treated = {"model": "m", "harness": "agent"}
    baseline = {"model": "m", "harness": "single-shot"}
    with pytest.raises(CrossCellDeltaError):
        safe_delta(treated, baseline, 4.2, 3.8)


def test_safe_delta_refuses_across_plugin_sets():
    treated = {"model": "m", "harness": "agent", "plugin_set": "caveman-terse"}
    baseline = {"model": "m", "harness": "agent", "plugin_set": "none"}
    with pytest.raises(CrossCellDeltaError):
        safe_delta(treated, baseline, 4.2, 3.8)


def test_group_by_cell():
    rows = [
        {"model": "a", "harness": "single-shot"},
        {"model": "a", "harness": "single-shot"},
        {"model": "a", "harness": "agent"},
        {"model": "b", "harness": "agent"},
    ]
    grouped = group_by_cell(rows)
    assert set(grouped.keys()) == {
        "a|single-shot|none",
        "a|agent|none",
        "b|agent|none",
    }
    assert len(grouped["a|single-shot|none"]) == 2
