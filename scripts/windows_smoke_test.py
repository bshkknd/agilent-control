from __future__ import annotations

import argparse
import sys

from agilent_control import Keysight33600A, open_pyvisa_resource


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test VISA communication on Windows.")
    parser.add_argument("resource_name", help="VISA resource name, for example USB0::...")
    parser.add_argument(
        "--query",
        default="SOURce1:FREQuency?",
        help="Safe query to run after *IDN? succeeds.",
    )
    args = parser.parse_args()

    resource = open_pyvisa_resource(args.resource_name)
    instrument = Keysight33600A(resource)
    try:
        print(f"*IDN?: {instrument.identify()}")
        print(f"{args.query}: {instrument.query(args.query)}")
    finally:
        instrument.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
