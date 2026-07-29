import os
import socketserver

from .hal.aer_backend import AerSimulatorBackend
from .job import JobStatus
from .protocol import SOCKET_PATH, recv_message, send_message
from .scheduler import JobManager

job_manager: JobManager


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        while True:
            msg = recv_message(self.rfile)
            if msg is None:
                return
            try:
                reply = self._dispatch(msg)
            except Exception as exc:
                reply = {"error": str(exc)}
            send_message(self.wfile, reply)

    def _dispatch(self, msg: dict) -> dict:
        cmd = msg.get("cmd")
        if cmd == "submit":
            job = job_manager.submit(msg["qasm"], msg.get("shots", 1024))
            return {"job_id": job.id}
        if cmd == "status":
            job = job_manager.get(msg["job_id"])
            if job is None:
                return {"error": "no such job"}
            return {"status": job.status.value}
        if cmd == "result":
            job = job_manager.get(msg["job_id"])
            if job is None:
                return {"error": "no such job"}
            if job.status not in (JobStatus.DONE, JobStatus.FAILED):
                return {"error": f"job not finished (status={job.status.value})"}
            return job.to_dict()
        if cmd == "backends":
            b = job_manager.backend
            return {
                "name": b.name,
                "max_qubits": b.max_qubits,
                "qubits_in_use": job_manager.allocator.in_use,
            }
        return {"error": f"unknown command '{cmd}'"}


def main() -> None:
    global job_manager
    job_manager = JobManager(backend=AerSimulatorBackend())
    job_manager.start()

    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server = socketserver.ThreadingUnixStreamServer(SOCKET_PATH, Handler)
    print(f"qkerneld listening on {SOCKET_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        os.remove(SOCKET_PATH)


if __name__ == "__main__":
    main()
