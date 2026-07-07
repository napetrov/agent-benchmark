"""NumPy reference pipeline for dpnp migration task.

Generates deterministic synthetic data, applies element-wise math, computes
reduction statistics, and prints a validation signature.
"""
import numpy as np


def run():
    x = np.arange(1_000_000, dtype=np.float64)
    y = np.sin(x) + np.cos(x)
    mean_val = float(np.mean(y))
    std_val = float(np.std(y))
    min_val = float(np.min(y))
    max_val = float(np.max(y))
    # Balanced formula: all components contribute measurably
    sig = abs(mean_val) * 1e12 + std_val * 1e11 + abs(min_val) * 1e10 + max_val * 1e9
    print(f"VALID reference sig={sig:.6f}")


if __name__ == "__main__":
    run()
