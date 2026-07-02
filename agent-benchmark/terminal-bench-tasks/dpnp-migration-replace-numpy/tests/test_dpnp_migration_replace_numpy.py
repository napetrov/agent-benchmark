#!/usr/bin/env python3
"""Verifier for dpnp-migration-replace-numpy."""
import ast
import re
import subprocess
from pathlib import Path

SOLUTION = Path("/app/solution.py")
REFERENCE = Path("/app/reference.py")
TIMEOUT_SEC = 60.0
REL_TOL = 1e-9


def _run(script):
    result = subprocess.run(
        ["python3", str(script)], capture_output=True, text=True, timeout=TIMEOUT_SEC
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


def _uses_dpnp_calls(tree):
    """True if solution uses dpnp API calls (not just imports it)."""
    dpnp_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dpnp":
                    dpnp_names.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "dpnp":
            for alias in node.names:
                dpnp_names.add(alias.asname or alias.name)

    if not dpnp_names:
        return False

    DPNP_APIS = {"arange", "sin", "cos", "mean", "std", "min", "max", "asnumpy"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in DPNP_APIS
                and isinstance(func.value, ast.Name)
                and func.value.id in dpnp_names
            ):
                found.add(func.attr)
    return len(found) >= 2


def test_files_exist():
    assert SOLUTION.exists(), f"{SOLUTION} not found"
    assert REFERENCE.exists(), f"{REFERENCE} not found"


def test_solution_imports_dpnp():
    tree = ast.parse(SOLUTION.read_text(errors="replace"), filename=str(SOLUTION))
    assert _uses_dpnp_calls(tree), (
        "solution.py must import dpnp and use it for real computations (arange/sin/cos/mean/std); "
        "a plain NumPy solution does not satisfy the task"
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
