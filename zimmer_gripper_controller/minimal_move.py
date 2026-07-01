"""Minimal script to move the gripper to a single jaw-gap target."""

from __future__ import annotations

from zimmer_gripper_controller import (
    GripperConfig,
    GripperSession,
    JawGapConfig,
    LimitConfig,
    ModbusConfig,
    SessionConfig,
)

TARGET_GAP_M = 0.030
SETTLE_TIME_S = 2.0


def main() -> None:
    modbus = ModbusConfig(
        host="172.31.13.49",
        port=502,
        unit_id=1,
        io_link_port=0,
        timeout_s=1.0,
    )

    jaw_gap = JawGapConfig(
        jaw_gap_min_m=0.00100,
        jaw_gap_max_m=0.08000,
        device_pos_min_m=0.00100,
        device_pos_max_m=0.04000,
    )

    limits = LimitConfig(
        opening_min_m=jaw_gap.device_pos_min_m,
        opening_max_m=jaw_gap.device_pos_max_m,
        force_min_percent=1,
        force_max_percent=100,
        velocity_min_percent=1,
        velocity_max_percent=100,
    )

    config = SessionConfig(
        modbus=modbus,
        gripper=GripperConfig(
            limits=limits,
            grip_force_percent=5,
            drive_velocity_percent=50,
            device_mode_positioning=50,
            device_mode_force_outside=62,
            device_mode_force_inside=72,
            device_mode_preposition_outside=82,
            device_mode_preposition_inside=92,
            startup_homing_mode=10,
            invert_opening_direction=False,
        ),
        jaw_gap=jaw_gap,
        startup_timeout_s=25.0,
    )

    with GripperSession(config) as gripper:
        gripper.wait_until_ready()
        gripper.move_to_gap_m(TARGET_GAP_M, settle_time_s=SETTLE_TIME_S)
        state = gripper.state()
        print(f"Target gap: {TARGET_GAP_M:.5f} m")
        print(f"Actual gap: {state.jaw_gap_m:.5f} m")
        print(f"Diagnosis: 0x{state.diagnosis:04X}")

        gripper.close_gripper(settle_time_s=SETTLE_TIME_S)
        gripper.open(settle_time_s=SETTLE_TIME_S)



if __name__ == "__main__":
    main()
