"""Interactive CLI for Zimmer jaw-gap control."""

from __future__ import annotations

import argparse
import time

from .config import GripperConfig, JawGapConfig, LimitConfig, ModbusConfig, SessionConfig
from .session import GripperSession


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive Zimmer gripper test with fixed safety limits.",
    )
    parser.add_argument("--host", required=True, help="TBEN IP address")
    parser.add_argument("--port", type=int, default=502, help="Modbus TCP port")
    parser.add_argument("--unit-id", type=int, default=1, help="Modbus slave/unit id")
    parser.add_argument(
        "--io-link-port",
        type=int,
        default=0,
        choices=(0, 1, 2, 3),
        help="TBEN IO-Link port index (C0..C3)",
    )
    parser.add_argument("--timeout-s", type=float, default=1.0, help="Modbus timeout in seconds")
    parser.add_argument(
        "--swap-word-bytes",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Swap byte order within each 16-bit Modbus register",
    )
    parser.add_argument(
        "--jaw-gap-min-m",
        type=float,
        default=0.00100,
        help="Minimum jaw gap in meters",
    )
    parser.add_argument(
        "--jaw-gap-max-m",
        type=float,
        default=0.08000,
        help="Maximum jaw gap in meters",
    )
    parser.add_argument(
        "--device-pos-min-m",
        type=float,
        default=0.00100,
        help="Minimum Zimmer device-position coordinate in meters",
    )
    parser.add_argument(
        "--device-pos-max-m",
        type=float,
        default=0.04000,
        help="Maximum Zimmer device-position coordinate in meters",
    )
    parser.add_argument("--force-percent", type=int, default=20, help="Grip force in percent")
    parser.add_argument(
        "--velocity-percent",
        type=int,
        default=15,
        help="Drive velocity in percent",
    )
    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=25.0,
        help="Startup wait timeout in seconds",
    )
    return parser


def _fmt_mm(value_m: float) -> str:
    return f"{value_m * 1000.0:.2f} mm"


def _print_state(session: GripperSession) -> None:
    st = session.state()
    data_transfer_ok = bool(st.status_word & (1 << 12))
    last_to_base = bool(st.status_word & (1 << 13))
    last_to_work = bool(st.status_word & (1 << 14))
    print(
        f"gap={st.jaw_gap_m:.5f} m ({_fmt_mm(st.jaw_gap_m)}) | "
        f"device_pos={st.device_position_m:.5f} m ({_fmt_mm(st.device_position_m)}) | "
        f"diag=0x{st.diagnosis:04X} | motor={st.motor_on} | motion={st.in_motion} | "
        f"error={st.has_error} | startup={st.startup_completed} | dto={data_transfer_ok} | "
        f"last(base/work)=({last_to_base}/{last_to_work})"
    )
    if st.last_error_text:
        print(f"last_error: {st.last_error_text}")


def main() -> None:
    args = build_arg_parser().parse_args()

    jaw_gap = JawGapConfig(
        jaw_gap_min_m=args.jaw_gap_min_m,
        jaw_gap_max_m=args.jaw_gap_max_m,
        device_pos_min_m=args.device_pos_min_m,
        device_pos_max_m=args.device_pos_max_m,
    )
    limits = LimitConfig(
        opening_min_m=jaw_gap.device_pos_min_m,
        opening_max_m=jaw_gap.device_pos_max_m,
        force_min_percent=1,
        force_max_percent=100,
        velocity_min_percent=1,
        velocity_max_percent=100,
    )
    cfg = SessionConfig(
        modbus=ModbusConfig(
            host=args.host,
            port=args.port,
            unit_id=args.unit_id,
            io_link_port=args.io_link_port,
            timeout_s=args.timeout_s,
            swap_word_bytes=args.swap_word_bytes,
        ),
        gripper=GripperConfig(
            limits=limits,
            grip_force_percent=args.force_percent,
            drive_velocity_percent=args.velocity_percent,
            device_mode_force_outside=62,
            device_mode_force_inside=72,
            device_mode_preposition_outside=82,
            device_mode_preposition_inside=92,
            startup_homing_mode=10,
            invert_opening_direction=False,
            device_mode_positioning=50,
        ),
        jaw_gap=jaw_gap,
        startup_timeout_s=args.startup_timeout_s,
    )

    session = GripperSession(cfg)
    print("Starting controller...")
    session.connect()
    print("Controller started")

    try:
        print("Waiting for startup to complete...")
        state = session.wait_until_ready()
        homing = cfg.gripper.startup_homing_mode
        print(
            "Limits "
            f"gap=[{jaw_gap.jaw_gap_min_m:.5f}, {jaw_gap.jaw_gap_max_m:.5f}] m "
            f"([{_fmt_mm(jaw_gap.jaw_gap_min_m)}, {_fmt_mm(jaw_gap.jaw_gap_max_m)}]) | "
            f"device=[{jaw_gap.device_pos_min_m:.5f}, {jaw_gap.device_pos_max_m:.5f}] m"
        )
        print(
            f"Force={cfg.gripper.grip_force_percent}% | "
            f"Velocity={cfg.gripper.drive_velocity_percent}% | "
            f"Homing={homing if homing is not None else 'off'}"
        )
        direction = (
            "decrease-on-close"
            if state.device_direction_sign is not None and state.device_direction_sign < 0
            else "increase-on-close"
        )
        print(
            "Startup reference "
            f"open_ref_pos={state.open_reference_position_m:.5f} m "
            f"({_fmt_mm(state.open_reference_position_m or 0.0)}) | "
            f"device_dir={direction}"
        )
        print(f"Modbus word byte swap={'on' if args.swap_word_bytes else 'off'}")
        print('Enter jaw gap in meters, "status", or "q" to quit.')
        time.sleep(cfg.status_settle_s)
        _print_state(session)

        while True:
            user_input = input("opening_m> ").strip()
            if not user_input:
                continue

            cmd = user_input.lower()
            if cmd in {"q", "quit", "exit"}:
                break
            if cmd in {"status", "s"}:
                _print_state(session)
                continue
            if cmd in {"open", "o"}:
                clamped_gap_m = session.open()
            elif cmd in {"close", "c"}:
                clamped_gap_m = session.close_gripper()
            else:
                try:
                    requested_gap_m = float(user_input)
                except ValueError:
                    print(
                        'Invalid input. Enter jaw gap as float in meters, '
                        '"status", "open", "close", or "q".'
                    )
                    continue
                clamped_gap_m = session.move_to_gap_m(requested_gap_m)
                print(
                    "Requested gap "
                    f"{requested_gap_m:.5f} m ({_fmt_mm(requested_gap_m)}) | "
                    f"target gap {clamped_gap_m:.5f} m ({_fmt_mm(clamped_gap_m)})"
                )
                time.sleep(cfg.status_settle_s)
                _print_state(session)
                continue

            print(f"Target gap {clamped_gap_m:.5f} m ({_fmt_mm(clamped_gap_m)})")
            time.sleep(cfg.status_settle_s)
            _print_state(session)

    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        print("Stopping controller...")
        session.close()
        print("Controller stopped")


if __name__ == "__main__":
    main()
