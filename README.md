# qkernel

A small, honestly-scoped "quantum operating system" kernel: a job/process manager,
a qubit resource allocator, and a hardware-abstraction layer (HAL) for dispatching
quantum circuits to backends — starting on a software simulator, ending with a real
Linux kernel driver in front of it.

The design deliberately follows how Linux integrates accelerators (GPUs, TPUs, NICs):
a thin kernel-space device driver handles the mechanism (job submission, polling,
shared memory), while a userspace daemon owns the policy (scheduling, resource
allocation, multi-backend abstraction). Phase 1 below is pure userspace so the
daemon/HAL design can be proven out before any kernel code is written.

## Status

| Phase | Description | Status |
|---|---|---|
| 1 | Userspace daemon: job manager + qubit allocator + HAL over Qiskit Aer | 🚧 in progress |
| 2 | Linux kernel char device (`/dev/qpu0`, `ioctl` submit/status/cancel) | ⬜ planned |
| 3 | cgroups v2 resource limits, sysfs capability attributes, telemetry | ⬜ planned |
| 4 | Real cloud QPU backend behind the HAL (IBM Quantum) | ⬜ planned |

## Architecture (Phase 1)

```
 qctl (CLI) --unix socket--> qkerneld (daemon)
                                 |
                         +-------+-------+
                         |  JobManager   |   in-memory job table + worker threads
                         +-------+-------+
                                 |
                         +-------+-------+
                         |   Allocator   |   qubit-capacity semaphore per backend
                         +-------+-------+
                                 |
                         +-------+-------+
                         |      HAL      |   abstract backend interface
                         +-------+-------+
                                 |
                          AerSimulatorBackend (Qiskit Aer)
```

The daemon speaks a small JSON-line protocol over a Unix domain socket
(`/tmp/qkerneld.sock`). That boundary is deliberate: in Phase 2 the client side
stays the same, but the daemon talks to a real kernel device (`/dev/qpu0`) instead
of calling the simulator in-process — the protocol/backend swap is meant to be a
clean seam, not a rewrite.

## Setup (inside WSL2 Ubuntu — this project targets Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the demo

Terminal 1 — start the daemon:

```bash
python3 -m daemon.server
```

Terminal 2 — submit the bundled Bell-state circuit:

```bash
python3 -m cli.qctl submit examples/bell.qasm --shots 1024
python3 -m cli.qctl status <job_id>
python3 -m cli.qctl result <job_id>
python3 -m cli.qctl backends
```

`result` prints the measurement counts once the job finishes — for a Bell state
you should see roughly a 50/50 split between `00` and `11`.

## Tests

```bash
pip install pytest
pytest
```

## Why this scope

The full "quantum OS" vision (error correction, multi-hardware HAL across
superconducting/trapped-ion/photonic devices, security manager, real-time control)
is a multi-year research effort, not a portfolio project. This repo scopes down to
the part that's buildable and demoable without lab access to real QPUs: a working
job manager, a real resource-allocation policy (qubit capacity as a semaphore), a
real Linux kernel driver boundary, and a HAL abstraction that's proven against both
a simulator and, eventually, a real cloud backend.
