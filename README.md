# Pick Place Imitation Learning

Python app for Wandelbots NOVA with a pick/place loop, Zimmer gripper integration, and optional local RealSense camera API checks.

Current NOVA app name: `pick-place-imitation-learning` (from `.nova`).

## Features

- Pick and place loop with target and randomized table pose
- Zimmer gripper support (real Modbus device) and mock fallback
- Tunable grip, hold, velocity, and grip-gap parameters via `.env`
- Local RealSense API connectivity script without using app UI
- NOVA deployment flow via `nova app install`

## Prerequisites

- Python 3.11+
- `uv` installed
- Docker and NOVA CLI for deployment
- Reachable NOVA host and cell

## Local Run

```bash
cd nova-pick-place-imitation-learning
uv sync
uv run python -m app.pick_and_place
```

## Gripper Parameters

Main runtime parameters are loaded from `.env`:

```bash
ZIMMER_FORCE_PERCENT=2
ZIMMER_HOLD_FORCE_PERCENT=1
ZIMMER_VELOCITY_PERCENT=20
ZIMMER_GRIP_GAP_MM=45.0
```

Meaning:

- `ZIMMER_FORCE_PERCENT`: force used while closing to grip
- `ZIMMER_HOLD_FORCE_PERCENT`: reduced force while carrying
- `ZIMMER_VELOCITY_PERCENT`: jaw movement speed
- `ZIMMER_GRIP_GAP_MM`: target jaw gap during grip (example: `45.0` for 4.5 cm)

When the run starts, console output prints the effective values, for example:

```text
[Gripper] ZimmerGripper @ 172.31.13.49:502 unit=1 io_link_port=0 grip_force=2% hold_force=1% velocity=20% grip_gap=45.0mm
```

## Local RealSense Camera (No App UI)

This project includes `realsense_local_connect.py` for direct backend API checks:

```bash
python3 realsense_local_connect.py
```

Useful options:

```bash
python3 realsense_local_connect.py --no-start
python3 realsense_local_connect.py --keep-stream
python3 realsense_local_connect.py --base-url http://172.31.11.129/cell/realsense/
```

## Deploy to NOVA

```bash
nova config set host wandelbox-hhmnwy
nova config set image-registry registry-1.docker.io/<dockerhub-user>
nova app install
```

After install, open:

- `http://wandelbox-hhmnwy/`
- `http://wandelbox-hhmnwy/cell/pick-place-imitation-learning/`

## Repository Notes

- `.nova` defines the installed app name and metadata.
- `app/pick_and_place.py` is the program entrypoint.
- `app/gripper_helper.py` bridges app code to `zimmer_gripper_controller`.
- `zimmer_gripper_controller/` contains the low-level driver/session implementation.

## Troubleshooting

- `ModuleNotFoundError: No module named nova`:
	Run with `uv run ...` instead of plain `python3`.
- Gripper startup timeout (`diag=0x0301`):
	Check TBEN connectivity, IO-Link port mapping, and actuator readiness.
