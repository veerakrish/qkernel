import threading


class QubitAllocator:
    """Tracks qubit capacity for a backend as a counting semaphore.

    A simulator doesn't actually need reservation to run correctly, but a
    resource manager that hands out unlimited capacity isn't modeling
    anything — this makes contention real so the scheduler has something to
    schedule, and gives Phase 4 (a real, capacity-limited QPU) a policy
    layer that already works.
    """

    def __init__(self, total_qubits: int):
        self.total_qubits = total_qubits
        self._available = total_qubits
        self._cond = threading.Condition()

    def acquire(self, n: int) -> None:
        if n > self.total_qubits:
            raise ValueError(f"requested {n} qubits exceeds backend capacity {self.total_qubits}")
        with self._cond:
            while self._available < n:
                self._cond.wait()
            self._available -= n

    def release(self, n: int) -> None:
        with self._cond:
            self._available += n
            self._cond.notify_all()

    @property
    def in_use(self) -> int:
        with self._cond:
            return self.total_qubits - self._available
