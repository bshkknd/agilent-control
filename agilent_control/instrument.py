from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol


class VisaLikeResource(Protocol):
    def query(self, command: str) -> str:
        ...

    def write(self, command: str) -> None:
        ...

    def close(self) -> None:
        ...


DEFAULT_SCPI_COMMANDS: tuple[str, ...] = (
    "SOURce1:AM:DEPTh{0}",
    "SOURce1:AM:DSSC{0}",
    "SOURce1:AM:INTernal:FREQuency{0}",
    "SOURce1:AM:INTernal:FUNCtion{0}",
    "SOURce1:AM:SOURce{0}",
    "SOURce1:AM:STATe{0}",
    "SOURce1:BPSK:INTernal:RATE{0}",
    "SOURce1:BPSK:PHASe{0}",
    "SOURce1:BPSK:SOURce{0}",
    "SOURce1:BPSK:STATe{0}",
    "SOURce1:BURSt:GATE:POLarity{0}",
    "SOURce1:BURSt:INTernal:PERiod{0}",
    "SOURce1:BURSt:MODE{0}",
    "SOURce1:BURSt:NCYCles{0}",
    "SOURce1:BURSt:PHASe{0}",
    "SOURce1:BURSt:STATe{0}",
    "DISPlay{0}",
    "FORMat:BORDer{0}",
    "INITiate1:CONTinuous{0}",
    "INPut:ATTenuation:STATe{0}",
    "OUTPut1:LOAD{0}",
    "OUTPut1:MODE{0}",
    "OUTPut1:POLarity{0}",
    "OUTPut1:SYNC:MODE{0}",
    "OUTPut1:SYNC:POLarity{0}",
    "OUTPut:SYNC{0}",
    "OUTPut:SYNC:SOURce{0}",
    "OUTPut:TRIGger{0}",
    "OUTPut:TRIGger:SLOPe{0}",
    "OUTPut:TRIGger:SOURce{0}",
    "OUTPut{0}",
    "ROSCillator:SOURce{0}",
    "ROSCillator:SOURce:AUTO{0}",
    "SOURce1:FM:DEViation{0}",
    "SOURce1:FM:INTernal:FREQuency{0}",
    "SOURce1:FM:INTernal:FUNCtion{0}",
    "SOURce1:FM:SOURce{0}",
    "SOURce1:FM:STATe{0}",
    "SOURce1:FREQuency{0}",
    "SOURce1:FREQuency:CENTer{0}",
    "SOURce1:FREQuency:MODE{0}",
    "SOURce1:FREQuency:SPAN{0}",
    "SOURce1:FREQuency:STARt{0}",
    "SOURce1:FREQuency:STOP{0}",
    "SOURce1:FSKey:FREQuency{0}",
    "SOURce1:FSKey:INTernal:RATE{0}",
    "SOURce1:FSKey:SOURce{0}",
    "SOURce1:FSKey:STATe{0}",
    "SOURce1:FUNCtion{0}",
    "SOURce1:FUNCtion:ARBitrary{0}",
    "SOURce1:FUNCtion:ARBitrary:ADVance{0}",
    "SOURce1:FUNCtion:ARBitrary:FILTer{0}",
    "SOURce1:FUNCtion:ARBitrary:FREQuency{0}",
    "SOURce1:FUNCtion:ARBitrary:PERiod{0}",
    "SOURce1:FUNCtion:ARBitrary:PTPeak{0}",
    "SOURce1:FUNCtion:ARBitrary:SRATe{0}",
    "SOURce1:FUNCtion:NOISe:BANDwidth{0}",
    "SOURce1:FUNCtion:PRBS:BRATe{0}",
    "SOURce1:FUNCtion:PRBS:DATA{0}",
    "SOURce1:FUNCtion:PRBS:TRANsition:BOTH{0}",
    "SOURce1:FUNCtion:PULSe:HOLD{0}",
    "SOURce1:FUNCtion:PULSe:PERiod{0}",
    "SOURce1:FUNCtion:PULSe:TRANsition:LEADing{0}",
    "SOURce1:FUNCtion:PULSe:TRANsition:TRAiling{0}",
    "SOURce1:FUNCtion:PULSe:WIDTh{0}",
    "SOURce1:FUNCtion:RAMP:SYMMetry{0}",
    "SOURce1:FUNCtion:SQUare:DCYCle{0}",
    "SOURce1:FUNCtion:SQUare:PERiod{0}",
    "SOURce1:LIST:DWELl{0}",
    "SOURce1:LIST:FREQuency{0}",
    "SOURce1:MARKer:CYCle{0}",
    "SOURce1:MARKer:FREQuency{0}",
    "SOURce1:MARKer:POINt{0}",
    "SOURce1:PHASe:ARBitrary{0}",
    "SOURce1:PHASe:MODulation{0}",
    "SOURce1:PM:DEViation{0}",
    "SOURce1:PM:INTernal:FREQuency{0}",
    "SOURce1:PM:INTernal:FUNCtion{0}",
    "SOURce1:PM:SOURce{0}",
    "SOURce1:PM:STATe{0}",
    "SOURce1:PWM:DEViation{0}",
    "SOURce1:PWM:DEViation:DCYCle{0}",
    "SOURce1:PWM:INTernal:FREQuency{0}",
    "SOURce1:PWM:INTernal:FUNCtion{0}",
    "SOURce1:PWM:SOURce{0}",
    "SOURce1:PWM:STATe{0}",
    "SOURce1:SUM:AMPLitude{0}",
    "SOURce1:SUM:INTernal:FREQuency{0}",
    "SOURce1:SUM:INTernal:FUNCtion{0}",
    "SOURce1:SUM:SOURce{0}",
    "SOURce1:SWEep:HTIMe{0}",
    "SOURce1:SWEep:RTIMe{0}",
    "SOURce1:SWEep:SPACing{0}",
    "SOURce1:SWEep:STATe{0}",
    "SOURce1:SWEep:TIME{0}",
    "SOURce1:VOLTage{0}",
    "SOURce1:VOLTage:HIGH{0}",
    "SOURce1:VOLTage:LOW{0}",
    "SOURce1:VOLTage:LIMit:HIGH{0}",
    "SOURce1:VOLTage:LIMit:LOW{0}",
    "SOURce1:VOLTage:LIMit:STATe{0}",
    "SOURce1:VOLTage:OFFSet{0}",
    "SOURce1:VOLTage:RANGe:AUTO{0}",
    "SOURce1:VOLTage:UNIT{0}",
    "TRIGger1:COUNt{0}",
    "TRIGger1:DELay{0}",
    "TRIGger1:LEVel{0}",
    "TRIGger1:SLOPe{0}",
    "TRIGger1:SOURce{0}",
    "TRIGger1:TIMer{0}",
    "UNIT:ANGLe{0}",
    "UNIT:ARBitrary:ANGLe{0}",
)


