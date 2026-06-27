#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <thread>
#include <vector>

// Test-and-test-and-set (TTAS) spinlock WITHOUT backoff. The read-only spin
// already keeps the line shared while the lock is held, so this is not the
// classic TAS write-storm. The remaining problem shows up at *release*: when
// unlock() clears the flag, every waiter observes the free flag in the same
// window and races into the atomic exchange simultaneously -> a CAS storm /
// thundering herd on the lock line. The spin loop has no delay, so all waiters
// retry as fast as possible.
class TtasLock {
    std::atomic<int> flag{0};
public:
    void lock() {
        for (;;) {
            // read-only spin: line stays shared while the lock is held
            while (flag.load(std::memory_order_relaxed) == 1) {
            }
            // no backoff: on release, all waiters hit this exchange at once
            if (flag.exchange(1, std::memory_order_acquire) == 0) return;
        }
    }
    void unlock() { flag.store(0, std::memory_order_release); }
};

int main(int argc, char** argv) {
    const unsigned threads = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 4u;
    const std::uint64_t iters = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 400000ULL;
    if (threads == 0 || iters == 0) { std::cerr << "INVALID_ARGUMENTS\n"; return 2; }

    TtasLock lock;
    std::uint64_t counter = 0;
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < threads; ++t) {
        pool.emplace_back([&] {
            for (std::uint64_t i = 0; i < iters; ++i) {
                lock.lock();
                ++counter;            // critical section
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
