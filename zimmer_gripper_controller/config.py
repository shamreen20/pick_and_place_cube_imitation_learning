"""Configuration models for the Zimmer gripper controller."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ModbusConfig:
    """Connection and register mapping for Turck TBEN-S2-4IOL over Modbus TCP."""

    host: str
    port: int = 502
    unit_id: int = 1
    io_link_port: int = 0
    timeout_s: float = 1.0
    swap_word_bytes: bool = False

    @property
    def input_base_register(self) -> int:
        """Return base input register for the selected IO-Link port."""
        return 0x0002 + self.io_link_port * 0x10

    @property
    def output_base_register(self) -> int:
        """Return base output register for the selected IO-Link port."""
        return 0x0801 + self.io_link_port * 0x10


@dataclass(slots=True)
class LimitConfig:
    """Software limits for opening, gripping force, and velocity."""

    opening_min_m: float
    opening_max_m: float
    force_min_percent: int = 1
    force_max_percent: int = 100
    velocity_min_percent: int = 1
    velocity_max_percent: int = 100


@dataclass(slots=True)
class GripperConfig:
    """Zimmer process parameters and control behavior defaults."""

    limits: LimitConfig
    position_tolerance_hundredth_mm: int = 50
    grip_force_percent: int = 20
    drive_velocity_percent: int = 15
    workpiece_no: int = 0
    device_mode_positioning: int = 50
    device_mode_force_outside: int = 62
    device_mode_force_inside: int = 72
    device_mode_preposition_outside: int = 82
    device_mode_preposition_inside: int = 92
    startup_homing_mode: int | None = 10
    invert_opening_direction: bool = False
    receive_cycle_s: float = 0.03
    send_cycle_s: float = 0.03
    command_deadband_m: float = 0.00003


@dataclass(slots=True)
class JawGapConfig:
    """User-facing jaw-gap model and derived device-position limits."""

    jaw_gap_min_m: float = 0.00100
    jaw_gap_max_m: float = 0.08000
    device_pos_min_m: float = 0.00100
    device_pos_max_m: float = 0.04000


@dataclass(slots=True)
class SessionConfig:
    """High-level session configuration for robot-facing usage."""

    modbus: ModbusConfig
    gripper: GripperConfig = field(
        default_factory=lambda: GripperConfig(
            limits=LimitConfig(opening_min_m=0.00100, opening_max_m=0.04000),
        )
    )
    jaw_gap: JawGapConfig = field(default_factory=JawGapConfig)
    startup_timeout_s: float = 25.0
    status_settle_s: float = 0.25
