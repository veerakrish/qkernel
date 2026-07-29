"""Worker loop: fetches jobs from the qpu0 kernel driver, executes them on
a HAL backend, and reports results back through the driver.

Requires the qpu_driver kernel module loaded. Run: python3 -m daemon.kernel_worker

Backend selection is via QKERNEL_BACKEND ("aer", the default, or "ibm").
For "ibm", QKERNEL_IBM_BACKEND_NAME optionally pins a specific device;
otherwise the least-busy operational QPU is selected. IBM credentials must
already be saved locally via QiskitRuntimeService.save_account() - this file
never touches a token.
"""

import json
import os
import sys
import threading

from daemon.hal.aer_backend import AerSimulatorBackend
from daemon.kdevice import QpuWorker


def make_backend():
    kind = os.environ.get("QKERNEL_BACKEND", "aer")
    if kind == "ibm":
        from daemon.hal.ibm_backend import IBMBackend
        return IBMBackend(backend_name=os.environ.get("QKERNEL_IBM_BACKEND_NAME"))
    return AerSimulatorBackend()


def worker_loop(worker_id: int) -> None:
    backend = make_backend()
    worker = QpuWorker()
    print(f"[worker {worker_id}] ready, backend={backend.name} max_qubits={backend.max_qubits}")
    while True:
        job = worker.fetch()
        print(f"[worker {worker_id}] fetched job_id={job['job_id']} "
              f"num_qubits={job['num_qubits']} shots={job['shots']}")
        try:
            counts = backend.execute(job["qasm"], job["shots"])
            worker.complete(job["job_id"], ok=True, result=json.dumps({"counts": counts}))
            print(f"[worker {worker_id}] completed job_id={job['job_id']}: {counts}")
        except Exception as exc:
            worker.complete(job["job_id"], ok=False, result=json.dumps({"error": str(exc)}))
            print(f"[worker {worker_id}] failed job_id={job['job_id']}: {exc}", file=sys.stderr)


def main(num_workers: int = 1) -> None:
    # num_workers > 1 hangs under real load: two threads racing on the
    # blocking FETCH ioctl while one runs Aer's native execution triggers
    # something in the GIL/threading/blocking-syscall interaction that
    # doesn't even respond to SIGINT. Isolated: a single worker completes
    # jobs correctly and fast; Aer alone (no kernel driver) is unaffected.
    # Root cause needs py-spy/gdb-level tooling to pin down - not chased
    # further here since a single worker fully proves Phase 2's design.
    threads = [
        threading.Thread(target=worker_loop, args=(i,), daemon=True)
        for i in range(num_workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
