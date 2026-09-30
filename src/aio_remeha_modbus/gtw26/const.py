"""Constants, enumerations and policies for the GTW26 gateway API."""

from dataclasses import dataclass
from enum import IntEnum
from typing import Final

MESSAGE_SPACING: Final[float] = 0.05
"""Minimum interval between requests, in seconds."""

GTW26_MAX_SPAN: Final[int] = 40
"""Largest single block read the GTW26 documents, in registers."""

# Heating and hot-water modes share a register, so a write preserves the other
# mode's bits.
HEATING_MODE_MASK: Final[int] = 0x2F
HOT_WATER_MODE_MASK: Final[int] = 0x50

BASE_MODE_REGISTERS: Final[tuple[int, int]] = (17, 26)
ISYSTEM_MODE_REGISTERS: Final[tuple[int, int, int]] = (653, 659, 667)
BASE_HOT_WATER_REGISTERS: Final[tuple[int, int]] = BASE_MODE_REGISTERS
ISYSTEM_HOT_WATER_REGISTER: Final[int] = ISYSTEM_MODE_REGISTERS[1]

CLOCK_MARKER: Final[int] = 0xFF00
"""Marker OR-ed into each clock word on the base layout."""

PANEL_NUDGE_REGISTER: Final[int] = 13
"""Panel-refresh register toggled by generation-4 base writes. Never read back."""

# Schedule layout. Each schedule is seven days of three registers, one day per read.
SCHEDULE_BASES: Final[dict[str, int]] = {
    "circuit_a_p4": 126,
    "circuit_b_p4": 147,
    "circuit_c_p4": 168,
    "hot_water": 189,
    "auxiliary": 210,
}
DAY_STRIDE: Final[int] = 3
DAYS: Final[int] = 7
WEEKDAY_FIELDS: Final[tuple[str, ...]] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Contiguous register windows each layout answers. Pooled reads stay inside these.
BASE_WINDOWS: Final[tuple[tuple[int, int], ...]] = (
    (1, 63),
    (64, 127),
    (251, 254),
    (384, 447),
    (448, 472),
    (474, 475),
)
ISYSTEM_WINDOWS: Final[tuple[tuple[int, int], ...]] = (
    (8, 8),
    (9, 11),
    (61, 61),
    (102, 102),
    (231, 233),
    (247, 252),
    (263, 299),
    (305, 360),
    (426, 474),
    (475, 475),
    (600, 625),
    (637, 644),
    (650, 685),
    (707, 744),
    (745, 746),
)

# Identity probe blocks used to detect the layout.
BASE_IDENTITY_BLOCKS: Final[tuple[tuple[int, int], ...]] = ((3, 4), (108, 3), (457, 1))
ISYSTEM_IDENTITY_BLOCKS: Final[tuple[tuple[int, int], ...]] = ((600, 1), (679, 6))


class RegisterLayout(IntEnum):
    """Which register map the controller answers."""

    BASE = 0
    """The paged base map, registers roughly 1 to 472."""

    ISYSTEM = 1
    """The iSystem map, registers 600 to 746, with schedules and installer settings."""


class ControllerGeneration(IntEnum):
    """Controller generation that governs write behaviour."""

    GENERATION_3 = 3
    """Diematic 3 and m3 generation. Base mode writes do not nudge the panel."""

    GENERATION_4 = 4
    """iSystem generation (type code 24). Base mode writes nudge the panel."""


class Weekday(IntEnum):
    """Days of the week, Monday-first and zero-based.

    The values match `gtw08.const.Weekday` so callers can use one key type
    for both gateways, while the packages stay independent.
    """

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class HeatingMode(IntEnum):
    """Heating-circuit mode held in the low bits of a mode register."""

    AUTO = 8
    TEMP_DAY = 36
    TEMP_NIGHT = 34
    PERM_DAY = 4
    PERM_NIGHT = 2
    ANTIFREEZE = 1
    HOLIDAY = 33


class HotWaterMode(IntEnum):
    """Hot-water mode held in bits 4 and 6 of a shared heating mode register."""

    AUTO = 0
    TEMP = 80
    PERM = 16


class HotWaterPriority(IntEnum):
    """Hot-water loading priority."""

    TOTAL = 0
    SLIDING = 1
    NONE = 2


