#!/usr/bin/env bash
set -euo pipefail

cat > /app/sp_fixed.cpp <<'CPP'
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <new>
#include <thread>
#include <vector>

// Fix: do not co-locate the control block with the object payload. Constructing
// the shared_ptr from `new Payload(...)` allocates the control block separately
// from the object, so the atomic reference count no longer shares a cache line
// with the read-only `value`. We also cache-line-align Payload so its hot
// read-only field cannot share a line with any neighbouring allocation.
struct alignas(64) Payload {
    std::uint64_t value;   // read-only; now on its own cache line, away from the refcount
    char pad[56];
    explicit Payload(std::uint64_t v) : value(v), pad{} {}
};

int main(int argc, char** argv) {
    const unsigned threads = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 4u;
    const std::uint64_t iters = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 4000000ULL;
    if (threads == 0 || iters == 0) { std::cerr << "INVALID_ARGUMENTS\n"; return 2; }

    // separate allocation: control block is NOT adjacent to the payload
    std::shared_ptr<Payload> obj(new Payload(7ULL));

    std::vector<std::uint64_t> sums(threads, 0);
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < threads; ++t) {
        pool.emplace_back([&, t] {
            std::uint64_t local = 0;
            for (std::uint64_t i = 0; i < iters; ++i) {
                std::shared_ptr<Payload> copy = obj;
                local += copy->value;
            }
            sums[t] = local;
        });
    }
    for (auto& th : pool) th.join();

    std::uint64_t total = 0;
    for (auto s : sums) total += s;
    const std::uint64_t expected = static_cast<std::uint64_t>(threads) * iters * 7ULL;
    if (total != expected) { std::cerr << "INVALID_RESULT total=" << total << "\n"; return 1; }
    std::cout << "VALID total=" << total << "\n";
    return 0;
}
CPP

g++ -O3 -std=c++17 -pthread /app/sp_fixed.cpp -o /app/sp_fixed
