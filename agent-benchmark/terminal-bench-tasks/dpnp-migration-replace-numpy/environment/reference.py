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
    # Print each metric independently for verification
    print(f"VALID mean={mean_val:.9e} std={std_val:.9e} min={min_val:.9e} max={max_val:.9e}")


if __name__ == "__main__":
    run()