class CircuitType(IntEnum):
    """Configured heating circuit type."""

    DISABLED = 0
    DIRECT = 1
    THREE_WAY_VALVE = 2
    DIRECT_PLUS = 3
    THREE_WAY_VALVE_PLUS = 4
    SWIMMING_POOL = 5


class Language(IntEnum):
    """Controller language selection. Not reliable for decoding on every panel."""

    FRENCH = 0
    GERMAN = 1
    ENGLISH = 2
    POLISH = 3
    ITALIAN = 4
    SPANISH = 5
    DUTCH = 6
    RUSSIAN = 7
    TURKISH = 8
    CZECH = 9


class AuxiliaryType(IntEnum):
    """Configured auxiliary 1 output type, from the official GTW26 M3 list."""

    PROGRAM = 0
    PRIMARY_PUMP = 1
    VM_PUMP = 2
    DHW_LOAD = 3
    FAILURE = 4


class AuxiliaryOutputType(IntEnum):
    """Configured auxiliary 2 and 3 output type, from the official list, unverified."""

    PRIMARY_PUMP = 0
    VM_PUMP = 1
    DHW_LOAD = 2
    DHW_LOAD_2 = 3
    FAILURE = 4


class AuxiliaryInput(IntEnum):
    """Configured auxiliary 1 input function, from the official M3-GT list."""

    DISABLED = 0
    ROOM_SENSOR_A = 1
    ROOM_SENSOR_B = 2
    ROOM_SENSOR_C = 3
    ROOM_SENSOR_AUX = 4


class NightMode(IntEnum):
    """What heating does during the reduced (night) period."""

    STOP = 0
    DECREASE = 1


class LegionellaProtection(IntEnum):
    """Domestic hot-water legionella protection schedule."""

    NONE = 0
    DAILY = 1
    WEEKLY = 2


class ActiveMode(IntEnum):
    """The mode a zone is currently running, from the iSystem active-mode registers."""

    ANTIFREEZE = 0
    NIGHT = 2
    DAY = 4


@dataclass(frozen=True)
class ClockPolicy:
    """Where and how to write the controller clock."""

    time_address: int
    date_address: int | None
    uses_marker: bool


@dataclass(frozen=True)
class LayoutPolicy:
    """Per-layout write parameters."""

    mode_addresses: dict[str, int]
    hot_water_addresses: tuple[int, ...]
    clock: ClockPolicy
    nudges_panel: bool


BASE_POLICY = LayoutPolicy(
    mode_addresses=dict(zip(("A", "B"), BASE_MODE_REGISTERS, strict=True)),
    hot_water_addresses=BASE_HOT_WATER_REGISTERS,
    clock=ClockPolicy(time_address=4, date_address=108, uses_marker=True),
    nudges_panel=True,
)
ISYSTEM_POLICY = LayoutPolicy(
    mode_addresses=dict(zip(("A", "B", "C"), ISYSTEM_MODE_REGISTERS, strict=True)),
    hot_water_addresses=(ISYSTEM_HOT_WATER_REGISTER,),
    clock=ClockPolicy(time_address=679, date_address=None, uses_marker=False),
    nudges_panel=False,
)


MODEL_CODES: Final[dict[int, str]] = {
    0: "3-25LP",
    1: "3-15LP",
    2: "3-25SOLO",
    3: "3-25K",
    4: "3-15SOLO",
    5: "3-E25LP",
    6: "DOMOLIGHT",
    7: "3-35",
    8: "3-50",
    9: "3-25 BIC",
    10: "3-15ECO",
    11: "3-25ECO",
    12: "3-35ECO",
    13: "3-50ECO",
    14: "3-65ECO",
    20: "Diematic 3",
    21: "Diematic m2",
    22: "Diematic m3",
    23: "MIT",
    24: "D4",
    25: "MB/OT interface",
    30: "MC 35 E",
    31: "MC 45",
    32: "MC 65",
    33: "MC 90",
    34: "C210",
    35: "C310",
    36: "C610",
    37: "C230",
    40: "Robur HP",
}
"""Tentative type-register labels, not reliable physical boiler model names."""

