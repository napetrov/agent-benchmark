---
name: dpnp-io
description: File I/O patterns for dpnp arrays (NumPy conversion round-trips, HDF5, Zarr, CSV, chunking for large datasets)
---

## Quick Start: Loading and Saving dpnp Arrays

dpnp has no native file I/O. All file operations use NumPy conversion:

```python
import numpy
import dpnp

# Load .npy file
arr = dpnp.array(numpy.load('data.npy'))

# Compute with dpnp
result = dpnp.fft.fft2(arr) + dpnp.mean(arr)

# Save result
numpy.save('output.npy', dpnp.asnumpy(result))
```

Pattern: NumPy load → `dpnp.array()` → compute → `dpnp.asnumpy()` → NumPy save.

## Why dpnp Has No Native I/O

dpnp focuses on compute acceleration, not file formats. The conversion overhead (host ↔ device transfer) is typically small compared to compute time. For compute-heavy workloads (FFT, linear algebra, large element-wise ops), the pattern works well. For I/O-bound tasks (reading many small files, simple aggregations), dpnp may not accelerate overall runtime.

## NumPy .npy and .npz Files

**Single array (.npy)**:
```python
import numpy
import dpnp

# Load
data = dpnp.array(numpy.load('input.npy'))

# Save
numpy.save('output.npy', dpnp.asnumpy(data))
```

**Multiple arrays (.npz)**:
```python
import numpy
import dpnp

# Load — use with block to ensure the NpzFile is closed after reading
with numpy.load('data.npz') as npz:
    x = dpnp.array(npz['x'])
    y = dpnp.array(npz['y'])

# Save
numpy.savez('output.npz', x=dpnp.asnumpy(x), y=dpnp.asnumpy(y))
```

**Memory consideration**: Conversion creates a temporary host copy. For a 4GB array, you need 4GB extra RAM during `dpnp.array()` and `dpnp.asnumpy()` calls.

**When to use**: Datasets under 1GB, single-file storage, fast prototyping.

## Chunked Loading for Large Files

For files larger than available RAM, load and process in chunks:

```python
import numpy
import dpnp

# Load 2GB file in 200MB chunks
chunk_size = 25_000_000  # 200MB of float64 (8 bytes each)
data = numpy.load('large.npy', mmap_mode='r')  # Memory-mapped, no full load
result = []

# Pre-allocate output array to avoid accumulating chunks in memory
final = numpy.empty(len(data), dtype=numpy.float64)

for i in range(0, len(data), chunk_size):
    chunk_np = data[i:i+chunk_size]
    chunk_dpnp = dpnp.array(chunk_np)
    
    # Your dpnp operations
    processed = dpnp.sqrt(chunk_dpnp) * 2.0
    
    # Write directly into output slice — no in-memory accumulation
    final[i:i+len(chunk_np)] = dpnp.asnumpy(processed)

numpy.save('output.npy', final)
```

**Rule of thumb**: Chunk size = 10-20% of available RAM.

## HDF5 Files via h5py

h5py works only with NumPy arrays. Use the same conversion pattern:

```python
import h5py
import dpnp

# Read full dataset
with h5py.File('data.h5', 'r') as f:
    arr = dpnp.array(f['dataset'][:])

# Write dataset
with h5py.File('output.h5', 'w') as f:
    f.create_dataset('result', data=dpnp.asnumpy(arr))
```

**Chunked reading for large HDF5 datasets**:
```python
with h5py.File('large.h5', 'r') as f:
    dset = f['dataset']  # Shape: (10_000_000,)
    chunk_size = 1_000_000
    result = []
    
    combined = numpy.empty(dset.shape[0], dtype=numpy.complex128)
    for i in range(0, dset.shape[0], chunk_size):
        chunk_np = dset[i:i+chunk_size]
        chunk_dpnp = dpnp.array(chunk_np)
        processed = dpnp.fft.fft(chunk_dpnp)
        # Write directly into pre-allocated slice
        combined[i:i+len(chunk_np)] = dpnp.asnumpy(processed)
```

**Incremental writes** (results too large for memory):
```python
with h5py.File('output.h5', 'w') as f:
    total_size = 50_000_000
    chunk_size = 5_000_000
    dset = f.create_dataset('result', shape=(total_size,), dtype='float64')
    
    for i in range(0, total_size, chunk_size):
        # Compute chunk with dpnp
        chunk_result = compute_on_dpnp(i, chunk_size)  # Returns dpnp array
        dset[i:i+chunk_size] = dpnp.asnumpy(chunk_result)
```

**When to use**: Multi-dataset files, hierarchical structure, datasets over 1GB.

## Zarr for Cloud and Large Arrays

Zarr provides chunked, compressed storage and works with S3/GCS via fsspec:

```python
import zarr
import dpnp

# Read
z = zarr.open('data.zarr', mode='r')
arr = dpnp.array(z['dataset'][:])  # Full load

# Write
z = zarr.open('output.zarr', mode='w', shape=(1_000_000,), chunks=(100_000,), dtype='float64')
z[:] = dpnp.asnumpy(arr)
```

