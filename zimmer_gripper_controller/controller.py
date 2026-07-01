"""Threaded gripper controller."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass

from .client import TbenModbusClient
from .config import GripperConfig, ModbusConfig
from .protocol import (
    CW_DATA_TRANSFER,
    CW_MOVE_TO_BASE,
    CW_MOVE_TO_WORK,
    CW_NONE,
    CW_RESET_DIRECTION_FLAG,
    InputPDU,
    OutputPDU,
    hundredth_mm_to_meters,
    meters_to_hundredth_mm,
)


@dataclass(slots=True)
class GripperState:
    """Latest state snapshot of the gripper."""

    connected: bool = False
    running: bool = False
    status_word: int = 0
    diagnosis: int = 0
    actual_position_hundredth_mm: int = 0
    actual_opening_m: float = 0.0
    motor_on: bool = False
    in_motion: bool = False
    data_transfer_ok: bool = False
    has_error: bool = False
    startup_completed: bool = False
    last_error_text: str = ""
    last_rx_timestamp: float = 0.0


class GripperController:
    """Simple threaded controller for Zimmer GEH/GED grippers."""

    _RECOVERABLE_DIAGNOSES = {0x0301, 0x0305, 0x0306, 0x0307, 0x0308, 0x0313}

    def __init__(self, modbus: ModbusConfig, config: GripperConfig):
        self._client = TbenModbusClient(modbus)
        self._cfg = config

        self._stop_event = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None

        self._lock = threading.Lock()
        self._state = GripperState()

        min_m = self._cfg.limits.opening_min_m
        self._target_opening_m = self._to_device_opening(self._clamp_opening(min_m))
        self._target_force_percent = self._clamp_force(self._cfg.grip_force_percent)
        self._target_velocity_percent = self._clamp_velocity(self._cfg.drive_velocity_percent)

        self._rx_pdu = InputPDU(status_word=0, diagnosis=0, actual_position=0)
        self._tx_pdu = self._build_default_output_pdu()

        self._startup_completed = False
        self._pending_handshake = False
        self._handshake_apply_runtime_parameters = False
        self._handshake_phase = "idle"
        self._handshake_clear_wait_cycles = 0
        self._pending_direction_reset = False
        self._direction_reset_phase = "idle"
        self._direction_reset_wait_cycles = 0
        self._fault_recovery_active = False
        self._startup_homing_done = self._cfg.startup_homing_mode is None
        self._startup_homing_in_progress = False
        self._startup_homing_settle_cycles = 0
        self._runtime_parameters_initialized = False
        self._startup_runtime_handshake_started = False
        self._recoverable_recovery_active = False
        self._target_was_set_by_user = False
        self._startup_target_synced = False

    def start(self) -> None:
        """Connect and start both control loops."""
        if self._state.running:
            return

        if not self._client.connect():
            raise RuntimeError("Could not connect to Modbus server")

        with self._lock:
            self._state.connected = True
            self._state.running = True

        self._stop_event.clear()
        self._rx_thread = threading.Thread(
            target=self._receive_loop,
            name="gripper-rx",
            daemon=True,
        )
        self._tx_thread = threading.Thread(
            target=self._send_loop,
            name="gripper-tx",
            daemon=True,
        )
        self._rx_thread.start()
        self._tx_thread.start()

    def stop(self) -> None:
        """Stop both loops and close Modbus connection."""
        self._stop_event.set()
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=2.0)
        if self._tx_thread is not None:
            self._tx_thread.join(timeout=2.0)
        self._client.close()
        with self._lock:
            self._state.running = False
            self._state.connected = False

    def set_target_opening_m(self, opening_m: float) -> float:
        """Set target opening in meters and return the clamped value."""
        clamped = self._clamp_opening(opening_m)
        with self._lock:
            self._target_opening_m = self._to_device_opening(clamped)
            self._target_was_set_by_user = True
        return clamped

    def set_force_percent(self, force_percent: int) -> int:
        """Set target grip force in percent and return the clamped value."""
        clamped = self._clamp_force(force_percent)
        with self._lock:
            self._target_force_percent = clamped
            self._request_handshake(apply_runtime_parameters=True)
        return clamped

    def set_velocity_percent(self, velocity_percent: int) -> int:
        """Set target drive velocity in percent and return the clamped value."""
        clamped = self._clamp_velocity(velocity_percent)
        with self._lock:
            self._target_velocity_percent = clamped
            self._request_handshake(apply_runtime_parameters=True)
        return clamped

    def get_state(self) -> GripperState:
        """Return a thread-safe copy of the latest state."""
        with self._lock:
            return GripperState(**asdict(self._state))

    def _receive_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                rx = self._client.read_input_pdu()
                now = time.time()
                with self._lock:
                    self._rx_pdu = rx
                    self._state.status_word = rx.status_word
                    self._state.diagnosis = rx.diagnosis
                    self._state.actual_position_hundredth_mm = rx.actual_position
                    device_opening_m = hundredth_mm_to_meters(rx.actual_position)
                    self._state.actual_opening_m = self._to_user_opening(device_opening_m)
                    self._state.motor_on = rx.motor_on
                    self._state.in_motion = rx.in_motion
                    self._state.data_transfer_ok = rx.data_transfer_ok
                    self._state.has_error = rx.has_error or rx.diagnosis not in (
                        0x0000,
                        0x0001,
                        0x0305,
                    )
                    self._state.last_rx_timestamp = now
                    self._state.last_error_text = (
                        f"Diagnosis=0x{rx.diagnosis:04X}" if self._state.has_error else ""
                    )
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._state.last_error_text = str(exc)
            time.sleep(self._cfg.receive_cycle_s)

    def _send_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    rx = self._rx_pdu
                    self._state.startup_completed = self._startup_completed
                self._advance_control_state(rx)
                self._client.write_output_pdu(self._tx_pdu)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._state.last_error_text = str(exc)
            time.sleep(self._cfg.send_cycle_s)

    def _advance_control_state(self, rx: InputPDU) -> None:
        if rx.diagnosis in (0x0000, 0x0001):
            self._recoverable_recovery_active = False
        elif (
            self._startup_completed
            and rx.diagnosis in self._RECOVERABLE_DIAGNOSES
            and not self._recoverable_recovery_active
            and not self._pending_handshake
        ):
            self._request_handshake(apply_runtime_parameters=True)
            self._recoverable_recovery_active = True

        if self._is_fault_active(rx):
            self._fault_recovery_active = True
            self._startup_completed = False
            self._startup_homing_done = self._cfg.startup_homing_mode is None
            self._startup_homing_in_progress = False
            self._startup_homing_settle_cycles = 0
            self._runtime_parameters_initialized = False
            self._startup_runtime_handshake_started = False
            self._startup_target_synced = False
            self._tx_pdu.device_mode = 2
            self._request_handshake(apply_runtime_parameters=False)

        if self._pending_handshake:
            self._run_handshake(rx)
            return

        if not self._startup_completed:
            if self._fault_recovery_active and self._is_fault_active(rx):
                self._tx_pdu.control_word = CW_NONE
                return
            self._fault_recovery_active = False
            self._run_startup(rx)
            return

        if self._pending_direction_reset:
            self._run_direction_reset(rx)
            return

        self._run_motion_control(rx)

    def _run_startup(self, rx: InputPDU) -> None:
        if not rx.motor_on:
            self._tx_pdu.device_mode = 3
            self._request_handshake(apply_runtime_parameters=False)
            self._run_handshake(rx)
            return

        if self._cfg.startup_homing_mode is not None and not self._startup_homing_done:
            if not self._startup_homing_in_progress:
                self._tx_pdu.device_mode = self._cfg.startup_homing_mode
                self._request_handshake(apply_runtime_parameters=False)
                self._startup_homing_in_progress = True
                self._startup_homing_settle_cycles = 0
                return

            if self._pending_handshake:
                self._tx_pdu.control_word = CW_NONE
                return

            if rx.in_motion or rx.diagnosis in (0x0305, 0x0306):
                self._startup_homing_settle_cycles = 0
                self._tx_pdu.control_word = CW_NONE
                return

            if rx.diagnosis in (0x0000, 0x0001):
                self._startup_homing_settle_cycles += 1
                if self._startup_homing_settle_cycles >= 3:
                    self._startup_homing_done = True
                    self._startup_homing_in_progress = False
                self._tx_pdu.control_word = CW_NONE
                return

            self._request_handshake(apply_runtime_parameters=True)
            return

        if not self._runtime_parameters_initialized:
            if self._startup_runtime_handshake_started and not self._pending_handshake:
                self._runtime_parameters_initialized = True
                self._startup_completed = True
                return

            self._tx_pdu.device_mode = self._cfg.device_mode_positioning
            self._request_handshake(apply_runtime_parameters=True)
            self._startup_runtime_handshake_started = True
            return

        self._startup_completed = True

    def _run_handshake(self, rx: InputPDU) -> None:
        if self._handshake_phase == "idle":
            if self._handshake_apply_runtime_parameters:
                self._apply_runtime_parameters()
            self._tx_pdu.control_word = CW_DATA_TRANSFER
            self._handshake_phase = "set"
            self._handshake_clear_wait_cycles = 0
            return

        if self._handshake_phase == "set":
            if rx.data_transfer_ok:
                self._tx_pdu.control_word = CW_NONE
                self._handshake_phase = "clear"
                self._handshake_clear_wait_cycles = 0
            return

        if self._handshake_phase == "clear":
            self._handshake_clear_wait_cycles += 1
            if not rx.data_transfer_ok:
                self._handshake_phase = "idle"
                self._pending_handshake = False
                self._handshake_apply_runtime_parameters = False
                self._handshake_clear_wait_cycles = 0
                return

            if self._handshake_clear_wait_cycles >= 15:
                self._tx_pdu.control_word = CW_NONE
                self._handshake_phase = "idle"
                self._pending_handshake = False
                self._handshake_apply_runtime_parameters = False
                self._handshake_clear_wait_cycles = 0

    def _run_direction_reset(self, rx: InputPDU) -> None:
        if self._direction_reset_phase == "idle":
            self._tx_pdu.control_word = CW_RESET_DIRECTION_FLAG
            self._direction_reset_phase = "set"
            return

        if self._direction_reset_phase == "set":
            self._tx_pdu.control_word = CW_NONE
            self._direction_reset_phase = "clear"
            return

        if self._direction_reset_phase == "clear":
            self._direction_reset_wait_cycles = 0
            if not rx.last_cmd_to_base and not rx.last_cmd_to_work:
                self._pending_direction_reset = False
                self._direction_reset_phase = "idle"
                return
            self._direction_reset_phase = "wait"
            return

        if self._direction_reset_phase == "wait":
            self._direction_reset_wait_cycles += 1
            if (
                (not rx.last_cmd_to_base and not rx.last_cmd_to_work)
                or self._direction_reset_wait_cycles >= 8
            ):
                self._pending_direction_reset = False
                self._direction_reset_phase = "idle"

    def _run_motion_control(self, rx: InputPDU) -> None:
        if not self._startup_target_synced and not self._target_was_set_by_user:
            self._target_opening_m = hundredth_mm_to_meters(rx.actual_position)
            self._startup_target_synced = True
            self._tx_pdu.control_word = CW_NONE
            return

        min_units = meters_to_hundredth_mm(self._cfg.limits.opening_min_m)
        max_units = meters_to_hundredth_mm(self._cfg.limits.opening_max_m)

        requested_target_units = meters_to_hundredth_mm(self._target_opening_m)
        safe_target_units = min(max_units - 2, max(min_units + 2, requested_target_units))

        target_m = hundredth_mm_to_meters(safe_target_units)
        current_m = hundredth_mm_to_meters(rx.actual_position)
        delta_m = target_m - current_m

        if rx.in_motion:
            return

        if abs(delta_m) <= self._cfg.command_deadband_m:
            self._tx_pdu.control_word = CW_NONE
            return

        if delta_m > 0:
            desired_base = min_units
            desired_work = safe_target_units
            desired_shift = self._compute_shift_position(desired_base, desired_work)
            desired_teach = desired_shift

            updated = self._set_motion_positions(
                base=desired_base,
                shift=desired_shift,
                teach=desired_teach,
                work=desired_work,
            )
            if updated:
                self._request_handshake(apply_runtime_parameters=False)
                self._tx_pdu.control_word = CW_NONE
                return

            if rx.last_cmd_to_work:
                self._request_direction_reset()
                self._tx_pdu.control_word = CW_NONE
            else:
                self._tx_pdu.control_word = CW_MOVE_TO_WORK
            return

        desired_base = safe_target_units
        desired_work = max_units
        desired_shift = self._compute_shift_position(desired_base, desired_work)
        desired_teach = desired_shift

        updated = self._set_motion_positions(
            base=desired_base,
            shift=desired_shift,
            teach=desired_teach,
            work=desired_work,
        )
        if updated:
            self._request_handshake(apply_runtime_parameters=False)
            self._tx_pdu.control_word = CW_NONE
            return

        if rx.last_cmd_to_base:
            self._request_direction_reset()
            self._tx_pdu.control_word = CW_NONE
        else:
            self._tx_pdu.control_word = CW_MOVE_TO_BASE

    def _set_motion_positions(self, *, base: int, shift: int, teach: int, work: int) -> bool:
        base, shift, work = self._normalize_positions(base, shift, work)

        updated = False
        if self._tx_pdu.base_position != base:
            self._tx_pdu.base_position = base
            updated = True
        if self._tx_pdu.shift_position != shift:
            self._tx_pdu.shift_position = shift
            updated = True
        if self._tx_pdu.teach_position != teach:
            self._tx_pdu.teach_position = teach
            updated = True
        if self._tx_pdu.work_position != work:
            self._tx_pdu.work_position = work
            updated = True

        return updated

    def _apply_runtime_parameters(self) -> None:
        self._tx_pdu.device_mode = self._cfg.device_mode_positioning
        self._tx_pdu.workpiece_no = self._cfg.workpiece_no
        self._tx_pdu.position_tolerance = self._cfg.position_tolerance_hundredth_mm
        self._tx_pdu.grip_force = self._target_force_percent
        self._tx_pdu.drive_velocity = self._target_velocity_percent

        min_units = meters_to_hundredth_mm(self._cfg.limits.opening_min_m)
        max_units = meters_to_hundredth_mm(self._cfg.limits.opening_max_m)
        midpoint = self._compute_shift_position(min_units, max_units)
        self._tx_pdu.base_position = min_units
        self._tx_pdu.shift_position = midpoint
        self._tx_pdu.teach_position = midpoint
        self._tx_pdu.work_position = max_units

    def _build_default_output_pdu(self) -> OutputPDU:
        min_units = meters_to_hundredth_mm(self._cfg.limits.opening_min_m)
        max_units = meters_to_hundredth_mm(self._cfg.limits.opening_max_m)
        midpoint = self._compute_shift_position(min_units, max_units)
        return OutputPDU(
            control_word=CW_NONE,
            device_mode=self._cfg.device_mode_positioning,
            workpiece_no=self._cfg.workpiece_no,
            reserve=0,
            position_tolerance=self._cfg.position_tolerance_hundredth_mm,
            grip_force=self._target_force_percent,
            drive_velocity=self._target_velocity_percent,
            base_position=min_units,
            shift_position=midpoint,
            teach_position=midpoint,
            work_position=max_units,
        )

    def _clamp_opening(self, opening_m: float) -> float:
        return max(self._cfg.limits.opening_min_m, min(self._cfg.limits.opening_max_m, opening_m))

    def _to_device_opening(self, opening_m: float) -> float:
        opening_m = self._clamp_opening(opening_m)
        if not self._cfg.invert_opening_direction:
            return opening_m
        min_m = self._cfg.limits.opening_min_m
        max_m = self._cfg.limits.opening_max_m
        return (min_m + max_m) - opening_m

    def _to_user_opening(self, device_opening_m: float) -> float:
        device_opening_m = self._clamp_opening(device_opening_m)
        if not self._cfg.invert_opening_direction:
            return device_opening_m
        min_m = self._cfg.limits.opening_min_m
        max_m = self._cfg.limits.opening_max_m
        return (min_m + max_m) - device_opening_m

    def _clamp_force(self, force_percent: int) -> int:
        lo = self._cfg.limits.force_min_percent
        hi = self._cfg.limits.force_max_percent
        return max(lo, min(hi, int(force_percent)))

    def _clamp_velocity(self, velocity_percent: int) -> int:
        lo = self._cfg.limits.velocity_min_percent
        hi = self._cfg.limits.velocity_max_percent
        return max(lo, min(hi, int(velocity_percent)))

    def _request_handshake(self, *, apply_runtime_parameters: bool) -> None:
        self._pending_handshake = True
        self._handshake_apply_runtime_parameters = (
            self._handshake_apply_runtime_parameters or apply_runtime_parameters
        )

    def _request_direction_reset(self) -> None:
        self._pending_direction_reset = True
        self._direction_reset_phase = "idle"
        self._direction_reset_wait_cycles = 0

    @staticmethod
    def _compute_shift_position(base: int, work: int) -> int:
        return base + max(1, (work - base) // 2)

    @staticmethod
    def _normalize_positions(base: int, shift: int, work: int) -> tuple[int, int, int]:
        if work <= base + 1:
            work = base + 2
        if shift <= base:
            shift = base + 1
        if shift >= work:
            shift = work - 1
        return base, shift, work

    @staticmethod
    def _is_fault_active(rx: InputPDU) -> bool:
        return rx.diagnosis not in (0x0000, 0x0001, 0x0301, 0x0305, 0x0306, 0x0307, 0x0308, 0x0313)
