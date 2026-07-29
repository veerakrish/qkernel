"""ioctl bindings for the qpu0/qpu0worker kernel devices.

Struct formats here must mirror kernel/qpu0/qpu_ioctl.h byte-for-byte. Every
struct there is __attribute__((packed)), so a '<' (little-endian, no padding)
format string reproduces the layout exactly - if you change one side, change
the other.
"""

import fcntl
import os
import struct

DEV_CLIENT = "/dev/qpu0"
DEV_WORKER = "/dev/qpu0worker"

QASM_MAX = 4096
RESULT_MAX = 2048

_SUBMIT_FMT = f"<QIII{QASM_MAX}s"
_QUERY_FMT = f"<QII{RESULT_MAX}s"
_FETCH_FMT = f"<QIII{QASM_MAX}s"
_COMPLETE_FMT = f"<QII{RESULT_MAX}s"

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14

_IOC_TYPESHIFT = _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS

_IOC_READ_WRITE = 3  # _IOC_READ | _IOC_WRITE, per asm-generic/ioctl.h


def _iowr(magic: str, nr: int, size: int) -> int:
    return (_IOC_READ_WRITE << _IOC_DIRSHIFT) | (ord(magic) << _IOC_TYPESHIFT) | nr | (size << _IOC_SIZESHIFT)


QPU_IOC_SUBMIT = _iowr("q", 1, struct.calcsize(_SUBMIT_FMT))
QPU_IOC_QUERY = _iowr("q", 2, struct.calcsize(_QUERY_FMT))
QPU_IOC_FETCH = _iowr("q", 3, struct.calcsize(_FETCH_FMT))
QPU_IOC_COMPLETE = _iowr("q", 4, struct.calcsize(_COMPLETE_FMT))

QPU_JOB_PENDING = 0
QPU_JOB_RUNNING = 1
QPU_JOB_DONE = 2
QPU_JOB_FAILED = 3


class QpuClient:
    def __init__(self, path: str = DEV_CLIENT):
        self._fd = os.open(path, os.O_RDWR)

    def close(self) -> None:
        os.close(self._fd)

    def submit(self, qasm: str, shots: int, num_qubits: int) -> int:
        qasm_bytes = qasm.encode()
        if len(qasm_bytes) > QASM_MAX:
            raise ValueError(f"qasm exceeds {QASM_MAX} bytes")
        buf = bytearray(struct.pack(_SUBMIT_FMT, 0, num_qubits, shots, len(qasm_bytes), qasm_bytes))
        fcntl.ioctl(self._fd, QPU_IOC_SUBMIT, buf)
        return struct.unpack(_SUBMIT_FMT, buf)[0]

    def query(self, job_id: int) -> dict:
        buf = bytearray(struct.pack(_QUERY_FMT, job_id, 0, 0, b""))
        fcntl.ioctl(self._fd, QPU_IOC_QUERY, buf)
        jid, status, result_len, result = struct.unpack(_QUERY_FMT, buf)
        return {
            "job_id": jid,
            "status": status,
            "result": result[:result_len].decode() if result_len else None,
        }


class QpuWorker:
    def __init__(self, path: str = DEV_WORKER):
        self._fd = os.open(path, os.O_RDWR)

    def close(self) -> None:
        os.close(self._fd)

    def fetch(self) -> dict:
        """Blocks until a job is pending (kernel-side wait queue)."""
        buf = bytearray(struct.pack(_FETCH_FMT, 0, 0, 0, 0, b""))
        fcntl.ioctl(self._fd, QPU_IOC_FETCH, buf)
        job_id, num_qubits, shots, qasm_len, qasm = struct.unpack(_FETCH_FMT, buf)
        return {
            "job_id": job_id,
            "num_qubits": num_qubits,
            "shots": shots,
            "qasm": qasm[:qasm_len].decode(),
        }

    def complete(self, job_id: int, ok: bool, result: str) -> None:
        result_bytes = result.encode()
        if len(result_bytes) > RESULT_MAX:
            raise ValueError(f"result exceeds {RESULT_MAX} bytes")
        buf = bytearray(struct.pack(_COMPLETE_FMT, job_id, 1 if ok else 0, len(result_bytes), result_bytes))
        fcntl.ioctl(self._fd, QPU_IOC_COMPLETE, buf)
