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
| 2 | Linux kernel char device (`/dev/qpu0` + `/dev/qpu0worker`, `ioctl` job broker) | ✅ done |
| 3 | cgroups v2 resource limits, sysfs capability attributes, telemetry | ✅ done |
| 4 | Real cloud QPU backend behind the HAL (IBM Quantum) | ✅ done |

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

Phase 3 adds capability/telemetry introspection and real resource enforcement
around the worker process: `/sys/class/misc/qpu0/{qubits_total,qubits_in_use,
jobs_submitted,jobs_completed,jobs_failed}` (read-only sysfs attributes,
`qctl backends` reads these live) and running `kernel_worker.py` under a
systemd transient scope with cgroup v2 `MemoryMax`/`CPUQuota` limits that are
genuinely enforced by the kernel — see "Resource limits" below.

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
you should see roughly a 50/50 split between `00` and `11`. `backends` shows
live qubit usage and job counters from sysfs, not just static capacity.

## Resource limits (cgroups v2)

Instead of just launching the worker directly, run it under a systemd
transient scope with real memory/CPU limits — this is genuinely enforced by
the kernel's cgroup v2 memory controller, not just recorded configuration:

```bash
systemd-run --scope --unit=qkernel-worker -p MemoryMax=512M -p CPUQuota=50% \
  bash -c 'cd $(pwd) && source .venv/bin/activate && python3 -m daemon.kernel_worker'
```

`systemctl status qkernel-worker.scope` shows live memory/CPU usage against
the cap. To see the limit actually get enforced (not just configured), set
`MemoryMax` well below Qiskit/Aer's real footprint (~100-150M) and add
`-p MemorySwapMax=0` so there's no swap to fall back on — the process gets
killed by the kernel, and `dmesg` shows a `Memory cgroup out of memory` entry
naming the exact cgroup that triggered it. Without disabling swap, a tight
`MemoryMax` alone won't reliably trigger a kill — the cgroup will push pages
to swap under memory pressure instead, which is worth knowing since it's an
easy thing to get wrong when testing a memory cap.

## Running on real IBM Quantum hardware (Phase 4)

The HAL's whole point is that `AerSimulatorBackend` isn't special-cased
anywhere in the kernel driver, the worker loop, or the CLI — `daemon/hal/ibm_backend.py`
implements the same `QuantumBackend` interface against `qiskit-ibm-runtime`,
and swapping it in is a one-line environment variable, not a code change.

Set up credentials once (this stores them in `~/.qiskit/qiskit-ibm-runtime.json`,
outside the repo — never commit a token, never paste one anywhere it'll be
logged, including into an AI chat):

```bash
python3 -c "
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(channel='ibm_quantum_platform', token='YOUR_TOKEN', overwrite=True)
"
```

Then run the worker against IBM instead of Aer:

```bash
QKERNEL_BACKEND=ibm python3 -m daemon.kernel_worker
```

Everything else — `qctl submit`/`status`/`result`, the kernel driver, the
qubit-capacity accounting — is unchanged. The only visible difference besides
`backend=ibm_fez` (or whichever device is least busy) is that a real job
queues on physical hardware, so it can take anywhere from under a minute to
several minutes rather than Aer's near-instant response.

One thing worth knowing if you try this: a real device's result won't be a
clean 50/50 split for a Bell state the way Aer's is. Verified run against
`ibm_fez` (156 qubits): `{'00': 519, '11': 494, '01': 9, '10': 2}` — the small
leakage into `01`/`10` is genuine hardware noise/decoherence, not a bug. A
perfect simulator can't produce that; a real NISQ-era device does. That
noise signature is itself evidence the job actually ran on physical
hardware rather than a simulator.

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
  this; not yet built.

## Why this scope

The full "quantum OS" vision (error correction, multi-hardware HAL across
superconducting/trapped-ion/photonic devices, security manager, real-time control)
is a multi-year research effort, not a portfolio project. This repo scopes down to
the part that's buildable and demoable without lab access to real QPUs: a working
job manager, a real resource-allocation policy (qubit capacity as a semaphore in
Phase 1, an atomic counter in the kernel for Phase 2), a real Linux kernel driver,
and a HAL abstraction proven against both a local simulator and real IBM Quantum
hardware over the network.
