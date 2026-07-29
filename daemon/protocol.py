import json

SOCKET_PATH = "/tmp/qkerneld.sock"


def send_message(wfile, message: dict) -> None:
    wfile.write((json.dumps(message) + "\n").encode())
    wfile.flush()


def recv_message(rfile) -> dict | None:
    line = rfile.readline()
    if not line:
        return None
    return json.loads(line)
