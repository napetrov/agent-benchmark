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
    sig = mean_val + std_val * 1e4 + min_val * 1e8 + max_val * 1e12
    print(f"VALID reference sig={sig:.6f}")


if __name__ == "__main__":
    run()
