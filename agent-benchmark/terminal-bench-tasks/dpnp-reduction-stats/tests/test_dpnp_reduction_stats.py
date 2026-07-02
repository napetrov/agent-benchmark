#!/usr/bin/env python3
"""Verifier for dpnp-reduction-stats."""
import ast
import re
import subprocess
import sys
from pathlib import Path

SOLUTION = Path("/app/solution.py")
REFERENCE = Path("/app/reference.py")
TIMEOUT_SEC = 60.0
REL_TOL = 1e-7


def _run(script):
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=TIMEOUT_SEC
    )
    assert result.returncode == 0, (
        f"{script} exit={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "VALID" in result.stdout, f"expected VALID in stdout, got {result.stdout!r}"
    return result.stdout


def _sig(text):
    m = re.search(r"sig=([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", text)
    assert m, f"no sig=<value> found in {text!r}"
    return float(m.group(1))


def _uses_dpnp_reductions(tree):
    """True if solution imports dpnp and uses sum/mean/std with axis kwarg."""
    has_dpnp = False
    reduction_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dpnp":
                    has_dpnp = True
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "dpnp":
            has_dpnp = True
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in ("sum", "mean", "std"):
                reduction_calls.add(func.attr)
            if isinstance(func, ast.Name) and func.id in ("sum", "mean", "std"):
                reduction_calls.add(func.id)
    return has_dpnp and len(reduction_calls) >= 2


def test_files_exist():
    assert SOLUTION.exists(), f"{SOLUTION} not found"
    assert REFERENCE.exists(), f"{REFERENCE} not found"


def test_solution_uses_dpnp_reductions():
    tree = ast.parse(SOLUTION.read_text(errors="replace"), filename=str(SOLUTION))
    assert _uses_dpnp_reductions(tree), (
        "solution.py must import dpnp and use at least sum/mean/std reduction functions"
    )


def test_solution_uses_axis_parameter():
    source = SOLUTION.read_text(errors="replace")
    assert "axis=0" in source, (
        "solution.py must use axis=0 for per-column reductions"
    )


def test_signature_matches_reference():
    ref_sig = _sig(_run(REFERENCE))
    sol_sig = _sig(_run(SOLUTION))
    denom = max(abs(ref_sig), 1e-15)
    rel_err = abs(sol_sig - ref_sig) / denom
    assert rel_err <= REL_TOL, (
        f"dpnp sig {sol_sig} differs from reference {ref_sig} "
        f"(relative error {rel_err:.2e} > {REL_TOL})"
    )
