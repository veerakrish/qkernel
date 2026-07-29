"""Manual smoke test for the qpu0 kernel driver's ioctl interface.

Requires the qpu_driver module loaded (insmod) and /dev/qpu0 + /dev/qpu0worker
present. Run: sudo python3 scripts/smoke_qpu0.py
"""

from daemon.kdevice import QPU_JOB_DONE, QPU_JOB_PENDING, QpuClient, QpuWorker

BELL_QASM = (
    "OPENQASM 2.0;\n"
    'include "qelib1.inc";\n'
    "qreg q[2];\n"
    "creg c[2];\n"
    "h q[0];\n"
    "cx q[0],q[1];\n"
    "measure q[0]->c[0];\n"
    "measure q[1]->c[1];\n"
)


def main() -> None:
    client = QpuClient()
    worker = QpuWorker()

    job_id = client.submit(BELL_QASM, shots=1024, num_qubits=2)
    print(f"submitted job_id={job_id}")

    status = client.query(job_id)
    print(f"status after submit: {status}")
    assert status["status"] == QPU_JOB_PENDING

    job = worker.fetch()
    print(f"worker fetched: {job}")
    assert job["job_id"] == job_id
    assert job["qasm"] == BELL_QASM

    result = '{"counts": {"00": 512, "11": 512}}'
    worker.complete(job_id, ok=True, result=result)
    print("worker completed job")

    status = client.query(job_id)
    print(f"status after complete: {status}")
    assert status["status"] == QPU_JOB_DONE
    assert status["result"] == result

    client.close()
    worker.close()
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
