# Intel perf false sharing (shared_ptr control block)

You are given `/app/sp_bad.cpp`. A single shared object is read by many threads.
Each thread, in a hot loop, copies a `std::shared_ptr<Payload>` (which atomically
bumps the reference count up and down) and reads the object's read-only `value`
field. The included `/app/perf_c2c.txt` shows remote-HITM traffic on one cache
line at two offsets: the control block's atomic reference count (offset 0x00,
written on every copy) and `Payload::value` (offset 0x10, only ever read).

The object is allocated with `std::make_shared<Payload>()`, which places the
control block (holding the atomic reference count) in the **same heap block** as
the object, adjacent to its first members. So the constantly-written reference
count and the read-only `value` field land on the **same 64-byte cache line**.
Every refcount write invalidates the line, and every read of `value` then pays a
coherence miss even though `value` is never written. This is false sharing
between the shared_ptr control block and the object payload — the pattern fixed
in Hologres by not using `make_shared`.

Create a fixed implementation that:

1. Preserves the CLI: `<threads> <iterations>`.
2. Preserves the exact final total.
3. Stops co-locating the control block with the object payload: allocate the
   object **separately** from its control block (e.g.
   `std::shared_ptr<Payload>(new Payload(...))` instead of `make_shared`), and/or
   cache-line-align/pad so the reference count and the hot read-only field sit on
   different cache lines.
4. Writes source at `/app/sp_fixed.cpp`.
5. Writes an executable binary at `/app/sp_fixed`.
6. Prints a line containing `VALID total=<value>`.

A typical compile command is:

```bash
g++ -O3 -std=c++17 -pthread /app/sp_fixed.cpp -o /app/sp_fixed
```

The verifier checks that the total is unchanged at several thread counts, that
the program terminates within the time limit, and that the source no longer
allocates the contended object with `make_shared` (the control block is
separated from the payload, or the payload is explicitly cache-line-aligned).
