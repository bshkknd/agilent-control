from __future__ import annotations

import argparse
import socket
import sys
import time

from agilent_control.sync import parse_pulsewidth_response


REQUEST_BYTES = b"GET pulsewidth\r\n"


def format_hex(data: bytes) -> str:
    return data.hex(" ") if data else "-"


def read_reply(sock: socket.socket) -> bytes:
    return sock.recv(4096)


def run_probe(host: str, port: int, timeout_s: float) -> int:
    print(f"Target: {host}:{port}")

    connect_started = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout_s)
    except OSError as exc:
        print(f"Connect: FAILED ({exc})")
        return 1

    connect_elapsed = time.perf_counter() - connect_started
    print(f"Connect: OK ({connect_elapsed:.3f}s)")

    with sock:
        sock.settimeout(timeout_s)

        send_started = time.perf_counter()
        sock.sendall(REQUEST_BYTES)
        send_elapsed = time.perf_counter() - send_started
        print(f"Sent bytes: {REQUEST_BYTES!r}")
        print(f"Sent hex:   {format_hex(REQUEST_BYTES)}")
        print(f"Send time:  {send_elapsed:.3f}s")

        receive_started = time.perf_counter()
        try:
            response_bytes = read_reply(sock)
        except socket.timeout:
            print("Receive: TIMEOUT")
            return 1
        receive_elapsed = time.perf_counter() - receive_started

    if not response_bytes:
        print("Receive: CLOSED_WITHOUT_RESPONSE")
        return 1

    print(f"Recv bytes: {response_bytes!r}")
    print(f"Recv hex:   {format_hex(response_bytes)}")
    print(f"Recv time:  {receive_elapsed:.3f}s")

    try:
        response_text = response_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        print(f"Decode: FAILED ({exc})")
        return 1

    print(f"Recv text:  {response_text!r}")

    try:
        parsed_value = parse_pulsewidth_response(response_text)
    except ValueError as exc:
        print(f"Protocol: INVALID ({exc})")
        return 1

    print(f"Protocol: OK (VALUE={parsed_value:.12g})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-shot TCP pulse-width protocol smoke test.")
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
