from __future__ import annotations

import unittest

from agilent_control.instrument import Keysight33600A
from agilent_control.transports import FakeVisaResource


class Keysight33600ATest(unittest.TestCase):
    def test_get_all_scpi_dict_uses_queries_without_newlines(self) -> None:
        resource = FakeVisaResource(
            responses={
                "SOURce1:FREQuency?": "1000\r\n",
                "OUTPut?": "0\n",
            }
        )
        instrument = Keysight33600A(
            resource=resource,
            scpi_commands=("SOURce1:FREQuency{0}", "OUTPut{0}"),
            factory_defaults=(),
        )

        self.assertEqual(
            instrument.get_all_scpi_dict(),
            {"SOURce1:FREQuency?": " 1000", "OUTPut?": " 0"},
        )

    def test_get_unique_scpi_list_filters_factory_defaults(self) -> None:
        resource = FakeVisaResource(
            responses={
                "SOURce1:FREQuency?": "1000",
                "OUTPut?": "1",
            }
        )
        instrument = Keysight33600A(
            resource=resource,
            scpi_commands=("SOURce1:FREQuency{0}", "OUTPut{0}"),
            factory_defaults=("OUTPut 1",),
        )

        self.assertEqual(instrument.get_unique_scpi_list(), ["SOURce1:FREQuency 1000"])

    def test_apply_settings_writes_each_command(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)

        instrument.apply_settings(("OUTPut 1", "SOURce1:FREQuency 1234"))

        self.assertEqual(resource.writes, ["OUTPut 1", "SOURce1:FREQuency 1234"])

    def test_close_closes_resource(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)

        instrument.close()

        self.assertTrue(resource.is_closed)


if __name__ == "__main__":
    unittest.main()
