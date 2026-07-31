# Getting started: running your own circuits through qkernel

This assumes you already know Qiskit and have run a circuit locally through
`AerSimulator` — this guide is about the qkernel-specific parts: getting the
environment up, submitting *your* circuit instead of the bundled Bell state,
switching to real IBM hardware, and what to do when something breaks.

## 1. Get the environment running

You need WSL2 Ubuntu with the `qpu_driver` kernel module built and loaded
(see `kernel/qpu0/README.md` if you haven't done the one-time custom-kernel
setup yet — Microsoft's stock WSL2 kernel can't build modules against itself
directly).

```bash
cd ~/projects/qkernel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd kernel/qpu0
make
sudo insmod qpu_driver.ko
cd ../..
```

Check it worked:

```bash
lsmod | grep qpu_driver
ls /dev/qpu0 /dev/qpu0worker
```

Both device nodes should exist. If not, see **Debugging → module won't load** below.

## 2. Turn your existing circuit into something qkernel can submit

qkernel's client (`qctl`) submits circuits as OpenQASM 2 text files — not
Python `QuantumCircuit` objects directly. If you've already got a circuit you
tested with Aer:

```python
from qiskit import qasm2

qasm_text = qasm2.dumps(my_circuit)   # Qiskit 1.0+; NOT circuit.qasm(), that's removed
with open("my_circuit.qasm", "w") as f:
    f.write(qasm_text)
```

Two constraints worth knowing before you do this:
- **Circuit size cap**: the kernel driver's fixed buffer holds up to 4096
  bytes of QASM text. Fine for anything reasonably sized; a very deep or
  wide circuit could exceed it (`qctl submit` will just fail — see below).
- **Measurement-based only**: the pipeline returns measurement counts
  (`Sampler`), not statevectors or expectation values. If your local Aer
  testing used `Estimator` or `.save_statevector()`, that path isn't wired
  up here — only circuits ending in measurement.

### Worked example: a larger circuit (e.g. 30 qubits)

Same workflow as above — a bigger qubit count doesn't change the steps:

```python
from qiskit import qasm2

qasm_text = qasm2.dumps(my_30_qubit_circuit)
with open("my_circuit.qasm", "w") as f:
    f.write(qasm_text)
```

```bash
python3 -m cli.qctl submit my_circuit.qasm --shots 1024
```

Two real constraints apply here specifically, both about qkernel's design,
not IBM's:

**a) The 4096-byte QASM buffer is a constraint on circuit *depth* (total gate
count), not qubit count directly.** 30 qubits with a shallow circuit (tens of
gates) fits easily; 30 qubits with hundreds of gates might not. Check the
size before submitting:

```python
print(len(qasm_text.encode()))  # must be < 4096
```

If it's over, that's a real, documented limitation (see README's "Known
limitations") — not something you're doing wrong.

**b) The kernel's qubit-capacity check is a static number set when the
module loads, not the actual backend's real capacity.** It defaults to 32
(`qpu_total_qubits=32`), checked regardless of whether you're running
against Aer or IBM's 156-qubit hardware. A 30-qubit circuit fits fine under
the default (30 < 32). If you ever need more — say a 50-qubit circuit
against real IBM hardware — reload the module with a higher value:

```bash
sudo rmmod qpu_driver
sudo insmod qpu_driver.ko qpu_total_qubits=156
```

This is a slightly awkward part of the current design worth knowing about:
the kernel doesn't dynamically know which backend a job will actually run
on, it just enforces whatever number the module was loaded with.

## 3. Submit, monitor, retrieve results

Terminal 1 — start the worker (fetches jobs, executes them):

```bash
cd ~/projects/qkernel
source .venv/bin/activate
python3 -m daemon.kernel_worker
```

Terminal 2 — submit your circuit:

```bash
python3 -m cli.qctl submit my_circuit.qasm --shots 1024
# {"job_id": N}

python3 -m cli.qctl status N
python3 -m cli.qctl result N
python3 -m cli.qctl backends   # live qubit usage + job counters
```

This runs on the local Aer simulator by default — same numerical results
you'd get calling Aer directly, just dispatched through the kernel driver
instead of an in-process function call.

## 4. Switch to real IBM Quantum hardware

