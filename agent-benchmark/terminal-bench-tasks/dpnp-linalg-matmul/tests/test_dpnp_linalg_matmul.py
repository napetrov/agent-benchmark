#!/usr/bin/env python3
"""Verifier for dpnp-linalg-matmul."""
import ast
import re
import subprocess
import sys
from pathlib import Path

SOLUTION = Path("/app/solution.py")
REFERENCE = Path("/app/reference.py")
TIMEOUT_SEC = 60.0
REL_TOL = 1e-6
N_TEST = "256"


def _run(script, *args):
    cmd = [sys.executable, str(script), *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SEC)
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


def _uses_dpnp_matmul(tree):
    """True if the AST contains dpnp.matmul/matmul call or @ on dpnp arrays and imports dpnp."""
    has_dpnp_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dpnp":
                    has_dpnp_import = True
        if isinstance(node, ast.ImportFrom) and node.module == "dpnp":
            has_dpnp_import = True
    # Also look for matmul call or @ operator usage
    has_matmul = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "matmul":
                has_matmul = True
            if isinstance(func, ast.Name) and func.id == "matmul":
                has_matmul = True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult):
            has_matmul = True
    return has_dpnp_import and has_matmul


def test_files_exist():
    assert SOLUTION.exists(), f"{SOLUTION} not found"
    assert REFERENCE.exists(), f"{REFERENCE} not found"


def test_solution_uses_dpnp_matmul():
    tree = ast.parse(SOLUTION.read_text(errors="replace"), filename=str(SOLUTION))
    assert _uses_dpnp_matmul(tree), (
        "solution.py must import dpnp and use dpnp.matmul() or the @ operator on dpnp arrays"
    )


def test_signature_matches_reference():
    ref_sig = _sig(_run(REFERENCE, N_TEST))
    sol_sig = _sig(_run(SOLUTION, N_TEST))
    denom = max(abs(ref_sig), 1e-15)
    rel_err = abs(sol_sig - ref_sig) / denom
    assert rel_err <= REL_TOL, (
        f"dpnp sig {sol_sig} differs from reference {ref_sig} "
        f"(relative error {rel_err:.2e} > {REL_TOL})"
    )


def test_rejects_invalid_size():
    result = subprocess.run(
        [sys.executable, str(SOLUTION), "0"],
        capture_output=True, text=True, timeout=TIMEOUT_SEC
    )
    assert result.returncode != 0, "solution must exit non-zero for N=0"
