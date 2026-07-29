import time

from daemon.hal.base import QuantumBackend
from daemon.job import JobStatus
from daemon.scheduler import JobManager

BELL_QASM = """
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0], q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""


class FakeBackend(QuantumBackend):
    name = "fake"
    max_qubits = 4

    def execute(self, qasm: str, shots: int) -> dict:
        return {"00": shots // 2, "11": shots - shots // 2}


def wait_for(job_manager, job_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = job_manager.get(job_id)
        if job.status in (JobStatus.DONE, JobStatus.FAILED):
            return job
        time.sleep(0.01)
    raise TimeoutError("job did not finish in time")


def test_submit_and_run():
    manager = JobManager(backend=FakeBackend(), num_workers=1)
    manager.start()

    job = manager.submit(BELL_QASM, shots=100)
    finished = wait_for(manager, job.id)

    assert finished.status == JobStatus.DONE
    assert finished.counts == {"00": 50, "11": 50}


def test_submit_rejects_circuit_too_large():
    manager = JobManager(backend=FakeBackend(), num_workers=1)
    manager.start()

    too_big = BELL_QASM.replace("q[2]", "q[8]").replace("c[2]", "c[8]")
    try:
        manager.submit(too_big, shots=10)
        assert False, "expected ValueError"
    except ValueError:
        pass
