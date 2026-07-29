# qkernel

A small, honestly-scoped "quantum operating system" kernel: a job/process manager,
a qubit resource allocator, and a hardware-abstraction layer (HAL) for dispatching
quantum circuits to backends — starting on a software simulator, ending with a real
Linux kernel driver in front of it.

The design deliberately follows how Linux integrates accelerators (GPUs, TPUs, NICs):
a thin kernel-space device driver handles the mechanism (job submission, polling,
shared memory), while a userspace daemon owns the policy (scheduling, resource
allocation, multi-backend abstraction). Phase 1 proved the daemon/HAL design out
in pure userspace before any kernel code was written; Phase 2 replaces the
transport with a real kernel driver.

## Status

| Phase | Description | Status |
|---|---|---|
| 1 | Userspace daemon: job manager + qubit allocator + HAL over Qiskit Aer | ✅ done |
| 2 | Linux kernel char device (`/dev/qpu0` + `/dev/qpu0worker`, `ioctl` job broker) | 🚧 in progress |
| 3 | cgroups v2 resource limits, sysfs capability attributes, telemetry | ⬜ planned |
| 4 | Real cloud QPU backend behind the HAL (IBM Quantum) | ⬜ planned |

## Architecture (Phase 2, current)

```
 qctl (CLI) --ioctl--> /dev/qpu0 (kernel)
                            |
                     job table (idr) + pending queue (wait_event)
                            |
                     /dev/qpu0worker --ioctl--> kernel_worker.py
                                                       |
                                                 AerSimulatorBackend (Qiskit Aer)
```

The kernel module (`kernel/qpu0/qpu_driver.c`) never parses QASM or JSON — it
treats circuit text and results as opaque byte blobs and only tracks qubit
capacity as a plain counter. `ioctl` is used exclusively (no `read`/`write`);
every struct in `kernel/qpu0/qpu_ioctl.h` is `__attribute__((packed))` so
Python's `struct.pack`/`unpack` (`daemon/kdevice.py`) reproduces the exact byte
layout with a `<` format string — no compiler-padding ambiguity between the two
languages. The worker's `FETCH` call blocks on a kernel wait queue until a job
is actually pending, which is the one piece of this that's genuinely OS-level
rather than plumbing.

`daemon/server.py`/`daemon/scheduler.py` (Phase 1's Unix-socket daemon) still
exist as the original reference implementation and still run standalone, but
`qctl` now speaks the kernel `ioctl` protocol exclusively — Phase 2 supersedes
Phase 1 as the CLI's transport.

## Setup (inside WSL2 Ubuntu — this project targets Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Building the kernel module requires headers matching your exact running
kernel. On stock WSL2 this needs a kernel built from source and WSL2
reconfigured to boot it — see `kernel/qpu0/README.md` for the full path if
you're setting this up fresh; it's a one-time cost.

## Running the demo (Phase 2, kernel-mediated)

Build and load the driver:

```bash
cd kernel/qpu0
make
sudo insmod qpu_driver.ko
cd ../..
```

Terminal 1 — start the worker (fetches jobs from the kernel, executes on Aer):

```bash
python3 -m daemon.kernel_worker
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

`pytest` covers Phase 1's pure-userspace logic (allocator, scheduler) and
doesn't require the kernel module loaded. `scripts/smoke_qpu0.py` is a manual
end-to-end check of the kernel driver's `ioctl` interface — run it directly
(`sudo python3 scripts/smoke_qpu0.py`) after `insmod`, before starting the real
worker, if you want to sanity-check the driver in isolation.

## Known limitations

- **`kernel_worker.py` runs a single worker thread by default.** With 2+
  concurrent threads, one blocked on the kernel driver's `FETCH` ioctl while
  another runs Aer's native execution, the process hangs completely — no
  exception, no response to `SIGINT`. Isolated by testing each half alone:
  Aer works fine standalone, and a single worker completes jobs correctly and
  fast, so the bug is specifically in the threading/GIL/blocking-syscall
  interaction, not the kernel driver or Aer individually. Root-causing it
  needs `py-spy`/`gdb`-level tooling, not just reasoning from the outside —
  left as a documented follow-up rather than chased further, since a single
  worker fully proves the design.
- **No orphan-job recovery.** If a worker process dies after `FETCH` but
  before `COMPLETE`, that job is dequeued and stuck at `RUNNING` forever —
  nothing currently re-queues it. A heartbeat/timeout mechanism would fix
  this; deferred to Phase 3 alongside the other resource-management work.

## Why this scope

The full "quantum OS" vision (error correction, multi-hardware HAL across
superconducting/trapped-ion/photonic devices, security manager, real-time control)
is a multi-year research effort, not a portfolio project. This repo scopes down to
the part that's buildable and demoable without lab access to real QPUs: a working
job manager, a real resource-allocation policy (qubit capacity as a semaphore in
Phase 1, an atomic counter in the kernel for Phase 2), a real Linux kernel driver,
and a HAL abstraction that's proven against a simulator and, eventually, a real
cloud backend.
