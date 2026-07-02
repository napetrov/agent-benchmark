#!/usr/bin/env python3
"""Verifier for dpnp-device-fallback."""
import ast
import re
import subprocess
import sys
from pathlib import Path

SOLUTION = Path("/app/solution.py")
REFERENCE = Path("/app/reference.py")
TIMEOUT_SEC = 60.0
REL_TOL = 1e-9


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


def _uses_dpctl(tree):
    """Return True if the solution imports dpctl."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("dpctl"):
                    return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("dpctl"):
            return True
    return False


def _has_gpu_attempt(tree: ast.AST) -> bool:
    """Return True if source attempts SyclDevice('gpu') inside a try block."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in ast.walk(node):
                if (
                    isinstance(stmt, ast.Call)
                    and getattr(stmt.func, "attr", getattr(stmt.func, "id", "")) == "SyclDevice"
                    and any(
                        isinstance(a, ast.Constant) and a.value == "gpu"
                        for a in stmt.args
                    )
                ):
                    return True
    return False


def test_files_exist():
    assert SOLUTION.exists(), f"{SOLUTION} not found"
    assert REFERENCE.exists(), f"{REFERENCE} not found"


def test_solution_uses_dpctl():
    tree = ast.parse(SOLUTION.read_text(errors="replace"), filename=str(SOLUTION))
    assert _uses_dpctl(tree), (
        "solution.py must import dpctl for device management"
    )


def test_solution_attempts_gpu_first():
    tree = ast.parse(SOLUTION.read_text(errors="replace"), filename=str(SOLUTION))
    assert _has_gpu_attempt(tree), (
        "solution.py must attempt GPU device selection before falling back to CPU"
    )


def test_solution_runs_without_gpu():
    """Must complete successfully even when no GPU is present."""
    out = _run(SOLUTION)
    assert "INFO device=" in out, f"expected 'INFO device=' line in stdout, got {out!r}"


def test_signature_matches_reference():
    ref_sig = _sig(_run(REFERENCE))
    sol_sig = _sig(_run(SOLUTION))
    denom = max(abs(ref_sig), 1e-15)
    rel_err = abs(sol_sig - ref_sig) / denom
    assert rel_err <= REL_TOL, (
        f"dpnp sig {sol_sig} differs from reference {ref_sig} "
        f"(relative error {rel_err:.2e} > {REL_TOL})"
    )
