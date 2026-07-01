"""High-level robot-friendly API for jaw-gap based gripper control."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import JawGapConfig, SessionConfig
from .controller import GripperController, GripperState
from .protocol import hundredth_mm_to_meters


@dataclass(slots=True)
class SessionState:
    """User-facing state snapshot expressed in jaw-gap coordinates."""

    connected: bool
    running: bool
    jaw_gap_m: float
    device_position_m: float
    status_word: int
    diagnosis: int
    motor_on: bool
    in_motion: bool
    data_transfer_ok: bool
    has_error: bool
    startup_completed: bool
    last_error_text: str
    last_rx_timestamp: float
    open_reference_position_m: float | None
    device_direction_sign: float | None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def gap_from_device_position_m(
    device_pos_m: float,
    open_ref_pos_m: float,
    gap_cfg: JawGapConfig,
    device_dir_sign: float,
) -> float:
    """Convert Zimmer device position into user-facing jaw gap."""
    jaw_travel_m = max(0.0, device_dir_sign * (device_pos_m - open_ref_pos_m))
    return _clamp(
        gap_cfg.jaw_gap_max_m - 2.0 * jaw_travel_m,
        gap_cfg.jaw_gap_min_m,
        gap_cfg.jaw_gap_max_m,
    )


def device_position_from_gap_m(
    gap_m: float,
    open_ref_pos_m: float,
    gap_cfg: JawGapConfig,
    device_dir_sign: float,
) -> float:
    """Convert user-facing jaw gap into Zimmer device position."""
    clamped_gap_m = _clamp(gap_m, gap_cfg.jaw_gap_min_m, gap_cfg.jaw_gap_max_m)
    return open_ref_pos_m + device_dir_sign * 0.5 * (gap_cfg.jaw_gap_max_m - clamped_gap_m)


def select_device_direction(open_ref_pos_m: float, gap_cfg: JawGapConfig) -> float:
    """Pick the plausible device-position direction for jaw closing."""
    half_span = 0.5 * gap_cfg.jaw_gap_max_m
    close_if_dec = open_ref_pos_m - half_span
    close_if_inc = open_ref_pos_m + half_span

    def outside_distance(pos_m: float) -> float:
        if pos_m < gap_cfg.device_pos_min_m:
            return gap_cfg.device_pos_min_m - pos_m
        if pos_m > gap_cfg.device_pos_max_m:
            return pos_m - gap_cfg.device_pos_max_m
        return 0.0

    dec_score = outside_distance(close_if_dec)
    inc_score = outside_distance(close_if_inc)
    return -1.0 if dec_score <= inc_score else 1.0


class GripperSession:
    """Simple high-level API around the threaded controller."""

    def __init__(
        self,
        config: SessionConfig,
        controller_factory: Callable[..., GripperController] | None = None,
    ):
        self._config = config
        factory = controller_factory or GripperController
        self._controller = factory(modbus=config.modbus, config=config.gripper)
        self._open_ref_pos_m: float | None = None
        self._device_dir_sign: float | None = None

    def __enter__(self) -> GripperSession:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def config(self) -> SessionConfig:
        return self._config

    def connect(self) -> None:
        """Start the low-level controller."""
        self._controller.start()

    def close(self) -> None:
        """Stop the low-level controller."""
        self._controller.stop()

    def wait_until_ready(
        self,
        timeout_s: float | None = None,
        poll_interval_s: float = 0.05,
    ) -> SessionState:
        """Wait for startup completion and capture the open-reference position."""
        timeout = self._config.startup_timeout_s if timeout_s is None else timeout_s
        deadline = time.time() + timeout
        last_state = self._controller.get_state()
        while time.time() < deadline:
            last_state = self._controller.get_state()
            if last_state.startup_completed and last_state.motor_on:
                self._capture_open_reference(last_state)
                self.set_force_percent(self._config.gripper.grip_force_percent)
                self.set_velocity_percent(self._config.gripper.drive_velocity_percent)
                self.open()
                return self.state()
            time.sleep(poll_interval_s)
        error_suffix = (
            f" | last_error={last_state.last_error_text}"
            if last_state.last_error_text
            else ""
        )
        raise TimeoutError(
            "Startup timeout: homing/startup did not complete. "
            f"Last diag=0x{last_state.diagnosis:04X}"
            f"{error_suffix}"
        )

    def move_to_gap_m(self, gap_m: float, settle_time_s: float = 0.0) -> float:
        """Command a jaw-gap target in meters and optionally wait a fixed settle time."""
        self._require_reference()
        assert self._open_ref_pos_m is not None
        assert self._device_dir_sign is not None
        target_pos_m = device_position_from_gap_m(
            gap_m,
            self._open_ref_pos_m,
            self._config.jaw_gap,
            self._device_dir_sign,
        )
        clamped_pos_m = self._controller.set_target_opening_m(target_pos_m)
        clamped_gap_m = gap_from_device_position_m(
            clamped_pos_m,
            self._open_ref_pos_m,
            self._config.jaw_gap,
            self._device_dir_sign,
        )
        self._sleep_settle_time(settle_time_s)
        return clamped_gap_m

    def open(self, settle_time_s: float = 0.0) -> float:
        """Command the configured maximum jaw gap and optionally wait a fixed settle time."""
        return self.move_to_gap_m(self._config.jaw_gap.jaw_gap_max_m, settle_time_s=settle_time_s)

    def close_gripper(self, settle_time_s: float = 0.0) -> float:
        """Command the configured minimum jaw gap and optionally wait a fixed settle time."""
        return self.move_to_gap_m(self._config.jaw_gap.jaw_gap_min_m, settle_time_s=settle_time_s)

    def set_force_percent(self, force_percent: int) -> int:
        """Update target grip force in percent."""
        return self._controller.set_force_percent(force_percent)

    def set_velocity_percent(self, velocity_percent: int) -> int:
        """Update target drive velocity in percent."""
        return self._controller.set_velocity_percent(velocity_percent)

    def state(self) -> SessionState:
        """Return current state in jaw-gap coordinates."""
        raw = self._controller.get_state()
        device_pos_m = hundredth_mm_to_meters(raw.actual_position_hundredth_mm)
        jaw_gap_m = self._jaw_gap_from_state(raw)
        return SessionState(
            connected=raw.connected,
            running=raw.running,
            jaw_gap_m=jaw_gap_m,
            device_position_m=device_pos_m,
            status_word=raw.status_word,
            diagnosis=raw.diagnosis,
            motor_on=raw.motor_on,
            in_motion=raw.in_motion,
            data_transfer_ok=raw.data_transfer_ok,
            has_error=raw.has_error,
            startup_completed=raw.startup_completed,
            last_error_text=raw.last_error_text,
            last_rx_timestamp=raw.last_rx_timestamp,
            open_reference_position_m=self._open_ref_pos_m,
            device_direction_sign=self._device_dir_sign,
        )

    def raw_state(self) -> GripperState:
        """Return the underlying low-level controller state."""
        return self._controller.get_state()

    def _capture_open_reference(self, state: GripperState) -> None:
        open_ref_pos_m = hundredth_mm_to_meters(state.actual_position_hundredth_mm)
        self._open_ref_pos_m = open_ref_pos_m
        self._device_dir_sign = select_device_direction(open_ref_pos_m, self._config.jaw_gap)

    def _jaw_gap_from_state(self, raw: GripperState) -> float:
        if self._open_ref_pos_m is None or self._device_dir_sign is None:
            return self._config.jaw_gap.jaw_gap_max_m
        device_pos_m = hundredth_mm_to_meters(raw.actual_position_hundredth_mm)
        return gap_from_device_position_m(
            device_pos_m,
            self._open_ref_pos_m,
            self._config.jaw_gap,
            self._device_dir_sign,
        )

    def _require_reference(self) -> None:
        if self._open_ref_pos_m is None or self._device_dir_sign is None:
            raise RuntimeError("Open reference not initialized. Call wait_until_ready() first.")

    @staticmethod
    def _sleep_settle_time(settle_time_s: float) -> None:
        if settle_time_s < 0.0:
            raise ValueError("settle_time_s must be >= 0")
        if settle_time_s > 0.0:
            time.sleep(settle_time_s)