Once your circuit works against Aer, point the worker at IBM instead (setup
covered in section 5 below — do that first if you haven't):

```bash
QKERNEL_BACKEND=ibm python3 -m daemon.kernel_worker
```

Everything else is identical — same `qctl submit`/`status`/`result` commands.
The only differences: `backend=ibm_<device>` in the worker's `ready` line,
and real queue time (seconds to several minutes, depending on how busy the
least-busy device is) instead of Aer's near-instant response.

To target a specific device instead of auto-selecting least-busy:

```bash
QKERNEL_BACKEND=ibm QKERNEL_IBM_BACKEND_NAME=ibm_fez python3 -m daemon.kernel_worker
```

## 5. IBM Cloud account + API key setup

1. Go to the IBM Quantum Platform (search "IBM Quantum Platform" if the
   current URL isn't `quantum.ibm.com` or `cloud.ibm.com` by the time you
   read this — IBM has restructured this a few times, so don't trust a
   stale link over what's actually on their site).
2. Create an account / log in with an IBM Cloud ID.
3. Once logged in, find your account's **API keys** section (usually under
   your account/profile settings, sometimes labeled "Access" or "API keys").
   Generate a new key.
4. **Copy it immediately — it's shown once.** If you lose it, generate a new
   one; you can't retrieve the old value later.
5. Note the plan you're on (the free "open" plan gives access to real
   hardware with usage limits — exact quotas have changed over time, so
   check what's current on your account page rather than assuming).

**Do not paste this key into a chat with me, a GitHub issue, a Slack
message, or anywhere else it could get logged.** If you ever do paste it
somewhere by accident, treat it as compromised immediately: go back to the
API keys page and revoke/regenerate it before doing anything else.

## 6. Store the key: two options

**Option A — saved account (recommended, what this project defaults to).**
Run this once, typing the token directly into your own terminal:

```bash
python3 -c "
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(channel='ibm_quantum_platform', token='YOUR_TOKEN', overwrite=True)
"
```

This writes to `~/.qiskit/qiskit-ibm-runtime.json` — outside the repo
entirely, so there's no file in the project that could ever accidentally get
committed with your token in it.

**Option B — `.env` file (if you specifically want explicit, portable config,
e.g. for scripts or a container).**

```bash
cp .env.example .env
# edit .env, paste your token in place of the placeholder
```

`.env` is already in `.gitignore` — it will never be staged by `git add .`
or show up in `git status` as trackable. `kernel_worker.py` loads it
automatically (`QKERNEL_IBM_TOKEN` takes priority over a saved account if
both are present). Still, treat the file itself as sensitive: don't `cat` it
into a chat, a screen share, or a bug report.

If `channel='ibm_quantum_platform'` gets rejected with an invalid-channel
error, current `qiskit-ibm-runtime` accepts `ibm_cloud` or
`ibm_quantum_platform` — try the other one. This is exactly the kind of
detail that shifts as IBM's SDK evolves; the error message itself will tell
you the valid values at whatever version you're running.

## Debugging: when something goes wrong

**`insmod` says "File exists".** The module's already loaded — not an
error. Check `lsmod | grep qpu_driver`.

**`rmmod` says "Module qpu_driver is in use".** Something still has
`/dev/qpu0` or `/dev/qpu0worker` open — almost always a leftover
`kernel_worker.py` process from a previous session.
```bash
ps aux | grep kernel_worker
sudo kill -9 <pid>
```
Then retry `rmmod`. Rebuilding the `.ko` without doing this leaves the *old*
module running — new code compiles fine but silently isn't the one active.

**`qctl submit` fails with `[Errno 28] No space left on device` /
`OSError` around ENOSPC.** The circuit needs more qubits than the backend
has free capacity right now (`qctl backends` shows current usage). Wait for
running jobs to finish, or check you're not leaking capacity from a
previous orphaned job (see next item).

**A job is stuck at `RUNNING` forever.** Known limitation: if the worker
process that fetched a job dies before calling `complete()`, nothing
currently reclaims it. Check `ps aux | grep kernel_worker` — if the worker
that had it is gone, that job is unrecoverable; submit a new one. This is
documented in the README's "Known limitations" section, not something
you're doing wrong.

**`kernel_worker.py` hangs completely, doesn't respond to Ctrl+C, when
`num_workers > 1`.** Also a known, documented limitation (threading/GIL
interaction with the blocking kernel `ioctl`) — stick with the default
single worker.

**`insmod` fails with a version-magic or "disagrees about version of
symbol" error.** You're running a different kernel than the module was
built against — almost always means you rebuilt the kernel or module
inconsistently. See `kernel/qpu0/README.md` for the full custom-kernel setup;
the short version is the running kernel and the module must come from
literally the same build.

**IBM backend: `QiskitRuntimeService()` raises an auth/account error.**
Either no credentials are saved/set (redo section 5-6), or the channel value
is wrong for your account type (try swapping `ibm_quantum_platform` ↔
`ibm_cloud`). The error text usually names the actual problem — read it
before assuming it's something else.

**IBM backend: job queues for a very long time.** Real hardware, real
queue. Check `service.backends()` for a less busy device, or pin a specific
one with `QKERNEL_IBM_BACKEND_NAME` if you know which is currently quieter.

## Why use this instead of just the IBM Quantum web platform?

**Where qkernel genuinely helps:**
- **Scriptable and automatable.** `qctl submit circuit.qasm` is a shell
  command — it fits into scripts, batch sweeps, CI, or anything else you'd
  automate. The browser platform is fundamentally a manual, one-circuit-at-
  a-time UI.
- **One interface, two backends.** The same `qctl submit`/`status`/`result`
  commands work identically against local Aer and real IBM hardware — you
  develop and debug against the fast, free simulator, then flip one
  environment variable to run the exact same circuit for real. Doing this
  with IBM's SDK directly means writing different code paths for
  `AerSimulator` versus `QiskitRuntimeService`.
- **OS-level visibility into your own resource usage.** `qctl backends`,
  sysfs telemetry, and cgroup limits give you a local, inspectable record
  of what's queued/running/done and how much capacity you're using — useful
  if you're running experiments alongside other local work and want to
  reason about contention, not just submit-and-forget.
- **Stays in your terminal.** No context-switching to a browser tab,
  dashboard navigation, or page reloads mid-experiment.

**Where the IBM platform is genuinely better — be honest about this:**
- Its job dashboard, circuit visualizer, and transpiler controls (routing,
  optimization level, error mitigation like dynamical decoupling and
  twirling) are mature, polished tooling that qkernel doesn't attempt to
  replicate — this project is a thin dispatch layer, not a competing IDE.
- No artificial size limits — qkernel's 4KB QASM / 2KB result caps are real
  constraints of a fixed-size kernel `ioctl` buffer; IBM's platform has no
  such ceiling.
- No setup cost — logging into a website is a lot less friction than
  building a custom WSL2 kernel, which this project genuinely requires.
- Currently single-worker only (documented limitation) — no local
  parallelism across simultaneous jobs.

The honest framing: qkernel is worth using when you want a scriptable,
backend-agnostic CLI workflow for running the *same* circuit against
simulator and real hardware without rewriting code — not as a wholesale
replacement for IBM's own tooling, which is more capable for anything
involving visualization, error mitigation, or fine-grained transpiler control.
