# Nova Pick and Place Demo (Virtual Robot + Data Collection)

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
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Health/status:

- `GET http://localhost:8001/health`
- `GET http://localhost:8001/status`

## Hardware and Runtime Setup

Create and edit `.env` (copy from `.env.example`):

```env
NOVA_API=http://<YOUR_NOVA_IP>
CELL_NAME=cell
ROBOT_CONTROLLER_NAME=ur10e

# Zimmer gripper (leave empty for MockGripper)
ZIMMER_HOST=<TBEN_IP>
ZIMMER_PORT=502
ZIMMER_UNIT_ID=1
ZIMMER_IO_LINK_PORT=0
ZIMMER_FORCE_PERCENT=5
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
```

Default behavior of `collect_pick_and_place_episodes.py`:

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

## Cleanup Notes

Two obsolete top-level helper scripts were removed during cleanup.

Their functionality is covered by maintained tooling in `app/camera/`, `data_collection/`, and `zimmer_gripper_controller/`.
