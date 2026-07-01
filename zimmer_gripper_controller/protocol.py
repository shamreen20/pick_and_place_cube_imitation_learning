"""Zimmer process data encoding and status helpers."""

from __future__ import annotations

from dataclasses import dataclass

CW_NONE = 0x0000
CW_DATA_TRANSFER = 0x0001
CW_WRITE_PDU = 0x0002
CW_RESET_DIRECTION_FLAG = 0x0004
CW_TEACH = 0x0008
CW_MOVE_TO_BASE = 0x0100
CW_MOVE_TO_WORK = 0x0200
CW_JOG_TO_WORK = 0x0400
CW_JOG_TO_BASE = 0x0800


@dataclass(slots=True)
class OutputPDU:
    """Zimmer output process data (control -> gripper)."""

    control_word: int = CW_NONE
    device_mode: int = 0
    workpiece_no: int = 0
    reserve: int = 0
    position_tolerance: int = 50
    grip_force: int = 30
    drive_velocity: int = 30
    base_position: int = 100
    shift_position: int = 200
    teach_position: int = 300
    work_position: int = 400

    def to_registers(self) -> list[int]:
        """Encode the output structure into 8 Modbus holding registers."""
        reg0 = _u16(self.control_word)
        reg1 = (_u8(self.device_mode) << 8) | _u8(self.workpiece_no)
        reg2 = (_u8(self.reserve) << 8) | _u8(self.position_tolerance)
        reg3 = (_u8(self.grip_force) << 8) | _u8(self.drive_velocity)
        reg4 = _u16(self.base_position)
        reg5 = _u16(self.shift_position)
        reg6 = _u16(self.teach_position)
        reg7 = _u16(self.work_position)
        return [reg0, reg1, reg2, reg3, reg4, reg5, reg6, reg7]


@dataclass(slots=True)
class InputPDU:
    """Zimmer input process data (gripper -> control)."""

    status_word: int
    diagnosis: int
    actual_position: int

    @classmethod
    def from_registers(cls, registers: list[int]) -> InputPDU:
        """Decode the input structure from 3 Modbus input registers."""
        if len(registers) < 3:
            raise ValueError("Expected at least 3 input registers")
        return cls(
            status_word=_u16(registers[0]),
            diagnosis=_u16(registers[1]),
            actual_position=_u16(registers[2]),
        )

    @property
    def motor_on(self) -> bool:
        return bit_is_set(self.status_word, 1)

    @property
    def in_motion(self) -> bool:
        return bit_is_set(self.status_word, 2)

    @property
    def movement_complete(self) -> bool:
        return bit_is_set(self.status_word, 3)

    @property
    def plc_active(self) -> bool:
        return bit_is_set(self.status_word, 6)

    @property
    def base_reached(self) -> bool:
        return bit_is_set(self.status_word, 8)

    @property
    def teach_reached(self) -> bool:
        return bit_is_set(self.status_word, 9)

    @property
    def work_reached(self) -> bool:
        return bit_is_set(self.status_word, 10)

    @property
    def data_transfer_ok(self) -> bool:
        return bit_is_set(self.status_word, 12)

    @property
    def last_cmd_to_base(self) -> bool:
        return bit_is_set(self.status_word, 13)

    @property
    def last_cmd_to_work(self) -> bool:
        return bit_is_set(self.status_word, 14)

    @property
    def has_error(self) -> bool:
        return bit_is_set(self.status_word, 15)


def meters_to_hundredth_mm(opening_m: float) -> int:
    """Convert meters to Zimmer position unit (0.01 mm)."""
    return int(round(opening_m / 1e-5))


def hundredth_mm_to_meters(position_units: int) -> float:
    """Convert Zimmer position unit (0.01 mm) to meters."""
    return float(position_units) * 1e-5


def bit_is_set(value: int, bit: int) -> bool:
    """Return True if the bit is set in the integer."""
    return (value & (1 << bit)) != 0


def _u8(value: int) -> int:
    return value & 0xFF


def _u16(value: int) -> int:
    return value & 0xFFFF
