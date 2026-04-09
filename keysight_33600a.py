from agilent_control.instrument import DEFAULT_SCPI_COMMANDS, DEFAULT_SETTINGS, Keysight33600A

keysight_33600a = Keysight33600A
scpi_cmd_dict = DEFAULT_SCPI_COMMANDS
settings_por_scpi_list = DEFAULT_SETTINGS

__all__ = [
    "DEFAULT_SCPI_COMMANDS",
    "DEFAULT_SETTINGS",
    "Keysight33600A",
    "keysight_33600a",
    "scpi_cmd_dict",
    "settings_por_scpi_list",
]
