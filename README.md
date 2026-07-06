# Nova Pick and Place Demo

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
uv sync
```

### 2. Configure environment

Edit `.env` with your NOVA and gripper details:

```env
NOVA_API=http://<YOUR_NOVA_IP>
CELL_NAME=cell
ROBOT_CONTROLLER_NAME=ur10e

# Zimmer gripper — leave ZIMMER_HOST empty to use MockGripper (simulation)
ZIMMER_HOST=172.31.13.49
ZIMMER_PORT=502
ZIMMER_UNIT_ID=1
ZIMMER_IO_LINK_PORT=0
ZIMMER_FORCE_PERCENT=5
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
```

---

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
```

---

## Troubleshooting

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
