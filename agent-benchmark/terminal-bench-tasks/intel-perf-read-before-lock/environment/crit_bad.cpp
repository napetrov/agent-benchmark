#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>

// A shared accumulator guarded by a mutex. Each worker, in a hot loop, computes
// a per-iteration value and folds it into the shared total.
//
// The bug: the whole critical section is bloated. `compute()` depends only on
// the loop index -- it does NOT touch shared state and does NOT need the lock --
// yet it runs *while the lock is held*. Every other worker is blocked on the
// mutex for the entire duration of that lock-independent work, so the effective
// critical section is far longer than the one operation that actually needs
// protection (`total_ += v`). This is the "work that doesn't need the lock is
// done inside the lock" pattern (cf. ClickHouse ThreadGroupStatus::mutex, where
// a getter built/destroyed a temporary under the mutex; the heavy part belonged
// outside the critical section).
class Accumulator {
    std::mutex mtx_;
    std::uint64_t total_ = 0;
public:
    // pure function of the input; independent of shared state
    static std::uint64_t compute(std::uint64_t i) {
        std::uint64_t acc = i;
        for (int k = 0; k < 64; ++k) {
            acc = acc * 6364136223846793005ULL + 1442695040888963407ULL;
            acc ^= acc >> 29;
        }
        return acc;
    }

    void tick(std::uint64_t i) {
        mtx_.lock();
        std::uint64_t v = compute(i);   // lock-independent work, wrongly under the lock
        total_ += v;                    // the only operation that needs the lock
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

    // Reference total: sum of compute() over every distinct index [0, threads*iters)
    std::uint64_t expected = 0;
    const std::uint64_t n = static_cast<std::uint64_t>(threads) * iters;
    for (std::uint64_t i = 0; i < n; ++i) expected += Accumulator::compute(i);
    if (acc.total() != expected) { std::cerr << "INVALID_RESULT total=" << acc.total() << "\n"; return 1; }
    std::cout << "VALID total=" << acc.total() << "\n";
    return 0;
}
