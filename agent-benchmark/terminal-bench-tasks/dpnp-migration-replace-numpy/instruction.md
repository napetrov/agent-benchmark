# Migrate a NumPy preprocessing pipeline to dpnp

You are given `/app/reference.py`, a self-contained NumPy-based data
preprocessing pipeline that generates a deterministic synthetic dataset, applies
element-wise math operations, computes reduction statistics, and prints a
validation signature.

Create `/app/solution.py` that reproduces the **same** pipeline but accelerated
with **dpnp** (Intel's data-parallel NumPy extension):

1. Replace `import numpy as np` with `import dpnp as np` for the hot-path
   computations.
2. Preserve the same deterministic results: generate data with
   `np.arange(1_000_000, dtype=np.float64)`, apply `np.sin(x) + np.cos(x)`,
   compute `mean`, `std`, `min`, and `max` across the full array.
3. Print a line containing `VALID` and `sig=<value>` where the signature is:
   `mean + std * 1e4 + min * 1e8 + max * 1e12` (rounded to 6 decimal places).
4. For any operation that raises `NotImplementedError` in dpnp, fall back to
   NumPy using the recommended `asnumpy()` conversion pattern.

Requirements:

- The solution must actually `import dpnp` and use it for at least `arange`,
  `sin`, `cos`, `mean`, and `std`.
- Results must match the NumPy reference within `1e-9` relative tolerance.
- Do **not** import dpnp inside exception handlers only — the happy path must
  use dpnp.

Run the reference and solution with:

```bash
python3 /app/reference.py
python3 /app/solution.py
```
