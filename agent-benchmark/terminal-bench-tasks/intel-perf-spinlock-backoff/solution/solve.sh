#!/usr/bin/env bash
set -euo pipefail

cat > /app/spin_fixed.cpp <<'CPP'
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <thread>
#include <vector>

#if defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>
static inline void cpu_relax() { _mm_pause(); }
#else
static inline void cpu_relax() { std::this_thread::yield(); }
#endif

// Test-and-test-and-set (TTAS) spinlock WITH bounded exponential backoff.
// The read-only spin keeps the line shared while the lock is held. After a
// failed exchange (lost the race at release), the waiter spins on a relax/pause
// for `backoff` iterations, then doubles `backoff` up to a cap before retrying.
// Spreading retries in time breaks the release-time CAS storm. The cap bounds
// the worst-case delay so the lock can never livelock under oversubscription.
class TtasBackoffLock {
    std::atomic<int> flag{0};
    static constexpr int kMaxBackoff = 1024;  // cap: bounds retry delay
public:
    void lock() {
        int backoff = 1;
        for (;;) {
            // read-only spin: line stays shared while the lock is held
            while (flag.load(std::memory_order_relaxed) == 1) {
                cpu_relax();
            }
            if (flag.exchange(1, std::memory_order_acquire) == 0) return;
            // lost the race at release: back off before retrying
            for (int i = 0; i < backoff; ++i) cpu_relax();
            backoff = (backoff < kMaxBackoff) ? (backoff << 1) : kMaxBackoff;
        }
    }
    void unlock() { flag.store(0, std::memory_order_release); }
};

int main(int argc, char** argv) {
    const unsigned threads = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 4u;
    const std::uint64_t iters = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 400000ULL;
    if (threads == 0 || iters == 0) { std::cerr << "INVALID_ARGUMENTS\n"; return 2; }

    TtasBackoffLock lock;
    std::uint64_t counter = 0;
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < threads; ++t) {
        pool.emplace_back([&] {
            for (std::uint64_t i = 0; i < iters; ++i) {
                lock.lock();
                ++counter;
                lock.unlock();
            }
        });
    }
    for (auto& th : pool) th.join();

    const std::uint64_t expected = static_cast<std::uint64_t>(threads) * iters;
    if (counter != expected) { std::cerr << "INVALID_RESULT counter=" << counter << "\n"; return 1; }
    std::cout << "VALID count=" << counter << "\n";
    return 0;
}
CPP

g++ -O3 -std=c++17 -pthread /app/spin_fixed.cpp -o /app/spin_fixed