BASE_GENERATIONS: Final[dict[int, ControllerGeneration]] = dict.fromkeys(
    (20, 22), ControllerGeneration.GENERATION_3
) | {24: ControllerGeneration.GENERATION_4}
"""Type codes that name a controller generation. All other codes have none."""


M3_GT_FAULTS: Final[dict[int, str]] = {
    0x0000: "D3:OUTL S.B FAIL.",
    0x0001: "D4:OUTL S.C FAIL.",
    0x0002: "D5:OUTSI.S.FAIL.",
    0x0003: "D7:SYST.SENS.FAIL.",
    0x0004: "D9:DHW S.FAILURE",
    0x0005: "D11:ROOM S.A FAIL.",
    0x0006: "D12:ROOM S.B FAIL.",
    0x0007: "D13:ROOM S.C FAIL.",
    0x0008: "D14:MC COM.FAIL",
    0x0009: "D15:ST.TANK S.FAIL",
    0x000A: "D16:SWIM.P.B.S.FA",
    0x000B: "D16:SWIM.P.C.S.FA",
    0x000C: "D17:DHW 2 S.FAIL",
    0x000D: "D27:PCU COM.FAIL",
    0x000E: "Not Available",
    0x000F: "Not Available",
    0x0010: "Not Available",
    0x0011: "Not Available",
    0x0012: "D32:5 RESET:ON/OFF",
    0x0013: "D37:TA-S SHORT-CIR",
    0x0014: "D38:TA-S DISCONNEC",  # codespell:ignore
    0x0015: "D39:TA-S FAILURE",
    0x0016: "D50:OTH COM.FAIL",
    0x0017: "D51:DEF :SEE BOILER",
    0x0018: "D18:SOL.HW S.FAIL",
    0x0019: "D19:SOL.COL.S.FAIL",
    0x001A: "D20:SOL COM.FAIL",
    0x001B: "D99:DEF.BAD PCU",
    0x001C: "D40:FAIL UNKNOWN",
    0x001D: "D254:FAIL UNKNOWN",
    0x0800: "B0:PSU FAIL",
    0x0801: "B1:PSU PARAM FAIL",
    0x0802: "B2:EXCHAN.S.FAIL",
    0x0803: "B3:EXCHAN.S.FAIL",
    0x0804: "B4:EXCHAN.S.FAIL",
    0x0805: "B5:STB EXCHANGE",
    0x0806: "B6:BACK S.FAILURE",
    0x0807: "B7:BACK S.FAILURE",
    0x0808: "B8:BACK S.FAILURE",
    0x0809: "B9:STB BACK",
    0x080A: "B10:DT.EXCH.BAC.FAIL",
    0x080B: "B11:DT.BAC.EXCH.FAIL",
    0x080C: "B12:STB OPEN",
    0x080D: "B14:BURNER FAILURE",
    0x080E: "B15:CCE.TST.FAIL",
    0x080F: "B16:PARASIT FLAME",
    0x0810: "B17:VALVE FAIL",
    0x0811: "B32:DEF.OUTLET S.",
    0x0812: "B33:DEF.OUTLET S.",
    0x0813: "B34:FAN FAILURE",
    0x0814: "B35:BACK>BOIL FAIL",
    0x0815: "B36:I-CURRENT FAIL",
    0x0816: "B37:SU COM.FAIL",
    0x0817: "B38:PCU COM.FAIL",
    0x0818: "B39:BL OPEN FAIL",
    0x0819: "B255:FAIL UNKNOWN",
    0x081A: "B254:FAIL UNKNOWN",
    0x1000: "DEF.PSU 00",
    0x1001: "DEF.PSU PARAM 01",
    0x1002: "DEF.S.DEPART 02",
    0x1003: "DEF.S.DEPART 03",
    0x1004: "DEF.S.DEPART 04",
    0x1005: "STB DEPART 05",
    0x1006: "DEF.S.RETOUR 06",
    0x1007: "DEF.S.RETOUR 07",
    0x1008: "DEF.S.RETOUR 08",
    0x1009: "STB RETOUR 09",
    0x100A: "DT.DEP-RET<MIN 10",
    0x100B: "DT.DEP-RET>MAX 11",
    0x100C: "STB OUVERT 12",
    0x100D: "DEF.ALLUMAGE 14",
    0x100E: "FLAM.PARASI. 16",
    0x100F: "DEF.VANNE GAZ 17",
    0x1010: "DEF.VENTILO 34",
    0x1011: "DEF.RET>CHAUD 35",
    0x1012: "DEF.IONISATION 36",
    0x1013: "DEF.COM.SU 37",
    0x1014: "DEF.COM PCU 38",
    0x1015: "DEF BL OUVERT 39",
    0x1016: "DEF.TEST.HRU 40",
    0x1017: "DEF.MANQUE EAU 250",
    0x1018: "DEF.MANOMETRE 251",
    0x1019: "DEF.INCONNU 255",
    0x101A: "DEF.INCONNU 254",
    0x1800: "L0:PSU FAIL",
    0x1801: "L1:PSU PARAM FAIL",
    0x1802: "L2:STB OUTLET",
    0x1803: "L3:DEF.OIL.SENSOR",
    0x1804: "L4:BURNER FAILURE",
    0x1805: "L5:DEF.INTERNAL",
    0x1806: "L6:DEF.SPEED.MOT",
    0x1807: "L7:DEF.T.WARM UP",
    0x1808: "L8:DEF.PAR.FLAME",
    0x1809: "L9:OIL.PRES FAIL.",
    0x180A: "L30:SMOKE PRE.FAIL",
    0x180B: "L31:DEF.SMOKE.TEMP",
    0x180C: "L32:DEF.OUTLET S.",
    0x180D: "L33:DEF.OUTLET S.",
    0x180E: "L34:BACK S.FAILURE",
    0x180F: "L35:BACK S.FAILURE",
    0x1810: "L36:DEF.FLAME LOS",
    0x1811: "L37:SU COM.FAIL",
    0x1812: "L38:PCU COM.FAIL",
    0x1813: "L39:BL OPEN FAIL",
    0x1814: "L250:DEF.WATER MIS.",
    0x1815: "L251:MANOMETRE FAIL",
    0x1816: "L255:FAIL UNKNOWN",
    0x1817: "L254:FAIL UNKNOWN",
    0x2000: "L1:DEF.COMP.PAC",
    0x2001: "L2:DEF.V4V PAC",
    0x2002: "L3:DEF.POMPE PAC",
    0x2003: "L4:PAC HORS LIMIT",
    0x2004: "L5:DEF.DEB.PAC 6",
    0x2005: "L6:DEF.DEB.PAC 8",
    0x2006: "L7:DEF.COM.PAC",
    0x2007: "L8:DEF.S.SOR.COMP",
    0x2008: "L9:DEF.H.P PAC",
    0x2009: "L10:DEF.B.P PAC",
    0x200A: "L11:DEF.PRES.SOURC",  # codespell:ignore
    0x200B: "L12:DEF.ANTI.SOUR.",
    0x200C: "L13:DEF.P.SOURCE",
    0x200D: "L14:DEF.ANTI.COND.",
    0x200E: "L15:DEF.DEGIVRAGE",
    0x200F: "L16:DEF.PROT.MOT.",
    0x2010: "L17:DEF.S.GAZ.CH.",
    0x2011: "L18:DEF.COM.PAC",
    0x2012: "L19:DEF.S.DEP.PAC",
    0x2013: "L20:DEF.S.RET.PAC",
    0x2014: "L21:DEF.S.EXT.ENT.",
    0x2015: "L22:DEF.S.EXT.SOR.",
    0x2016: "L23:DEF.S.GAZ EXP.",
    0x2017: "L24:DEF.S.EVAPO.",
    0x2018: "L25:DEF.S.CONDENS.",
    0x2019: "L32:BL.USER.RESET",
    0x201A: "L33:DEF.DEBIT",
    0x201B: "L255:DEF.INCONNU",
    0x201C: "L254:DEF.INCONNU",
}
"""M3-GT column of the official GTW26 M3 error list, unverified on iSystem."""

