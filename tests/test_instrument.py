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

    def test_configure_ttl_single_pulse_writes_expected_sequence(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)

        instrument.configure_ttl_single_pulse()

        self.assertEqual(
            resource.writes,
            [
                "*RST",
                "OUTP:LOAD INF",
                "FUNC PULS",
                "DISPlay:UNIT:PULSe WIDTh",
                "FREQ 10",
                "FUNC:PULS:HOLD WIDT",
                "FUNC:PULS:WIDT 1e-05",
                "FUNC:PULS:TRAN 5e-09",
                "VOLT:LOW 0",
                "VOLT:HIGH 5",
                "BURS:MODE TRIG",
                "BURS:NCYC 1",
                "TRIG:SOUR EXT",
                "TRIG:SLOP POS",
                "BURS:STAT ON",
                "OUTP ON",
            ],
        )

    def test_configure_ttl_single_pulse_accepts_overrides(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)

        instrument.configure_ttl_single_pulse(
            frequency_hz=20.0,
            pulse_width_s=20e-6,
            high_level_v=3.3,
            low_level_v=0.2,
            trigger_slope="neg",
            edge_time_s=10e-9,
            reset=False,
        )

        self.assertEqual(
            resource.writes,
            [
                "OUTP:LOAD INF",
                "FUNC PULS",
                "DISPlay:UNIT:PULSe WIDTh",
                "FREQ 20",
                "FUNC:PULS:HOLD WIDT",
                "FUNC:PULS:WIDT 2e-05",
                "FUNC:PULS:TRAN 1e-08",
                "VOLT:LOW 0.2",
                "VOLT:HIGH 3.3",
                "BURS:MODE TRIG",
                "BURS:NCYC 1",
                "TRIG:SOUR EXT",
                "TRIG:SLOP NEG",
                "BURS:STAT ON",
                "OUTP ON",
            ],
        )

    def test_set_pulse_width_writes_width_command(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)

        instrument.set_pulse_width(25e-6)

        self.assertEqual(resource.writes, ["FUNC:PULS:WIDT 2.5e-05"])

    def test_configure_sine_output_writes_expected_sequence(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)

        instrument.configure_sine_output(frequency_hz=1.5e6, power_dbm=-10.0)

        self.assertEqual(
            resource.writes,
            [
                "FUNC SIN",
                "FREQ 1500000",
                "POW -10DBM",
                "OUTP:LOAD 50",
                "OUTP ON",
            ],
        )

    def test_set_sine_frequency_writes_frequency_command(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)

        instrument.set_sine_frequency(2.5e6)

        self.assertEqual(resource.writes, ["FREQ 2500000"])

    def test_read_ttl_single_pulse_config_queries_expected_values(self) -> None:
        resource = FakeVisaResource(
            responses={
                "FUNC?": "PULS",
                "FREQ?": "10",
                "FUNC:PULS:WIDT?": "1E-5",
                "FUNC:PULS:TRAN?": "5E-9",
                "VOLT:HIGH?": "5",
                "VOLT:LOW?": "0",
                "OUTP:LOAD?": "INF",
                "BURS:MODE?": "TRIG",
                "BURS:NCYC?": "1",
                "TRIG:SOUR?": "EXT",
                "TRIG:SLOP?": "POS",
                "BURS:STAT?": "1",
                "OUTP?": "1",
            }
        )
        instrument = Keysight33600A(resource=resource)

        self.assertEqual(
            instrument.read_ttl_single_pulse_config(),
            {
                "FUNC?": "PULS",
                "FREQ?": "10",
                "FUNC:PULS:WIDT?": "1E-5",
                "FUNC:PULS:TRAN?": "5E-9",
                "VOLT:HIGH?": "5",
                "VOLT:LOW?": "0",
                "OUTP:LOAD?": "INF",
                "BURS:MODE?": "TRIG",
                "BURS:NCYC?": "1",
                "TRIG:SOUR?": "EXT",
                "TRIG:SLOP?": "POS",
                "BURS:STAT?": "1",
                "OUTP?": "1",
            },
        )


if __name__ == "__main__":
    unittest.main()