**Chunked processing**:
```python
z = zarr.open('data.zarr', mode='r')
dset = z['dataset']
chunk_size = 100_000
combined = numpy.empty(dset.shape[0], dtype=numpy.float64)

for i in range(0, dset.shape[0], chunk_size):
    chunk = dpnp.array(dset[i:i+chunk_size])
    processed = dpnp.log(chunk + 1)
    # Write directly into output slice
    combined[i:i+chunk_size] = dpnp.asnumpy(processed)
```

**Incremental writes**:
```python
z = zarr.open('output.zarr', mode='w', shape=(10_000_000,), chunks=(500_000,), dtype='float32')
for i in range(0, 10_000_000, 500_000):
    chunk = compute_dpnp_chunk(i)
    z[i:i+500_000] = dpnp.asnumpy(chunk)
```

**When to use**: Datasets over 10GB, cloud storage, parallel workflows, compression needed.

## CSV and Text Files

**CSV with pandas**:
```python
import numpy
import pandas as pd
import dpnp

# Load
df = pd.read_csv('data.csv')
arr = dpnp.array(df.values)  # Or: df['column'].values for single column

# Save
numpy.savetxt('output.csv', dpnp.asnumpy(arr), delimiter=',')
# Or: pd.DataFrame(dpnp.asnumpy(arr)).to_csv('output.csv', index=False)
```

**Numeric CSV with dpnp.loadtxt**:
```python
import dpnp

arr = dpnp.loadtxt('data.csv', delimiter=',')  # returns dpnp array directly
```

*Note: `dpnp.loadtxt` delegates to `numpy.loadtxt` internally. Structured dtypes are not supported.*

**Performance note**: CSV parsing is CPU-bound and slow. dpnp conversion overhead is negligible compared to parsing time. For large CSV files (>100MB), consider converting to .npy or HDF5 for faster repeated access.

**When to use**: Small datasets (<100MB), human-readable exports, Excel compatibility.

## Performance Guidelines

**When does conversion overhead matter?**
- If I/O time > compute time, dpnp provides no benefit
- If compute time < 10× I/O time, profile before assuming speedup

**Good pattern** (minimize conversions) — *for small files only*:
```python
# Load once (works well if total memory footprint fits in device RAM)
# For 10 small files (<100MB each): this is efficient
# For large files: this loads everything into memory at once — use chunked processing instead
data = [dpnp.array(numpy.load(f'file_{i}.npy')) for i in range(10)]

# Compute many operations
results = [dpnp.fft.fft2(dpnp.matmul(d, d.T)) for d in data]

# Save once
for i, r in enumerate(results):
    numpy.save(f'out_{i}.npy', dpnp.asnumpy(r))
```

**For large files** (chunked processing):
```python
# Process one file at a time to avoid memory overflow
for i in range(10):
    data = dpnp.array(numpy.load(f'file_{i}.npy'))
    result = dpnp.fft.fft2(dpnp.matmul(data, data.T))
    numpy.save(f'out_{i}.npy', dpnp.asnumpy(result))
    del data, result  # Free memory before next iteration
```

**Bad pattern** (conversion in loop):
```python
for i in range(1000):
    data = dpnp.array(numpy.load(f'file_{i}.npy'))  # 1000 conversions!
    result = dpnp.sum(data)  # Trivial compute, not worth conversion
    numpy.save(f'out_{i}.npy', dpnp.asnumpy(result))
```

**Memory vs speed tradeoff**: Chunked processing reduces memory usage but adds conversion overhead per chunk. For a 10GB dataset:
- Full load: 1 conversion, 10GB RAM
- 10 chunks: 10 conversions, 1GB RAM

Choose based on available memory and whether compute time >> conversion time.

## Format Selection Guide

| File Size | Format | Reason |
|-----------|--------|--------|
| <100MB | .npy or CSV | Simple, fast, single-file |
| 100MB-1GB | .npy or .npz | Efficient binary, memory-mapped load |
| 1GB-10GB | HDF5 | Chunked access, multiple datasets |
| >10GB | Zarr | Cloud-friendly, compression, parallel access |

**Multiple datasets**: Use .npz (small), HDF5 (medium), or Zarr (large).
**Cloud storage**: Use Zarr with fsspec.
**Human-readable**: Use CSV (but convert to binary for performance).

## Summary

dpnp has no native binary file I/O (`.npy`, HDF5, Zarr). For those formats, all operations require NumPy conversion via `dpnp.array()` (load) and `dpnp.asnumpy()` (save). For CSV/text files, use `dpnp.loadtxt()` directly — it delegates to `numpy.loadtxt` internally and returns a dpnp array. This pattern works well when compute time dominates I/O time (typical for FFT, linear algebra, large element-wise ops). For large files, use chunked processing to avoid memory overflow. Minimize conversion frequency by batching operations between I/O calls. Choose file format based on dataset size: .npy for <1GB, HDF5 for 1-10GB, Zarr for >10GB or cloud storage. Note: if dpnp adds native I/O for other formats in the future, those functions will most likely use NumPy as a backend internally (as `dpnp.loadtxt` already does).
