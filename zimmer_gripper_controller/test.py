"""Quickstart script for the standalone Zimmer gripper controller package.

This script is intended as a readable reference for new users.
It shows the typical lifecycle:

1. Build a Modbus and session configuration
2. Create a GripperSession
3. Connect and wait until startup is finished
4. Read state
5. Send jaw-gap commands
6. Adjust force and velocity
7. Shut down cleanly

Run example:

    python test.py
"""

from __future__ import annotations

from zimmer_gripper_controller import (
    GripperConfig,
    GripperSession,
    JawGapConfig,
    LimitConfig,
    ModbusConfig,
    SessionConfig,
)


def fmt_mm(value_m: float) -> str:
    return f"{value_m * 1000.0:.2f} mm"


def print_state(prefix: str, session: GripperSession) -> None:
    state = session.state()
    print(
        f"{prefix}: gap={state.jaw_gap_m:.5f} m ({fmt_mm(state.jaw_gap_m)}) | "
        f"device_pos={state.device_position_m:.5f} m ({fmt_mm(state.device_position_m)}) | "
        f"diag=0x{state.diagnosis:04X} | motor={state.motor_on} | motion={state.in_motion}"
    )


def main() -> None:
    # ModbusConfig contains only the communication settings for the TBEN.
    # This script intentionally keeps them hardcoded for quick local testing.
    modbus = ModbusConfig(
        host="172.31.13.49",
        port=502,
        unit_id=1,
        io_link_port=0,
        timeout_s=1.0,
    )

    # JawGapConfig defines the user-facing gripper opening range.
    # These values are intentionally the same defaults used in the interactive CLI.
    jaw_gap = JawGapConfig(
        jaw_gap_min_m=0.00100,
        jaw_gap_max_m=0.08000,
        device_pos_min_m=0.00100,
        device_pos_max_m=0.04000,
    )

    # LimitConfig defines the internal Zimmer device-position range and parameter bounds.
    limits = LimitConfig(
        opening_min_m=jaw_gap.device_pos_min_m,
        opening_max_m=jaw_gap.device_pos_max_m,
        force_min_percent=1,
        force_max_percent=100,
        velocity_min_percent=1,
        velocity_max_percent=100,
    )

    # GripperConfig contains low-level controller behavior and Zimmer mode settings.
    gripper = GripperConfig(
        limits=limits,
        grip_force_percent=5,
        drive_velocity_percent=20,
        device_mode_positioning=50,
        device_mode_force_outside=62,
        device_mode_force_inside=72,
        device_mode_preposition_outside=82,
        device_mode_preposition_inside=92,
        startup_homing_mode=10,
        invert_opening_direction=False,
    )

    # SessionConfig bundles everything into the high-level API.
    config = SessionConfig(
        modbus=modbus,
        gripper=gripper,
        jaw_gap=jaw_gap,
        startup_timeout_s=25.0,
        status_settle_s=5,
    )

    print("Creating GripperSession...")
    with GripperSession(config) as gripper:
        print("Connecting and waiting for startup...")

        # wait_until_ready() blocks until motor-on and startup are complete.
        # It also captures the opening reference needed for jaw-gap control.
        ready_state = gripper.wait_until_ready()
        print(
            f"Ready: open_ref={ready_state.open_reference_position_m:.5f} m | "
            f"direction={ready_state.device_direction_sign:+.0f}"
        )
        print_state("Initial state", gripper)

        # state() returns the high-level session state in jaw-gap coordinates.
        state = gripper.state()
        print(f"Current jaw gap from state(): {state.jaw_gap_m:.5f} m ({fmt_mm(state.jaw_gap_m)})")

        # raw_state() exposes the underlying controller state if low-level details are needed.
        raw = gripper.raw_state()
        print(
            f"Raw state: actual_position={raw.actual_position_hundredth_mm} * 0.01 mm | "
            f"status_word=0x{raw.status_word:04X}"
        )

        print("\n1) open() -> command the configured maximum jaw gap")
        gripper.open(settle_time_s=config.status_settle_s)
        print_state("After open()", gripper)

        print("\n2) move_to_gap_m(0.030) -> move to a specific jaw gap")
        gripper.move_to_gap_m(0.030, settle_time_s=config.status_settle_s)
        print_state("After move_to_gap_m(0.030)", gripper)

        print("\n3) set_force_percent(30) -> change gripping force")
        applied_force = gripper.set_force_percent(5)
        print(f"Applied force: {applied_force}%")

        print("\n4) set_velocity_percent(25) -> change drive velocity")
        applied_velocity = gripper.set_velocity_percent(50)
        print(f"Applied velocity: {applied_velocity}%")

        print("\n5) close_gripper() -> command the configured minimum jaw gap")
        gripper.close_gripper(settle_time_s=config.status_settle_s)
        print_state("After close_gripper()", gripper)

        print("\n6) move_to_gap_m(0.050) -> open again to an intermediate value")
        gripper.move_to_gap_m(0.050, settle_time_s=config.status_settle_s)
        print_state("After move_to_gap_m(0.050)", gripper)

        print("\n7) open the Gripper fully")
        gripper.open(settle_time_s=config.status_settle_s)

        print("\nDone. The context manager will now stop the controller cleanly.")


if __name__ == "__main__":
    main()
