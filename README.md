# Nova Pick and Place Demo (Virtual Robot + Data Collection)

<<<<<<< Updated upstream
A Python application for Wandelbots NOVA that demonstrates a pick-and-place workflow with random table repositioning, using a UR10e robot and a Zimmer GEH6060 parallel gripper.

## Features

- **Robot loop**: Home → Pick from fixed target → Place at random table position → Home → Retrieve & return (repeats N cycles)
- **Zimmer GEH6060 gripper**: Real Modbus TCP control via Turck TBEN-S2-4IOL, or mock gripper for simulation
- **TCP compensation**: Poses taught with `OnRobot_Single` TCP are automatically converted to `umi_gripper` TCP at runtime
- **NOVA deployment ready**: FastAPI backend, Docker containerised, runs as a NOVA app

## Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Docker (for deployment to NOVA)
- Wandelbots NOVA CLI: `brew install wandelbotsgmbh/wandelbots/nova` (macOS/Linux) or [download](https://github.com/wandelbotsgmbh/nova-cli/releases) (Windows)
- Access to a NOVA instance (cloud or local)

---

## Quick Start

### 1. Install dependencies

```bash
=======
This repository provides NOVA programs for pick-and-place and cube transfer, Zimmer gripper integration, camera utilities, and data-collection helpers for LeRobot-style datasets.

## What Is Included

- FastAPI NOVA app that registers robot programs.
- Pick-and-place program with random table placement and return-to-target cycle.
- Cube-transfer programs, including a steps-1-3 data-collection variant.
- Zimmer GEH6060 support through `zimmer_gripper_controller`.
- Camera checks and collector config tooling.
- Automated episode collection script with retries and finalize checks.

## Programs Registered by the App

The backend in `app/main.py` registers these program IDs:

- `pick_and_place`
- `cube_transfer_loop`
- `cube_transfer_steps_1_3`

Run backend:

```bash
cd /home/shamreen-tabassum/Documents/nova-pick-place-demo-files/nova-pick-place-demo-virtualRobot
>>>>>>> Stashed changes
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001
```

<<<<<<< Updated upstream
### 2. Configure environment

Edit `.env` with your NOVA and gripper details:
=======
Health/status:

- `GET http://localhost:8001/health`
- `GET http://localhost:8001/status`

## Hardware and Runtime Setup

Create and edit `.env` (copy from `.env.example`):
>>>>>>> Stashed changes

```env
NOVA_API=http://<YOUR_NOVA_IP>
CELL_NAME=cell
ROBOT_CONTROLLER_NAME=ur10e

<<<<<<< Updated upstream
# Zimmer gripper — leave ZIMMER_HOST empty to use MockGripper (simulation)
ZIMMER_HOST=172.31.13.49
=======
# Zimmer gripper (leave empty for MockGripper)
ZIMMER_HOST=<TBEN_IP>
>>>>>>> Stashed changes
ZIMMER_PORT=502
ZIMMER_UNIT_ID=1
ZIMMER_IO_LINK_PORT=0
ZIMMER_FORCE_PERCENT=5
<<<<<<< Updated upstream
ZIMMER_STARTUP_TIMEOUT_S=60
```

### 3. Run the web API backend (registers programs with NOVA)

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open browser: http://localhost:8000

### 4. Run directly from CLI (without NOVA UI)

```bash
uv run python -m app.pick_and_place.pick_and_place
```

---

## Deploy to NOVA

### 1. Build and push the Docker image

```bash
docker build -t YOUR-DOCKERHUB-USERNAME/nova-pick-place-demo:latest .
docker push YOUR-DOCKERHUB-USERNAME/nova-pick-place-demo:latest
```

### 2. Deploy

```bash
nova app install
```

Open your NOVA instance UI — the app appears on the home screen with a **Pick and Place** program.

---

## Gripper Behaviour

The Zimmer GEH6060 jaw gap is set to `TARGET_GAP_M = 0.035 m` (35 mm) when picking.
`close()` positions the jaws at this gap — it does **not** drive to zero (force mode).
`open()` drives to the full 80 mm open position.

Per-cycle sequence:
```
startup       → open  (80 mm)
TARGET_PICK   → close (35 mm) ← grips cube
RANDOM place  → open  (80 mm) ← releases cube
RANDOM pick   → close (35 mm) ← grips cube
TARGET place  → open  (80 mm) ← releases cube
```

Gripper parameters (matched to `minimal_move.py`):

| Parameter | Value |
|---|---|
| `TARGET_GAP_M` | 0.035 m (35 mm) |
| `GRIPPER_SETTLE_S` | 2.0 s |
| `grip_force_percent` | 5 % (min for physical closing) |
| `drive_velocity_percent` | 50 % |

If `ZIMMER_HOST` is empty, `MockGripper` is used automatically — no hardware needed.

---

## Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `NOVA_API` | — | NOVA instance URL, e.g. `http://172.31.11.253` |
| `CELL_NAME` | `cell` | NOVA cell/workspace name |
| `ROBOT_CONTROLLER_NAME` | `ur10e` | Controller name in NOVA |
| `ZIMMER_HOST` | *(empty)* | TBEN-S2-4IOL Modbus IP — empty = MockGripper |
| `ZIMMER_PORT` | `502` | Modbus TCP port |
| `ZIMMER_UNIT_ID` | `1` | Modbus unit ID |
| `ZIMMER_IO_LINK_PORT` | `0` | IO-Link port on TBEN (0–3) |
| `ZIMMER_FORCE_PERCENT` | `5` | Grip force (1–100 %) |
| `ZIMMER_STARTUP_TIMEOUT_S` | `60` | Homing/startup timeout in seconds |
| `RANDOM_RELEASE_EXTRA_DZ_MM` | `10` | Extra Z touchdown depth at random place (mm) |

### Motion speeds

Defined in `app/pick_and_place/pick_and_place.py`:

```python
slow  = MotionSettings(tcp_velocity_limit=50)   # home transitions
avg   = MotionSettings(tcp_velocity_limit=80)   # approach / pick / carry
place = MotionSettings(tcp_velocity_limit=30)   # final descent and touchdown
```

### Workspace bounds

Defined in `app/pick_and_place/pick_and_place_poses.py`:

```python
X_MIN, X_MAX       = -520.2, 507.9   # random table X range (mm)
Y_MIN, Y_MAX       = -522.1, -192.7  # random table Y range (mm)
Z_TABLE_APPROACH   = 450.0           # hover height (mm)
Z_DROP             = 265.0           # table surface drop height (mm)
=======
ZIMMER_HOLD_FORCE_PERCENT=3
ZIMMER_STARTUP_TIMEOUT_S=60
```

Notes:

- If `ZIMMER_HOST` is empty, the app uses `MockGripper`.
- Real camera streams should be visible in NOVA camera app before collection.

## Camera Utilities

Verify cameras through the built-in check:

```bash
uv run python -m app.camera.camera_app_check --cameras-base-url http://<nova-host>/cell/cameras
```

Generate/refresh collector config helpers:

```bash
uv run python data_collection/setup_data_collection.py --nova-data-collection-root /home/shamreen-tabassum/Documents/nova-data-collection
```

## Data Collection Workflow

Start collector (terminal A):

```bash
cd /home/shamreen-tabassum/Documents/nova-data-collection/app
uv sync
uv run nova-collect
```

Collector health:

- `GET http://localhost:8000/health`

Start backend (terminal B):

```bash
cd /home/shamreen-tabassum/Documents/nova-pick-place-demo-files/nova-pick-place-demo-virtualRobot
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Run automated collection (example: 100 episodes):

```bash
cd /home/shamreen-tabassum/Documents/nova-pick-place-demo-files/nova-pick-place-demo-virtualRobot/data_collection
../.venv/bin/python collect_pick_and_place_episodes.py \
	--dataset pick_and_place_100 \
	--target-episodes 100 \
	--stop-session-on-exit
>>>>>>> Stashed changes
```

Default behavior of `collect_pick_and_place_episodes.py`:

<<<<<<< Updated upstream
## Project Structure

```
nova-pick-place-demo/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI backend — registers NOVA programs
│   ├── gripper_helper.py                # MockGripper and ZimmerGripper async wrappers
│   ├── camera/
│   │   ├── __init__.py
│   │   ├── camera_app_check.py          # CLI: check NOVA camera devices
│   │   └── camera_client.py            # CameraClient for NOVA camera API
│   └── pick_and_place/
│       ├── __init__.py
│       ├── pick_and_place.py            # Main NOVA program — robot + gripper loop
│       ├── pick_and_place_env.py        # Env var helpers (load_env_file, env_int, …)
│       ├── pick_and_place_motion.py     # TCP selection + motion execution with retry
│       └── pick_and_place_poses.py      # All pose constants + TCP compensation math
├── zimmer_gripper_controller/           # Zimmer GEH6060 Modbus driver package
│   ├── minimal_move.py                  # Standalone gripper test script
│   └── …
├── data_collection/                     # LeRobot data export helpers
├── cube-imitation-learning/             # Imitation learning subproject
├── pyproject.toml                       # Dependencies (uv)
├── Dockerfile                           # Container build
├── .env                                 # Environment variables (do not commit)
└── README.md
=======
- Uploads collector config from `data_collection/recording_steps_1_3.json`.
- Starts a session.
- For each episode: start episode -> run program -> wait for backend idle -> stop episode.
- Retries transient camera/source failures.
- Writes per-attempt JSONL logs under `data_collection/collection_runs/`.

## Where Data Is Stored

Finalized recordings are stored in the collector repository:

- `/home/shamreen-tabassum/Documents/nova-data-collection/app/recordings/<dataset>/<recording_id>/`

A recording is treated as finalized when both files exist:

- `meta.json`
- `recording.rrd`

## Gripper Testing

Run Zimmer standalone test:

```bash
set -a && source .env && set +a
uv run python zimmer_gripper_controller/minimal_move.py
>>>>>>> Stashed changes
```

## Repository Layout

```text
app/
	main.py
	cube_transfer_loop.py
	gripper_helper.py
	camera/
	pick_and_place/
data_collection/
	collect_pick_and_place_episodes.py
	setup_data_collection.py
	recording_steps_1_3.template.json
zimmer_gripper_controller/
cube-imitation-learning/
```

<<<<<<< Updated upstream
### MockGripper used instead of real gripper
`ZIMMER_HOST` is empty when the program runs. This happens when `.env` is not loaded.
The program loads `.env` from the project root automatically. Verify:
```bash
grep ZIMMER_HOST .env   # should show: ZIMMER_HOST=172.31.13.49
```

### Gripper closes to wrong gap / goes to zero
`close()` must call `session.move_to_gap_m(TARGET_GAP_M)`, not `close_gripper()`.
`close_gripper()` drives jaws to `jaw_gap_min_m = 1 mm` (zero). Check `gripper_helper.py`.

### Robot program fails with `InitMovementFailed`
The controller is in monitor mode. The motion module retries once automatically by
switching to control mode. If it fails repeatedly, check controller state in NOVA UI.

### TCP not found
The program requires `umi_gripper` TCP registered on the controller. Available TCPs are
printed at startup: `Available TCPs: ['OnRobot_Single', 'umi_gripper']`.
Register `umi_gripper` in NOVA UI under controller settings with offset
`(-1.5724, 3.6754, 221.7036, 0, 0, 0)` mm relative to the flange.

### Test the gripper in isolation
```bash
set -a && source .env && set +a
uv run python zimmer_gripper_controller/minimal_move.py
# Expected output:
# Target gap: 0.03000 m
# Actual gap: 0.03002 m
# Diagnosis: 0x0000
```
=======
## Cleanup Notes

Two obsolete top-level helper scripts were removed during cleanup.

Their functionality is covered by maintained tooling in `app/camera/`, `data_collection/`, and `zimmer_gripper_controller/`.
>>>>>>> Stashed changes