C230_FAULTS: Final[dict[int, str]] = {
    0x0000: "NO FAILURE",
    0x0001: "BOILER S.FAIL.",
    0x0002: "OUTL S.A FAIL.",
    0x0003: "OUTL S.B FAIL.",
    0x0004: "OUTL S.C FAIL.",
    0x0005: "OUTSI. S.FAIL.",
    0x0006: "SMOKE S. FAIL.",
    0x0007: "AUX. F. DEFEKT",
    0x0008: "Not used",
    0x0009: "DHW S. FAILURE",
    0x000A: "BACK S.FAILURE",
    0x000B: "ROOM S.A FAIL.",
    0x000C: "ROOM S.B FAIL.",
    0x000D: "ROOM S.C FAIL.",
    0x000E: "SOLAR S. FAIL",
    0x000F: "ST.TANK S.FAIL",
    0x0010: "SWIM.P.A S.FAIL",
    0x0011: "DHW 2 S. FAIL",
    0x0012: "CDI.A COM.FAIL",
    0x0013: "CDI.B COM.FAIL",
    0x0014: "CDI.C COM.FAIL",
    0x0015: "Not used",
    0x0016: "Not used",
    0x0017: "Not used",
    0x0018: "Not used",
    0x0019: "Not used",
    0x001A: "Not used",
    0x001B: "I-CURRENT FAIL",
    0x001C: "BURNER FAILURE",
    0x001D: "PARASIT FLAME",
    0x001E: "STB BOILER",
    0x001F: "STB BACK",
    0x0020: "VALVE FAIL",
    0x0021: "Not used",
    0x0022: "PCU BLOCKING",
    0x0023: "EXCHAN.S.FAIL",
    0x0024: "STB EXCHANGE",
    0x0025: "TA-S SHORT-CIR",
    0x0026: "TA-S DISCONNEC",  # codespell:ignore
    0x0027: "TA-S FAILURE",
    0x0028: "MC COM.FAIL",
    0x0029: "AUX2.SENS.FAIL",
    0x002A: "UNIV.SENS.FAIL",
    0x002B: "SWIM.P.B S.FAIL",
    0x002C: "SWIM.P.C S.FAIL",
    0x002D: "PCU COM. FAIL",
    0x002E: "LOCKING",
    0x002F: "PSU FAIL",
    0x0030: "PSU PARAM FAIL",
    0x0031: "CCE TEST FAIL",
    0x0032: "FAN FAILURE",
    0x0033: "SMOKE.P.FAIL",
    0x0034: "SU COM.FAIL",
    0x0035: "PCU-M3 COM.FAIL",
    0x0036: "CS OPEN FAIL",
    0x0037: "EXCH-BACK<MIN",
    0x0038: "EXCH-BACK>MAX",
    0x0039: "BACK>BOIL FAIL",
    0x003A: "FAIL UNKNOWN",
    0x1000: "PSU FAIL 00",
    0x1001: "PSU PARAM FAIL 01",
    0x1002: "DEF.OUTLET S. 02",
    0x1003: "DEF.OUTLET S. 03",
    0x1004: "DEF.OUTLET S. 04",
    0x1005: "STB OUTLET 05",
    0x1006: "BACK S.FAILURE 06",
    0x1007: "BACK S.FAILURE 07",
    0x1008: "BACK S.FAILURE 08",
    0x1009: "STB BACK 09",
    0x100A: "DT.DEP-RET<MIN 10",
    0x100B: "DT.DEP-RET>MAX 11",
    0x100C: "STB OPEN 12",
    0x100D: "BURNER FAILURE 14",
    0x100E: "PARASIT FLAME 16",
    0x100F: "VALVE FAIL 17",
    0x1010: "FAN FAILURE 34",
    0x1011: "BACK>BOIL FAIL 35",
    0x1012: "I-CURRENT FAIL 36",
    0x1013: "SU COM.FAIL 37",
    0x1014: "PCU COM.FAIL 38",
    0x1015: "BL OPEN FAIL 39",
    0x1016: "TEST.HRU.FAIL 40",
    0x1017: "DEF.WATER MIS. 250",
    0x1018: "MANOMETRE FAIL 251",
    0x1019: "FAIL UNKNOWN 255",
    0x101A: "FAIL UNKNOWN 254",
}
"""C230 column of the official GTW26 M3 error list, unverified on iSystem."""

NO_FAULT: Final[int] = 0xFFFF
"""Register value that means no fault is reported."""
