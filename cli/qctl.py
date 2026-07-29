import argparse
import json
import socket
import sys

from daemon.protocol import SOCKET_PATH, recv_message, send_message


def call(message: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(SOCKET_PATH)
        send_message(sock.makefile("wb"), message)
        reply = recv_message(sock.makefile("rb"))
        if reply is None:
            raise ConnectionError("daemon closed the connection without replying")
        return reply


def cmd_submit(args: argparse.Namespace) -> None:
    with open(args.qasm_file) as f:
        qasm = f.read()
    reply = call({"cmd": "submit", "qasm": qasm, "shots": args.shots})
    print(json.dumps(reply, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    print(json.dumps(call({"cmd": "status", "job_id": args.job_id}), indent=2))


def cmd_result(args: argparse.Namespace) -> None:
    print(json.dumps(call({"cmd": "result", "job_id": args.job_id}), indent=2))


def cmd_backends(_args: argparse.Namespace) -> None:
    print(json.dumps(call({"cmd": "backends"}), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="qctl")
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="submit a QASM circuit as a job")
    p_submit.add_argument("qasm_file")
    p_submit.add_argument("--shots", type=int, default=1024)
    p_submit.set_defaults(func=cmd_submit)

    p_status = sub.add_parser("status", help="check a job's status")
    p_status.add_argument("job_id")
    p_status.set_defaults(func=cmd_status)

    p_result = sub.add_parser("result", help="fetch a finished job's result")
    p_result.add_argument("job_id")
    p_result.set_defaults(func=cmd_result)

    p_backends = sub.add_parser("backends", help="show backend capacity/usage")
    p_backends.set_defaults(func=cmd_backends)

    args = parser.parse_args()
    try:
        args.func(args)
    except (ConnectionError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
