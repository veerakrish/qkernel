import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass
class Job:
    qasm: str
    shots: int
    num_qubits: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: JobStatus = JobStatus.QUEUED
    backend_name: str | None = None
    counts: dict | None = None
    error: str | None = None
    submitted_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "num_qubits": self.num_qubits,
            "shots": self.shots,
            "backend_name": self.backend_name,
            "counts": self.counts,
            "error": self.error,
        }
