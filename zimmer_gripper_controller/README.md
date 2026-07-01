# Zimmer Gripper Controller

Standalone Python implementation to control a Zimmer gripper through a Turck `TBEN-S2-4IOL` IO-Link master.

The package provides two layers:

- a low-level threaded controller for direct Zimmer process-data control
- a high-level jaw-gap based session API for robot applications

The design goal is low complexity:

- one thread for receiving state continuously
- one thread for sending commands continuously
- user-facing jaw-gap commands in meters
- software limits for travel, gripping force, and velocity

This package is used directly by the top-level app in this repository (`app/gripper_helper.py`).

## Architecture

- `PC -> Modbus TCP -> TBEN-S2-4IOL -> IO-Link -> Zimmer gripper`
- The TBEN is used as a transport bridge.
- `DeviceMode` belongs to the Zimmer gripper logic, not to TBEN setup.

## Setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

## Interactive CLI

The CLI is the integrated standalone variant of the interactive `set_opening.py` workflow.

```bash
python -m zimmer_gripper_controller.cli --host 10.0.0.5
```

Supported commands:

- floating-point jaw-gap value in meters, for example `0.025`
- `status`
- `open`
- `close`
- `q`

Important defaults:

- jaw gap range: `0.00100 .. 0.08000 m`
- device-position range: `0.00100 .. 0.04000 m`
- force: `20 %`
- velocity: `15 %`
- startup timeout: `25 s`

Note: The top-level app may override these defaults in its wrapper configuration
for specific hardware tuning (for example different jaw minimums, force, or velocity).

## Python API

Use `GripperSession` for robot-facing code.

```python
from zimmer_gripper_controller import GripperSession, ModbusConfig, SessionConfig

config = SessionConfig(
    modbus=ModbusConfig(host="10.0.0.5", io_link_port=0),
)

with GripperSession(config) as gripper:
    gripper.wait_until_ready()
    gripper.move_to_gap_m(0.025, settle_time_s=2.0)
    state = gripper.state()
    print(state.jaw_gap_m, state.diagnosis)
```

If you want a simple blocking pause after a move, pass `settle_time_s` to `move_to_gap_m()`, `open()`, or `close_gripper()`.

You can also use the low-level `GripperController` directly if you want Zimmer device-position control instead of jaw-gap commands.

## Runtime Parameters That Affect Holding

At runtime, these values are written to the output process data during controller handshakes:

- `grip_force_percent`
- `drive_velocity_percent`

They are clamped by `LimitConfig` ranges and then transmitted through `OutputPDU`
as `grip_force` and `drive_velocity`.

## Safety Notes

- Always validate jaw-gap and device-position limits on the real machine before unattended operation.
- Keep STO and the power safety chain outside this software.
- If `Diagnosis` reports errors such as `0x0100`, check actuator power and wiring first.