DEFAULT_SETTINGS: tuple[str, ...] = (
    "DISPlay 1",
    "FORMat:BORDer NORM",
    "INITiate1:CONTinuous 1",
    "INPut:ATTenuation:STATe 1",
    "OUTPut 0",
    "OUTPut1:LOAD +5.000000000000000E+01",
    "OUTPut1:MODE NORM",
    "OUTPut1:POLarity NORM",
    "OUTPut1:SYNC:MODE NORM",
    "OUTPut1:SYNC:POLarity NORM",
    "OUTPut:SYNC 1",
    "OUTPut:SYNC:SOURce CH1",
    "OUTPut:TRIGger 0",
    "OUTPut:TRIGger:SLOPe POS",
    "OUTPut:TRIGger:SOURce CH1",
    "ROSCillator:SOURce INT",
    "ROSCillator:SOURce:AUTO ON",
    "SOURce1:AM:DEPTh +1.000000000000000E+02",
    "SOURce1:AM:DSSC 0",
    "SOURce1:AM:INTernal:FREQuency +1.000000000000000E+02",
    "SOURce1:AM:INTernal:FUNCtion SIN",
    "SOURce1:AM:SOURce INT",
    "SOURce1:AM:STATe 0",
    "SOURce1:BPSK:INTernal:RATE +1.000000000000000E+01",
    "SOURce1:BPSK:PHASe +1.800000000000000E+02",
    "SOURce1:BPSK:SOURce INT",
    "SOURce1:BPSK:STATe 0",
    "SOURce1:BURSt:GATE:POLarity NORM",
    "SOURce1:BURSt:INTernal:PERiod +1.000000000000000E-02",
    "SOURce1:BURSt:MODE TRIG",
    "SOURce1:BURSt:NCYCles +1.000000000000000E+00",
    "SOURce1:BURSt:PHASe +0.0000000000000E+00",
    "SOURce1:BURSt:STATe 0",
    "SOURce1:FM:DEViation +1.000000000000000E+02",
    "SOURce1:FM:INTernal:FREQuency +1.000000000000000E+01",
    "SOURce1:FM:INTernal:FUNCtion SIN",
    "SOURce1:FM:SOURce INT",
    "SOURce1:FM:STATe 0",
    "SOURce1:FREQuency +1.000000000000000E+03",
    "SOURce1:FREQuency:CENTer +5.500000000000000E+02",
    "SOURce1:FREQuency:MODE CW",
    "SOURce1:FREQuency:SPAN +9.000000000000000E+02",
    "SOURce1:FREQuency:STARt +1.000000000000000E+02",
    "SOURce1:FREQuency:STOP +1.000000000000000E+03",
    "SOURce1:FSKey:FREQuency +1.000000000000000E+02",
    "SOURce1:FSKey:INTernal:RATE +1.000000000000000E+01",
    "SOURce1:FSKey:SOURce INT",
    "SOURce1:FSKey:STATe 0",
    "SOURce1:FUNCtion SIN",
    'SOURce1:FUNCtion:ARBitrary "INT:\\BUILTIN\\EXP_RISE.ARB"',
    "SOURce1:FUNCtion:ARBitrary:ADVance SRAT",
    "SOURce1:FUNCtion:ARBitrary:FILTer STEP",
    "SOURce1:FUNCtion:ARBitrary:FREQuency +1.600000000000000E+02",
    "SOURce1:FUNCtion:ARBitrary:PERiod +6.250000000000000E-03",
    "SOURce1:FUNCtion:ARBitrary:PTPeak +1.000000000000000E-01",
    "SOURce1:FUNCtion:ARBitrary:SRATe +4.000000000000000E+04",
    "SOURce1:FUNCtion:NOISe:BANDwidth +1.000000000000000E+05",
    "SOURce1:FUNCtion:PRBS:BRATe +1.000000000000000E+03",
    "SOURce1:FUNCtion:PRBS:DATA PN7",
    "SOURce1:FUNCtion:PRBS:TRANsition:BOTH +4.000000000000000E-09",
    "SOURce1:FUNCtion:PULSe:HOLD WIDT",
    "SOURce1:FUNCtion:PULSe:PERiod +1.000000000000000E-03",
    "SOURce1:FUNCtion:PULSe:TRANsition:LEADing +4.000000000000000E-09",
    "SOURce1:FUNCtion:PULSe:TRANsition:TRAiling +4.000000000000000E-09",
    "SOURce1:FUNCtion:PULSe:WIDTh +1.000000000000000E-04",
    "SOURce1:FUNCtion:RAMP:SYMMetry +1.000000000000000E+02",
    "SOURce1:FUNCtion:SQUare:DCYCle +5.000000000000000E+01",
    "SOURce1:FUNCtion:SQUare:PERiod +1.000000000000000E-03",
    "SOURce1:LIST:DWELl +1.000000000000000E+00",
    "SOURce1:LIST:FREQuency +1.00000000E+002,+1.00000000E+003,+5.50000000E+002",
    "SOURce1:MARKer:CYCle +2.000000000000000E+00",
    "SOURce1:MARKer:FREQuency +5.000000000000000E+02",
    "SOURce1:MARKer:POINt +1.00000000E+001",
    "SOURce1:PHASe:ARBitrary +0.0000000000000E+00",
    "SOURce1:PHASe:MODulation +0.0000000000000E+00",
    "SOURce1:PM:DEViation +1.800000000000000E+02",
    "SOURce1:PM:INTernal:FREQuency +1.000000000000000E+01",
    "SOURce1:PM:INTernal:FUNCtion SIN",
    "SOURce1:PM:SOURce INT",
    "SOURce1:PM:STATe 0",
    "SOURce1:PWM:DEViation +1.000000000000000E-05",
    "SOURce1:PWM:DEViation:DCYCle +1.000000000000000E+00",
    "SOURce1:PWM:INTernal:FREQuency +1.000000000000000E+01",
    "SOURce1:PWM:INTernal:FUNCtion SIN",
    "SOURce1:PWM:SOURce INT",
    "SOURce1:PWM:STATe 0",
    "SOURce1:SUM:AMPLitude +1.000000000000000E-01",
    "SOURce1:SUM:INTernal:FREQuency +1.000000000000000E+02",
    "SOURce1:SUM:INTernal:FUNCtion SIN",
    "SOURce1:SUM:SOURce INT",
    "SOURce1:SWEep:HTIMe +0.000000000000000E+00",
    "SOURce1:SWEep:RTIMe +0.000000000000000E+00",
    "SOURce1:SWEep:SPACing LIN",
    "SOURce1:SWEep:STATe 0",
    "SOURce1:SWEep:TIME +1.000000000000000E+00",
    "SOURce1:VOLTage +1.0000000000000E-01",
    "SOURce1:VOLTage:HIGH +5.000000000000000E-02",
    "SOURce1:VOLTage:LOW -5.000000000000000E-02",
    "SOURce1:VOLTage:LIMit:HIGH +5.000000000000000E+00",
    "SOURce1:VOLTage:LIMit:LOW -5.000000000000000E+00",
    "SOURce1:VOLTage:LIMit:STATe 0",
    "SOURce1:VOLTage:OFFSet +0.0000000000000E+00",
    "SOURce1:VOLTage:RANGe:AUTO 1",
    "SOURce1:VOLTage:UNIT VPP",
    "TRIGger1:COUNt +1.000000000000000E+00",
    "TRIGger1:DELay +0.000000000000000E+00",
    "TRIGger1:LEVel +3.300000000000000E+00",
    "TRIGger1:SLOPe POS",
    "TRIGger1:SOURce IMM",
    "TRIGger1:TIMer +1.000000000000000E+00",
    "UNIT:ANGLe DEG",
    "UNIT:ARBitrary:ANGLe DEG",
)


@dataclass(slots=True)
class Keysight33600A:
    resource: VisaLikeResource
    scpi_commands: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SCPI_COMMANDS)
    factory_defaults: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SETTINGS)

    def query(self, command: str) -> str:
        return self.resource.query(command).rstrip("\r\n")

    def write(self, command: str) -> None:
        self.resource.write(command)

    def identify(self) -> str:
        return self.query("*IDN?")

    def get_all_scpi_dict(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for command in self.scpi_commands:
            response = f" {self.query(command.format('?'))}"
            result[command.format("?")] = response
        return result

    def get_all_scpi_list(self) -> list[str]:
        result: list[str] = []
        for command in self.scpi_commands:
            response = f" {self.query(command.format('?'))}"
            result.append(command.format(response))
        return result

    def get_unique_scpi_list(self) -> list[str]:
        instrument_settings = self.get_all_scpi_list()
        return [setting for setting in instrument_settings if setting not in self.factory_defaults]

    def apply_settings(self, settings: Iterable[str]) -> None:
        for command in settings:
            self.write(command)

    def apply_factory_defaults(self) -> None:
        self.apply_settings(self.factory_defaults)

    def close(self) -> None:
        self.resource.close()
