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


def _uses_dpnp(tree):
    """True if the solution actually imports dpnp (not just in a comment)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dpnp":
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "dpnp":
                return True
    return False


def test_files_exist():
    assert SOLUTION.exists(), f"{SOLUTION} not found"
    assert REFERENCE.exists(), f"{REFERENCE} not found"


def test_solution_imports_dpnp():
    tree = ast.parse(SOLUTION.read_text(errors="replace"), filename=str(SOLUTION))
    assert _uses_dpnp(tree), (
        "solution.py must import dpnp at the top level; "
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
