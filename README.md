# Nova Pick and Place Demo

A Python application for Wandelbots NOVA that demonstrates a pick-and-place workflow with random table repositioning.

## Features
- 🤖 **Robot loop**: Home → Pick from target → Place randomly → Home → Retrieve & return (repeats)
- 📍 **Coordinate logging**: Each cycle prints stored/reused poses with tolerance verification
- 🔌 **Zimmer gripper support**: Both mock (virtual) and real Modbus-based gripper
- 📊 **Rerun visualization**: Real-time 3D robot motion display
- 🚀 **NOVA deployment ready**: Docker containerized, follows Wandelbots quickstart

## Prerequisites
- Python 3.11+
- Docker (for deployment to NOVA)
- Wandelbots NOVA CLI: `brew install wandelbotsgmbh/wandelbots/nova` (macOS/Linux) or [download](https://github.com/wandelbotsgmbh/nova-cli/releases) (Windows)
- Access to a NOVA instance (cloud or local)

## Quick Start (Local/Virtual)

### 1. Setup dependencies
```bash
cd nova-pick-place-demo
uv sync
```

### 2. Run the pick-and-place program
This starts 10 cycles with the virtual robot and mock gripper:
```bash
uv run python -m app.pick_and_place
```

**Console output shows:**
```
[Home joints] [j1, j2, j3, j4, j5, j6]
[Target approach] xyz=(491.9, -133.3, 250.0)
[Target pick]     xyz=(491.9, -133.3, -71.4)
[Stored random pose] xyz=(450.99, -79.98, -72.0)
[Reuse check] stored=(...) reused=(...) same=True tol_mm=0.1
```

### 3. View in Rerun (3D visualization)
The program uses Rerun for live visualization. Connect via:
```bash
rerun --connect rerun+http://127.0.0.1:9876/proxy
```

### 4. (Optional) Run the web API backend
```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open browser: http://localhost:8000

---

## Deploy to NOVA

### 1. Configure NOVA CLI
Follow [Wandelbots NOVA quickstart](https://docs.wandelbots.io/26.5/developing-python-quickstart):

```bash
# Set your NOVA instance host
nova config set host wandelbox-hhmnwy  # or your NOVA IP/hostname

# Configure Docker image registry (required for deployment)
nova config set image-registry registry-1.docker.io/YOUR-DOCKER-USERNAME
```

### 2. Update environment
Copy `.env.example` to `.env` and fill in your NOVA instance details:
```bash
cp .env.example .env
# Edit .env with your NOVA_API, CELL_NAME, and optional ZIMMER_HOST
```

### 3. Build and push Docker image
```bash
docker build -t YOUR-DOCKER-USERNAME/nova-pick-place-demo:latest .
docker push YOUR-DOCKER-USERNAME/nova-pick-place-demo:latest
```

### 4. Deploy to NOVA
```bash
nova app install
# or specify explicitly:
# nova app install ./nova-pick-place-demo.yaml
```

### 5. Verify deployment
Open your NOVA instance UI and verify the app appears on the home screen. Click to launch.

---

## Configuration

### Motion speeds (in pick_and_place.py)
- `slow = 25 mm/s`   — Home transitions (safer)
- `average = 35 mm/s` — Pick/place moves (standard)

Adjust these constants if needed:
```python
slow = MotionSettings(tcp_velocity_limit=25)
average = MotionSettings(tcp_velocity_limit=35)
```

### Workspace bounds (in pick_and_place.py)
Random table poses are constrained to:
```python
X_MIN, X_MAX = 350.0, 600.0   # table x range (mm)
Y_MIN, Y_MAX = -130.0, 120.0  # table y range (mm)
Z_DROP = -72.0                # table surface height (mm)
Z_APPROACH = 250.0            # hover height above table (mm)
```

### Real Zimmer gripper
To use a real Zimmer gripper on the robot instead of mock:
```bash
export ZIMMER_HOST=192.168.1.50  # TBEN-S2-4IOL IP
uv run python -m app.pick_and_place --use-zimmer-gripper true
```

---

## Project Structure
```
nova-pick-place-demo/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI backend
│   ├── pick_and_place.py          # Main robot program
│   ├── gripper_helper.py          # Mock & Zimmer gripper classes
│   └── static/
│       └── app_icon.png           # App icon for NOVA UI
├── zimmer_gripper_controller/     # Zimmer Modbus driver
├── pyproject.toml                 # Dependencies (uv)
├── Dockerfile                     # Container build config
├── nova-pick-place-demo.yaml      # NOVA app manifest
├── .env.example                   # Environment template
└── README.md                       # This file
```

---

## Troubleshooting

### Unclosed aiohttp session warnings
These are benign cleanup warnings from the NOVA SDK; they don't affect functionality.

### Program doesn't start
- Check `.env` has correct `NOVA_API` and `CELL_NAME`
- Ensure your NOVA instance is reachable: `ping wandelbox-hhmnwy`
- Run `nova status` to verify CLI setup

### Gripper not responding
- For mock gripper: no additional setup needed
- For real Zimmer: verify TBEN IP, Modbus port 502 is accessible, IO-Link configured

### Coordinate drift
If stored vs. reused poses show `same=False`, check `POSITION_TOLERANCE_MM` (default 0.1 mm).
