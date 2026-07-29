import argparse
import json
import sys

from qiskit import QuantumCircuit

from daemon.kdevice import QPU_JOB_DONE, QPU_JOB_FAILED, QpuClient

_STATUS_NAMES = {0: "PENDING", 1: "RUNNING", 2: "DONE", 3: "FAILED"}


def cmd_submit(args: argparse.Namespace) -> None:
    with open(args.qasm_file) as f:
        qasm = f.read()
    num_qubits = QuantumCircuit.from_qasm_str(qasm).num_qubits

    client = QpuClient()
    job_id = client.submit(qasm, shots=args.shots, num_qubits=num_qubits)
    client.close()
    print(json.dumps({"job_id": job_id}, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    client = QpuClient()
    status = client.query(args.job_id)
    client.close()
    print(json.dumps({"job_id": status["job_id"], "status": _STATUS_NAMES[status["status"]]}, indent=2))


def cmd_result(args: argparse.Namespace) -> None:
    client = QpuClient()
    status = client.query(args.job_id)
    client.close()

    state = _STATUS_NAMES[status["status"]]
    if status["status"] not in (QPU_JOB_DONE, QPU_JOB_FAILED):
        print(f"error: job not finished (status={state})", file=sys.stderr)
        sys.exit(1)

    result = json.loads(status["result"]) if state == "DONE" else status["result"]
    print(json.dumps({"job_id": status["job_id"], "status": state, "result": result}, indent=2))


def cmd_backends(_args: argparse.Namespace) -> None:
    with open("/sys/module/qpu_driver/parameters/qpu_total_qubits") as f:
        total_qubits = int(f.read().strip())
    print(json.dumps({"name": "qpu0", "max_qubits": total_qubits}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="qctl")
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="submit a QASM circuit as a job")
    p_submit.add_argument("qasm_file")
    p_submit.add_argument("--shots", type=int, default=1024)
    p_submit.set_defaults(func=cmd_submit)

    p_status = sub.add_parser("status", help="check a job's status")
    p_status.add_argument("job_id", type=int)
    p_status.set_defaults(func=cmd_status)

    p_result = sub.add_parser("result", help="fetch a finished job's result")
    p_result.add_argument("job_id", type=int)
    p_result.set_defaults(func=cmd_result)

    p_backends = sub.add_parser("backends", help="show backend qubit capacity")
    p_backends.set_defaults(func=cmd_backends)

    args = parser.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, OSError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
