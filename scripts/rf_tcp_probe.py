from __future__ import annotations

import argparse
import socket
import sys


REQUEST_BYTES = b"GET rffrequency\r\n"


def run_probe(host: str, port: int, timeout_s: float) -> int:
    print(f"Target: {host}:{port}")
    print(f"Sent bytes: {REQUEST_BYTES!r}")

    try:
        with socket.create_connection((host, port), timeout_s) as sock:
            sock.settimeout(timeout_s)
            sock.sendall(REQUEST_BYTES)
            try:
                response = sock.recv(1024)
            except socket.timeout:
                print("Receive: TIMEOUT")
                return 1
    except OSError as exc:
        print(f"Connect/send: FAILED ({exc})")
        return 1

    print(f"Recv bytes: {response!r}")
    print(f"Recv hex:   {response.hex(' ') if response else '-'}")
    if not response:
        print("Receive: CLOSED_WITHOUT_RESPONSE")
        return 1

    try:
        print(f"Recv text:  {response.decode('utf-8', 'strict')!r}")
    except UnicodeDecodeError as exc:
        print(f"Decode: FAILED ({exc})")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Raw TCP probe for the RF frequency endpoint.")
    parser.add_argument("host", help="TCP server host")
    parser.add_argument("port", type=int, help="TCP server port")
    parser.add_argument("--timeout", type=float, default=2.0, help="Socket timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_probe(args.host, args.port, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
