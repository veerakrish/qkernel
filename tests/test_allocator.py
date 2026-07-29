import threading
import time

from daemon.allocator import QubitAllocator


def test_acquire_release_tracks_availability():
    alloc = QubitAllocator(total_qubits=4)
    alloc.acquire(3)
    assert alloc.in_use == 3
    alloc.release(3)
    assert alloc.in_use == 0


def test_acquire_over_capacity_raises():
    alloc = QubitAllocator(total_qubits=4)
    try:
        alloc.acquire(5)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_acquire_blocks_until_capacity_available():
    alloc = QubitAllocator(total_qubits=2)
    alloc.acquire(2)

    acquired = threading.Event()

    def waiter():
        alloc.acquire(2)
        acquired.set()

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.05)
    assert not acquired.is_set()

    alloc.release(2)
    t.join(timeout=1)
    assert acquired.is_set()
