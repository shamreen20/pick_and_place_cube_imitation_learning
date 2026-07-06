# Cube Transfer Data Collection Guide (Virtual Robot + Zimmer + RealSense + LeRobot)

This guide connects:
- Robot program in `app/cube_transfer_loop.py`
- NOVA Data Collection service in `/home/shamreen-tabassum/Documents/nova-data-collection`
- RealSense cameras through the NOVA camera gateway
- LeRobot export for training data

## 0) Programs in this repo

- Full loop (steps 1-5): program id `cube_transfer_loop`
- Data-collection loop (steps 1-3): program id `cube_transfer_steps_1_3`

For data collection, use `cube_transfer_steps_1_3` so episodes only cover:
1. Home
2. Pick at target, place random, store random pose
3. Return home

## 1) Start the collector service

In terminal A:

1. Open collector app folder:
   - `cd /home/shamreen-tabassum/Documents/nova-data-collection/app`
2. Prepare env:
   - `cp .env.template .env`
3. Edit `.env` values:
   - `NOVA_API=<your nova host>`
   - `CELL_NAME=cell`
   - `SERVE_GRPC_PORT=9876`
   - `RERUN_VIEWER_ENABLED=true`
4. Start collector:
   - `uv sync`
   - `uv run nova-collect`

Check it is up:
- `http://localhost:8000/health`

Optional automation (recommended):
- `uv run python data_collection/setup_data_collection.py --nova-data-collection-root /home/shamreen-tabassum/Documents/nova-data-collection`

This creates/updates:
- `/home/shamreen-tabassum/Documents/nova-data-collection/app/.env`
- `/home/shamreen-tabassum/Documents/nova-data-collection/export-service/.env`

## 2) Start your virtual-robot app (with programs)

In terminal B:

1. Go to this project:
   - `cd /home/shamreen-tabassum/Documents/nova-pick-place-demo-files/nova-pick-place-demo-virtualRobot`
2. Prepare env:
   - `cp .env.example .env`
3. Edit `.env` for robot + Zimmer:
   - `NOVA_API=<your nova host>`
   - `CELL_NAME=cell`
   - `ZIMMER_HOST=<tben ip>`
   - `ZIMMER_PORT=502`
   - `ZIMMER_UNIT_ID=1`
4. Start app:
   - `uv sync`
   - `uv run uvicorn app.main:app --host 0.0.0.0 --port 8001`

## 3) Attach RealSense cameras and verify in camera app

Physical steps:
1. Connect RealSense camera(s) to host/IPC USB.
2. Open NOVA camera app and confirm each camera is visible and streaming.

CLI verification from this repo:
- `uv run python -m app.camera_app_check --cameras-base-url http://<nova-host>/cell/cameras`

Generate 3-camera recording config automatically:
- `uv run python data_collection/setup_data_collection.py --nova-data-collection-root /home/shamreen-tabassum/Documents/nova-data-collection --cameras-base-url http://<nova-host>/cell/cameras --generate-recording-config`

The output lists:
- `provider_url`
- `original_device_id`

Use those values in recording config:
- `base_url` = provider URL root with `/api` suffix as required by the provider endpoint you use (for many setups this is `http://<host>/cell/realsense/api`)
- `device_id` = original device id from camera list

## 4) Create recording config for steps 1-3

1. Copy template:
   - `cp data_collection/recording_steps_1_3.template.json data_collection/recording_steps_1_3.json`
2. Edit if needed:
   - `motion_group` (example `0@ur10e`)
   - camera `base_url`
   - camera `device_id` for top/wrist/side cameras
   - metadata dataset/task/operator

Push config to collector:
- `curl -X POST http://localhost:8000/api/v1/config -H "Content-Type: application/json" -d @data_collection/recording_steps_1_3.json`

## 5) Start session and collect 1000 episodes (steps 1-3)

Use the collector session API:

1. Start session:
- `curl -X POST http://localhost:8000/api/v1/session/start -H "Content-Type: application/json" -d '{"dataset":"cube_steps_1_3_1000","task":"cube-transfer-steps-1-3","operator":"shamreen"}'`

2. For each episode (repeat 1000 times):
- Start collector episode:
  - `curl -X POST http://localhost:8000/api/v1/episodes/start -H "Content-Type: application/json" -d '{"lookback_s":0.0}'`
- Run robot program `cube_transfer_steps_1_3` once (count=1) from NOVA/Novax program endpoint or UI.
- If success, save:
  - `curl -X POST http://localhost:8000/api/v1/episodes/stop`
- If failure, discard:
  - `curl -X POST http://localhost:8000/api/v1/episodes/discard`

3. Stop session at the end:
- `curl -X POST http://localhost:8000/api/v1/session/stop`

## 6) Export to LeRobot

Start export service first (terminal C):

1. Open export-service folder:
   - `cd /home/shamreen-tabassum/Documents/nova-data-collection/export-service`
2. Create `.env` (same NOVA host/cell):
   - `NOVA_API=<your nova host>`
   - `CELL_NAME=cell`
   - `CATALOG_URL=`
   - `PORT=8080`
3. Run service:
   - `uv sync`
   - `uv run python -m nova_export.main`

1. Copy export template:
- `cp data_collection/lerobot_export_steps_1_3.template.json data_collection/lerobot_export_steps_1_3.json`

2. Register export config on export service:
- `curl -X POST http://localhost:8080/api/v1/export/config -H "Content-Type: application/json" -d @data_collection/lerobot_export_steps_1_3.json`

3. Trigger export:
- `curl -X POST http://localhost:8080/api/v1/export -H "Content-Type: application/json" -d '{"dataset":"cube_steps_1_3_1000"}'`

## 7) Why cameras are required

- The cube pose changes every episode (random placement), so image observations are needed.
- Policy learns visual state -> action mapping, not only fixed coordinates.
- Cameras improve robustness to variation and support policy generalization.

## 8) How to explain imitation learning in this project

- Expert policy = your scripted program.
- Demonstrations = synchronized robot state + camera streams + gripper events over episodes.
- Training = behavior cloning on LeRobot dataset.
- Inference = policy takes camera/state input and predicts robot/gripper actions.

## 9) Recommended quality gate before 1000 episodes

Collect and inspect 20 episodes first:
- camera streams present
- no dropped robot streams
- expected start/end in each episode
- success ratio acceptable

Then run full 1000 episode capture.
