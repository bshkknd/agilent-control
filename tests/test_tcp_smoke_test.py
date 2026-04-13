from __future__ import annotations

import socket
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from scripts import tcp_smoke_test


class TcpSmokeTestScriptTest(unittest.TestCase):
    def run_with_socket(self, fake_socket: object) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            with patch("socket.create_connection", return_value=fake_socket):
                result = tcp_smoke_test.run_probe("127.0.0.1", 9000, 2.0)
        return result, output.getvalue()

    def test_successful_exchange_prints_raw_bytes(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []
                self.responses = [b"VALUE 123\r\n"]

            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)

            def recv(self, _: int) -> bytes:
                if self.responses:
                    return self.responses.pop(0)
                return b""

        fake_socket = FakeSocket()
        result, output = self.run_with_socket(fake_socket)

        self.assertEqual(result, 0)
        self.assertEqual(fake_socket.sent, [b"GET pulsewidth\r\n"])
        self.assertIn("Recv bytes: b'VALUE 123\\r\\n'", output)
        self.assertIn("Protocol: OK (VALUE=123)", output)

    def test_timeout_returns_failure(self) -> None:
        class FakeSocket:
            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendall(self, data: bytes) -> None:
                self.sent = data

            def recv(self, _: int) -> bytes:
                raise socket.timeout()

        result, output = self.run_with_socket(FakeSocket())

        self.assertEqual(result, 1)
        self.assertIn("Receive: TIMEOUT", output)

    def test_closed_without_response_returns_failure(self) -> None:
        class FakeSocket:
            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendall(self, data: bytes) -> None:
                self.sent = data

            def recv(self, _: int) -> bytes:
                return b""

        result, output = self.run_with_socket(FakeSocket())

        self.assertEqual(result, 1)
        self.assertIn("Receive: CLOSED_WITHOUT_RESPONSE", output)

    def test_lf_only_response_is_reported_invalid(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.responses = [b"VALUE 123\n", b""]

            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendall(self, data: bytes) -> None:
                self.sent = data

            def recv(self, _: int) -> bytes:
                if self.responses:
                    return self.responses.pop(0)
                return b""

        result, output = self.run_with_socket(FakeSocket())

        self.assertEqual(result, 1)
        self.assertIn("Receive: INVALID", output)


if __name__ == "__main__":
    unittest.main()
