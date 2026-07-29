import queue
import threading

from qiskit import QuantumCircuit

from .allocator import QubitAllocator
from .hal.base import QuantumBackend
from .job import Job, JobStatus


class JobManager:
    def __init__(self, backend: QuantumBackend, num_workers: int = 2):
        self.backend = backend
        self.allocator = QubitAllocator(backend.max_qubits)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._workers = [
            threading.Thread(target=self._worker_loop, daemon=True)
            for _ in range(num_workers)
        ]

    def start(self) -> None:
        for w in self._workers:
            w.start()

    def submit(self, qasm: str, shots: int) -> Job:
        num_qubits = QuantumCircuit.from_qasm_str(qasm).num_qubits
        if num_qubits > self.backend.max_qubits:
            raise ValueError(
                f"circuit needs {num_qubits} qubits, backend '{self.backend.name}' "
                f"has {self.backend.max_qubits}"
            )
        job = Job(qasm=qasm, shots=shots, num_qubits=num_qubits, backend_name=self.backend.name)
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if job is None:
                continue
            job.status = JobStatus.RUNNING
            self.allocator.acquire(job.num_qubits)
            try:
                job.counts = self.backend.execute(job.qasm, job.shots)
                job.status = JobStatus.DONE
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
            finally:
                self.allocator.release(job.num_qubits)
