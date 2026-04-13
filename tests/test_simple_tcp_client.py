from __future__ import annotations

import socket
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from scripts import simple_tcp_client


class SimpleTcpClientScriptTest(unittest.TestCase):
    def run_with_socket(self, fake_socket: object) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            with patch("socket.create_connection", return_value=fake_socket):
                result = simple_tcp_client.run_probe("127.0.0.1", 9000, 0.1)
        return result, output.getvalue()

    def test_successful_exchange_prints_raw_reply(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []

            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)

            def recv(self, _: int) -> bytes:
                return b"VALUE 12.345600\r\n "

        fake_socket = FakeSocket()
        result, output = self.run_with_socket(fake_socket)

        self.assertEqual(result, 0)
        self.assertEqual(fake_socket.sent, [b"GET pulsewidth\r\n"])
        self.assertIn("Recv bytes: b'VALUE 12.345600\\r\\n '", output)
        self.assertIn("'VALUE 12.345600\\r\\n '", output)

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


if __name__ == "__main__":
    unittest.main()
