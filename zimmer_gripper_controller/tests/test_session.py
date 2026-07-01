from __future__ import annotations

from dataclasses import replace

import pytest

from zimmer_gripper_controller import (
    GripperConfig,
    GripperSession,
    JawGapConfig,
    LimitConfig,
    ModbusConfig,
    SessionConfig,
)
from zimmer_gripper_controller.controller import GripperState
from zimmer_gripper_controller.protocol import meters_to_hundredth_mm
from zimmer_gripper_controller.session import (
    device_position_from_gap_m,
    gap_from_device_position_m,
    select_device_direction,
)


class FakeController:
    def __init__(self, modbus, config):
        self.modbus = modbus
        self.config = config
        self.started = False
        self.stopped = False
        self.force = config.grip_force_percent
        self.velocity = config.drive_velocity_percent
        self.target_opening = None
        self.state = GripperState(
            connected=True,
            running=True,
            motor_on=True,
            startup_completed=True,
            actual_position_hundredth_mm=meters_to_hundredth_mm(0.039),
        )

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def get_state(self):
        return replace(self.state)

    def set_target_opening_m(self, opening_m: float):
        self.target_opening = opening_m
        self.state = replace(
            self.state,
            actual_position_hundredth_mm=meters_to_hundredth_mm(opening_m),
        )
        return opening_m

    def set_force_percent(self, force_percent: int):
        self.force = force_percent
        return force_percent

    def set_velocity_percent(self, velocity_percent: int):
        self.velocity = velocity_percent
        return velocity_percent


def test_gap_conversion_roundtrip():
    gap_cfg = JawGapConfig()
    open_ref = 0.039
    direction = select_device_direction(open_ref, gap_cfg)
    target_gap = 0.02
    device_pos = device_position_from_gap_m(target_gap, open_ref, gap_cfg, direction)
    recovered_gap = gap_from_device_position_m(device_pos, open_ref, gap_cfg, direction)
    assert recovered_gap == pytest.approx(target_gap)


def test_session_wait_and_move():
    config = SessionConfig(
        modbus=ModbusConfig(host="127.0.0.1"),
        gripper=GripperConfig(limits=LimitConfig(opening_min_m=0.001, opening_max_m=0.04)),
    )
    session = GripperSession(config, controller_factory=FakeController)
    session.connect()
    state = session.wait_until_ready(timeout_s=0.1, poll_interval_s=0.0)
    assert state.startup_completed is True
    clamped_gap = session.move_to_gap_m(0.03)
    assert clamped_gap == 0.03
    assert session.raw_state().actual_position_hundredth_mm == meters_to_hundredth_mm(
        session._controller.target_opening
    )
    session.close()


def test_session_clamps_gap_to_limits():
    config = SessionConfig(
        modbus=ModbusConfig(host="127.0.0.1"),
        gripper=GripperConfig(limits=LimitConfig(opening_min_m=0.001, opening_max_m=0.04)),
    )
    session = GripperSession(config, controller_factory=FakeController)
    session.connect()
    session.wait_until_ready(timeout_s=0.1, poll_interval_s=0.0)
    clamped_gap = session.move_to_gap_m(1.0)
    assert clamped_gap == config.jaw_gap.jaw_gap_max_m


def test_move_to_gap_supports_settle_time():
    config = SessionConfig(
        modbus=ModbusConfig(host="127.0.0.1"),
        gripper=GripperConfig(limits=LimitConfig(opening_min_m=0.001, opening_max_m=0.04)),
    )
    session = GripperSession(config, controller_factory=FakeController)
    session.connect()
    session.wait_until_ready(timeout_s=0.1, poll_interval_s=0.0)
    clamped_gap = session.move_to_gap_m(0.03, settle_time_s=0.0)
    assert clamped_gap == pytest.approx(0.03)
