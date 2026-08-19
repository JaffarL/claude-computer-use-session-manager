import socket
import sys


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


if not all(port_is_open(port) for port in (5900, 6080)):
    sys.exit(1)
