#!/usr/bin/env bash
set -euo pipefail

cat > /app/crit_fixed.cpp <<'CPP'
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>

// Critical section shrunk to only the shared update. compute() is a pure
// function of the index and does not touch shared state, so it runs OUTSIDE the
// lock; the mutex is held only for `total_ += v`. Every waiter is now blocked
// for a single add instead of the whole compute(), so contention no longer
// scales with the cost of the lock-independent work.
class Accumulator {
    std::mutex mtx_;
    std::uint64_t total_ = 0;
public:
    static std::uint64_t compute(std::uint64_t i) {
        std::uint64_t acc = i;
        for (int k = 0; k < 64; ++k) {
            acc = acc * 6364136223846793005ULL + 1442695040888963407ULL;
            acc ^= acc >> 29;
        }
        return acc;
    }

    void tick(std::uint64_t i) {
        std::uint64_t v = compute(i);   // lock-independent work, now outside the lock
        mtx_.lock();
        total_ += v;                    // only the shared update is protected
        mtx_.unlock();
    }

    std::uint64_t total() const { return total_; }
};

int main(int argc, char** argv) {
    const unsigned threads = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 4u;
    const std::uint64_t iters = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 200000ULL;
    if (threads == 0 || iters == 0) { std::cerr << "INVALID_ARGUMENTS\n"; return 2; }

    Accumulator acc;
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < threads; ++t) {
        pool.emplace_back([&, t] {
            for (std::uint64_t i = 0; i < iters; ++i) {
                acc.tick(static_cast<std::uint64_t>(t) * iters + i);
            }
        });
    }
    for (auto& th : pool) th.join();

    std::uint64_t expected = 0;
    const std::uint64_t n = static_cast<std::uint64_t>(threads) * iters;
    for (std::uint64_t i = 0; i < n; ++i) expected += Accumulator::compute(i);
    if (acc.total() != expected) { std::cerr << "INVALID_RESULT total=" << acc.total() << "\n"; return 1; }
    std::cout << "VALID total=" << acc.total() << "\n";
    return 0;
}
CPP

g++ -O3 -std=c++17 -pthread /app/crit_fixed.cpp -o /app/crit_fixed
