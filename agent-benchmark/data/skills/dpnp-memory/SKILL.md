---
name: dpnp-memory
description: Memory management, device control, and pre-allocation strategies for DPNP arrays — SYCL device inspection, avoiding memory leaks, chunking large workloads
---

# dpnp-memory

Memory management and device control for DPNP arrays. DPNP arrays live in SYCL unified shared memory (USM) device allocations, not CPU heap like NumPy. Memory persists until Python garbage collection runs. This skill covers device inspection, memory monitoring, pre-allocation patterns, and chunking strategies for large workloads.

```python
import dpnp

# Check where array lives
arr = dpnp.arange(1000)
print(arr.sycl_device)  # opencl:gpu:0, level_zero:gpu:0, opencl:cpu:0, etc.
print(arr.sycl_queue)   # Queue information

# Pre-allocate to avoid repeated allocation overhead
a = dpnp.arange(1000, dtype=dpnp.float64)
b = dpnp.arange(1000, dtype=dpnp.float64)
result = dpnp.empty(1000, dtype=dpnp.float64)
for i in range(100):
    dpnp.add(a, b, out=result)  # Reuses result buffer, no new allocation
```

## DPNP Memory Model

DPNP arrays are allocated in SYCL unified shared memory (USM) on the device (GPU or CPU). This contrasts with NumPy arrays, which live in CPU heap memory. Memory is not automatically freed when a dpnp array goes out of scope; it persists until Python's garbage collector reclaims it, though reclamation timing depends on object lifetime and allocator behavior. In long-running scripts or Jupyter notebooks, this can cause memory accumulation. DPNP selects a default device at import time: CPU fallback if no GPU is available, otherwise the first detected GPU. Use `dpctl.select_default_device()` to override. Device memory limits are typically 8-64 GB for discrete GPUs, unlimited for CPU. Allocation overhead is 10-100× higher than CPU malloc, so pre-allocation is critical for performance in loops.

## Checking Array Location

Every dpnp array has `array.sycl_device` and `array.sycl_queue` properties. Use these to verify which device holds the array. Check the default queue with `dpctl.get_current_queue()` and list available devices with `dpctl.get_devices()`. Device names follow the pattern `backend:device_type:index`, for example `opencl:gpu:0` for OpenCL GPU 0, `level_zero:gpu:0` for Level Zero GPU 0, or `opencl:cpu:0` for CPU fallback. Level Zero is the preferred backend for Intel GPUs (lower overhead than OpenCL). If multiple GPUs are present, arrays default to index 0 unless you create a custom queue.

```python
import dpnp
import dpctl

arr = dpnp.arange(1000)
print(arr.sycl_device)  # Example: opencl:gpu:0
print(arr.sycl_queue.device.name)  # Intel(R) UHD Graphics

# List all devices
for dev in dpctl.get_devices():
    print(dev)

# Force specific device
gpu = dpctl.SyclDevice("level_zero:gpu:0")
queue = dpctl.SyclQueue(gpu)
with dpctl.device_context(queue):
    arr_on_gpu = dpnp.arange(1000)
```

## Querying Memory Usage

DPNP has no built-in API for device memory stats. Use `dpctl.SyclQueue.get_device().max_mem_alloc_size` for the device's maximum single allocation size (typically 25-50% of total memory). For real-time memory usage on Intel GPUs, use `xpu-smi` (formerly `gpu_smi`): run `xpu-smi dump -m 1` for per-second updates. For OpenCL devices, use `clinfo` to query memory limits. For Level Zero, use `ze_info` (part of level-zero-tests package). Platform tools like `nvidia-smi` work for CUDA backend if dpnp is built with CUDA support. There is no equivalent to `torch.cuda.memory_summary()` in dpnp 0.21. To profile allocations, intercept SYCL allocation events with `SYCL_PI_TRACE=1` environment variable, but output is verbose.

```python
import dpctl

queue = dpctl.get_current_queue()
device = queue.device
print(f"Max allocation size: {device.max_mem_alloc_size / 1e9:.2f} GB")
print(f"Global memory size: {device.global_mem_size / 1e9:.2f} GB")
```

## Pre-allocation Strategies

Pre-allocation avoids repeated USM allocation overhead in loops. Pattern 1: allocate output buffer once, reuse via `out=` parameter. Pattern 2: use `dpnp.empty()` instead of `dpnp.zeros()` when initial values do not matter (saves initialization cost). Pattern 3: pre-allocate workspace arrays for in-place operations. Universal functions (ufuncs) like `add`, `multiply`, `sin` support the `out=` parameter. Performance gain is 2-5× for small array operations (< 1 MB) in tight loops (> 100 iterations). For large arrays (> 100 MB), allocation overhead is amortized and pre-allocation provides < 10% speedup.

