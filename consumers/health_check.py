"""Container health check for the Faust worker."""

import argparse
import os
import socket
import sys
import urllib.error
import urllib.request


def check_http(host: str, port: int, timeout: float = 5.0) -> bool:
    """Return True when the Faust web server responds on the configured port."""
    url = f"http://{host}:{port}/"

    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        # Any HTTP response means the web server is up.
        return True
    except Exception:
        return False


def check_tcp(host: str, port: int, timeout: float = 5.0) -> bool:
    """Fallback probe when the HTTP endpoint is unavailable but the port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Faust container health check")
    parser.add_argument("--detailed", action="store_true", help="Print probe details")
    args = parser.parse_args()

    host = os.getenv("FAUST_HEALTH_HOST", "127.0.0.1")
    port = int(os.getenv("FAUST_WEB_PORT", "6066"))

    http_ok = check_http(host, port)
    tcp_ok = check_tcp(host, port)
    healthy = http_ok or tcp_ok

    if args.detailed:
        print(f"host={host} port={port} http_ok={http_ok} tcp_ok={tcp_ok} healthy={healthy}")

    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
