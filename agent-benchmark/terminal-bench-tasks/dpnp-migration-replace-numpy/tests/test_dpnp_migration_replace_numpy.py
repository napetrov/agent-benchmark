#!/usr/bin/env python3
"""Verifier for dpnp-migration-replace-numpy."""
import ast
import re
import subprocess
from pathlib import Path

SOLUTION = Path("/app/solution.py")
REFERENCE = Path("/app/reference.py")
TIMEOUT_SEC = 60.0
# dpnp on CPU uses float64 via oneMKL; rel error vs NumPy is at ULP level (~1e-15).
# 1e-9 is intentionally generous to tolerate any future backend differences.
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


def _parse_stats(text):
    """Parse mean, std, min, max from output."""
    pattern = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
    mean_m = re.search(rf"mean={pattern}", text)
    std_m = re.search(rf"std={pattern}", text)
    min_m = re.search(rf"min={pattern}", text)
    max_m = re.search(rf"max={pattern}", text)

    assert mean_m, f"no mean=<value> found in {text!r}"
    assert std_m, f"no std=<value> found in {text!r}"
    assert min_m, f"no min=<value> found in {text!r}"
    assert max_m, f"no max=<value> found in {text!r}"

    return {
        "mean": float(mean_m.group(1)),
        "std": float(std_m.group(1)),
        "min": float(min_m.group(1)),
        "max": float(max_m.group(1)),
    }


def _uses_dpnp_calls(tree):
    """True if solution uses dpnp API calls (not just imports it)."""
    module_aliases: set[str] = set()
    direct_funcs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dpnp":
                    module_aliases.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "dpnp":
            for alias in node.names:
                direct_funcs.add(alias.asname or alias.name)

    if not module_aliases and not direct_funcs:
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
                and func.value.id in module_aliases
            ):
                found.add(func.attr)
            elif isinstance(func, ast.Name) and func.id in direct_funcs & DPNP_APIS:
                found.add(func.id)
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
    ref_stats = _parse_stats(_run(REFERENCE))
    sol_stats = _parse_stats(_run(SOLUTION))

    # Verify each metric independently
    for metric in ["mean", "std", "min", "max", "hist_sig"]:
        ref_val = ref_stats[metric]
        sol_val = sol_stats[metric]
        denom = max(abs(ref_val), 1e-15)
        rel_err = abs(sol_val - ref_val) / denom
        assert rel_err <= REL_TOL, (
            f"{metric}: solution {sol_val:.9e} differs from reference {ref_val:.9e} "
            f"(relative error {rel_err:.2e} > {REL_TOL})"
        )