```python
import dpnp

# Bad: allocates new array every iteration
a = dpnp.arange(10000)
b = dpnp.arange(10000)
for i in range(1000):
    result = dpnp.add(a, b)  # 1000 allocations

# Good: reuses result buffer
result = dpnp.empty(10000, dtype=dpnp.float64)
for i in range(1000):
    dpnp.add(a, b, out=result)  # 1 allocation

# Matrix multiplication with pre-allocated output
A = dpnp.random.rand(1000, 1000)
B = dpnp.random.rand(1000, 1000)
C = dpnp.empty((1000, 1000), dtype=dpnp.float64)
dpnp.matmul(A, B, out=C)
```

## Avoiding Memory Leaks and Transfers

DPNP-to-NumPy conversion triggers memory copy. Explicit conversions: `dpnp.asnumpy(arr)` (device to host), `dpnp.array(numpy_arr)` (host to device). Implicit conversions: calling NumPy functions on dpnp arrays, using Python operators on mixed dpnp/NumPy operands. Memory leak pattern: creating dpnp arrays in loop without reuse. Solution: factor array creation out of loop or use pre-allocation. The `del` statement does not immediately free device memory; it decrements the reference count, but memory persists until garbage collection runs. In Jupyter notebooks, force collection with `import gc; gc.collect()`. Memory leak symptom: script slows over time as device memory fills, eventually triggering fallback to CPU or out-of-memory error. Use `xpu-smi` to monitor memory usage while script runs. If memory usage climbs steadily, you have a leak.

```python
import dpnp
import numpy as np

# Bad: repeated allocation and copy in loop
for i in range(1000):
    arr = dpnp.arange(10000)  # Device allocation
    np_arr = dpnp.asnumpy(arr)  # Copy to host
    process(np_arr)

# Good: allocate once, reuse
arr = dpnp.arange(10000)
for i in range(1000):
    process(dpnp.asnumpy(arr))  # Still copies, but no repeated allocation

# Nudge garbage collection in notebooks (reclamation is not guaranteed immediate)
import gc
del large_array
gc.collect()  # May help reclaim device memory; timing depends on allocator
```

## Chunking Large Workloads

For datasets that exceed device memory, process in chunks that fit. Rule of thumb: chunk size should be 50-70% of device memory to leave room for intermediate results. Example: processing 100 GB dataset on 16 GB GPU requires chunks of 8-10 GB. Load chunk from disk, convert to dpnp, process, convert back to NumPy, save result, delete arrays, repeat. Explicitly delete arrays and call `gc.collect()` after each chunk to ensure memory is freed before next chunk. Profile first to identify bottleneck: if disk I/O dominates, chunking overhead is negligible; if compute dominates, chunking adds 10-20% overhead due to repeated allocation. For memory-bound workloads (network I/O, disk I/O), CPU fallback may be faster than GPU chunking. Use NumPy instead of dpnp when dataset is < 10,000 elements or device memory is exhausted and chunking overhead is prohibitive.

```python
import dpnp
import numpy as np
import gc

total_size = 100_000_000  # 100M elements
chunk_size = 10_000_000   # 10M elements per chunk (tune to device capacity)

for i in range(0, total_size, chunk_size):
    # Load chunk from disk (NumPy)
    chunk = np.load(f"data_chunk_{i}.npy")
    
    # Convert to dpnp and process
    arr = dpnp.array(chunk)
    result = dpnp.sum(arr ** 2)  # Example computation
    
    # Convert back and save
    np.save(f"result_{i}.npy", dpnp.asnumpy(result))
    
    # Free memory before next iteration (gc.collect may help, but timing is allocator-dependent)
    del arr, result, chunk
    gc.collect()
```

## Best Practices Summary

1. Check device placement with `array.sycl_device` when debugging multi-device issues.
2. Use `out=` parameter for ufuncs in loops with > 100 iterations and arrays < 1 MB.
3. Use `dpnp.empty()` instead of `dpnp.zeros()` when initial values do not matter.
4. In Jupyter notebooks, call `gc.collect()` after deleting large arrays to encourage device memory reclamation (note: timing depends on object lifetime and allocator behavior, not guaranteed immediate).
5. Monitor memory with `xpu-smi dump -m 1` during development to catch leaks early.
6. Chunk datasets that exceed 50% of device memory; process iteratively with explicit cleanup.
7. Profile before optimizing: use `time` module and memory monitoring to identify actual bottleneck.
8. Fallback to NumPy when dataset < 10,000 elements or when device memory is exhausted and chunking overhead exceeds compute savings.
9. Avoid implicit conversions in tight loops (mixed dpnp/NumPy operations trigger repeated copies).
10. For production workloads, validate memory usage in realistic scenarios (full dataset size, concurrent users) before deployment.
