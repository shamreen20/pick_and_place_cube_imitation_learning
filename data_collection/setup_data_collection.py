#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.camera.camera_client import CameraClient  # nova: E402


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_collector_env(nova_data_collection_root: Path, project_env: dict[str, str]) -> None:
    app_env_path = nova_data_collection_root / "app" / ".env"
    app_env_values = parse_env_file(app_env_path)

    app_env_values["NOVA_API"] = project_env.get("NOVA_API", app_env_values.get("NOVA_API", ""))
    app_env_values["CELL_NAME"] = project_env.get("CELL_NAME", app_env_values.get("CELL_NAME", "cell"))
    app_env_values.setdefault("PORT", "8000")
    app_env_values.setdefault("SERVE_GRPC_PORT", "9876")

    write_env_file(app_env_path, app_env_values)
    print(f"[OK] Collector env updated: {app_env_path}")


def ensure_export_env(nova_data_collection_root: Path, project_env: dict[str, str]) -> None:
    export_env_path = nova_data_collection_root / "export-service" / ".env"
    export_env_values = parse_env_file(export_env_path)

    export_env_values["NOVA_API"] = project_env.get("NOVA_API", export_env_values.get("NOVA_API", ""))
    export_env_values["CELL_NAME"] = project_env.get("CELL_NAME", export_env_values.get("CELL_NAME", "cell"))
    export_env_values.setdefault("CATALOG_URL", "")
    export_env_values.setdefault("PORT", "8080")

    write_env_file(export_env_path, export_env_values)
    print(f"[OK] Export env updated: {export_env_path}")


def _safe_name(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch.isalnum() or ch in {"_", "-"}:
            out.append(ch)
        elif ch in {" ", ".", "/", "@"}:
            out.append("_")
    cleaned = "".join(out).strip("_")
    if not cleaned:
        cleaned = "cam"
    return cleaned


def _camera_base_candidates(cameras_base_url: str) -> list[str]:
    base = cameras_base_url.rstrip("/")
    parsed = urlparse(base)
    candidates: list[str] = [base]

    if parsed.scheme and parsed.netloc:
        host = f"{parsed.scheme}://{parsed.netloc}"
        candidates.extend(
            [
                f"{host}/cell/cameras",
                f"{host}/cell/realsense",
                f"{host}:8093/webrtc-streamer",
            ]
        )

    uniq: list[str] = []
    for c in candidates:
        if c not in uniq:
            uniq.append(c)
    return uniq


def _discover_camera_client(cameras_base_url: str) -> tuple[CameraClient, list[Any], str]:
    errors: list[str] = []
    for candidate in _camera_base_candidates(cameras_base_url):
        client = CameraClient(cameras_base_url=candidate)
        try:
            devices = client.list_devices()
            if devices:
                return client, devices, candidate
            errors.append(f"{candidate}: no devices")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError(
        "Unable to discover camera endpoint. Tried:\n- " + "\n- ".join(errors)
    )


def build_three_camera_sources(cameras_base_url: str, camera_ids: list[str] | None = None) -> list[dict[str, Any]]:
    _, devices, selected_base = _discover_camera_client(cameras_base_url)
    if not devices:
        raise RuntimeError("No cameras discovered from NOVA camera gateway")

    print(f"[OK] Camera endpoint: {selected_base}")

    selected = []
    if camera_ids:
        id_set = set(camera_ids)
        for d in devices:
            if d.device_id in id_set or d.original_device_id in id_set or d.name in id_set:
                selected.append(d)
    else:
        selected = [d for d in devices if d.is_streaming]
        if len(selected) < 3:
            for d in devices:
                if d not in selected:
                    selected.append(d)
                if len(selected) >= 3:
                    break

    if len(selected) < 3:
        raise RuntimeError(
            f"Need 3 cameras, found only {len(selected)}. Attach/enable all three cameras first."
        )

    selected = selected[:3]
    default_names = ["cam_top", "cam_wrist", "cam_side"]
    sources: list[dict[str, Any]] = []

    for idx, cam in enumerate(selected):
        source_name = default_names[idx]
        if idx >= len(default_names):
            source_name = f"cam_{_safe_name(cam.name)}"

        sources.append(
            {
                "type": "camera",
                "name": source_name,
                "base_url": cam.provider_url,
                "device_id": cam.original_device_id,
                "stream_type": "color",
                # Side camera can be unavailable (for example no HDMI signal). Keep it optional.
                "required": idx < 2,
            }
        )

    print("[OK] Selected cameras:")
    for s in sources:
        print(
            f"  - {s['name']}: base_url={s['base_url']} device_id={s['device_id']}"
        )
    return sources


def generate_recording_config(
    output_path: Path,
    cameras_base_url: str,
    motion_group: str,
    dataset: str,
    task: str,
    operator: str,
    camera_ids: list[str] | None = None,
) -> None:
    camera_sources = build_three_camera_sources(cameras_base_url, camera_ids)

    config = {
        "version": 1,
        "metadata": {
            "dataset": dataset,
            "task": task,
            "operator": operator,
        },
        "settings": {
            "chunk_size_mb": 250,
        },
        "sources": [
            {
                "type": "robot",
                "name": "joint_positions",
                "motion_group": motion_group,
                "rate_ms": 64,
                "stream_type": "joint_position",
                "required": True,
            },
            {
                "type": "robot",
                "name": "tcp_pose",
                "motion_group": motion_group,
                "rate_ms": 64,
                "stream_type": "tcp_pose",
                "required": True,
            },
            {
                "type": "robot",
                "name": "commanded_joint_positions",
                "motion_group": motion_group,
                "rate_ms": 16,
                "stream_type": "commanded_joint_position",
                "required": True,
            },
            *camera_sources,
            {
                "type": "io",
                "name": "gripper_state",
                "controller": motion_group.split("@", 1)[1] if "@" in motion_group else "ur10e",
                "signal": "digital_out[0]",
                "required": False,
            },
        ],
    }

    output_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Recording config generated: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Setup local project + nova-data-collection for 3-camera data recording"
    )
    parser.add_argument(
        "--nova-data-collection-root",
        default="/home/shamreen-tabassum/Documents/nova-data-collection",
        help="Path to nova-data-collection repository",
    )
    parser.add_argument(
        "--project-env",
        default=str(PROJECT_ROOT / ".env"),
        help="Path to this project's .env file",
    )
    parser.add_argument(
        "--generate-recording-config",
        action="store_true",
        help="Generate recording_steps_1_3.json using 3 discovered cameras",
    )
    parser.add_argument(
        "--cameras-base-url",
        default=os.getenv("CAMERAS_BASE_URL", "http://localhost/cell/cameras"),
        help="NOVA camera gateway base URL",
    )
    parser.add_argument(
        "--motion-group",
        default="0@ur10e",
        help="Motion group id for collector robot sources",
    )
    parser.add_argument(
        "--dataset",
        default="cube_steps_1_3_1000",
        help="Dataset name for recording metadata",
    )
    parser.add_argument(
        "--task",
        default="Cube transfer steps 1-3: home -> pick target -> place random -> home",
        help="Task metadata",
    )
    parser.add_argument(
        "--operator",
        default="NOVA",
        help="Operator metadata",
    )
    parser.add_argument(
        "--camera-id",
        action="append",
        dest="camera_ids",
        default=None,
        help="Optional camera id/name to pin order (use 3 times)",
    )
    parser.add_argument(
        "--recording-output",
        default=str(PROJECT_ROOT / "data_collection" / "recording_steps_1_3.json"),
        help="Output path for generated recording config",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    nova_data_collection_root = Path(args.nova_data_collection_root)
    project_env_path = Path(args.project_env)

    if not nova_data_collection_root.exists():
        print(f"[ERR] nova-data-collection not found: {nova_data_collection_root}")
        return 1
    if not project_env_path.exists():
        print(f"[ERR] project env file not found: {project_env_path}")
        return 1

    project_env = parse_env_file(project_env_path)

    ensure_collector_env(nova_data_collection_root, project_env)
    ensure_export_env(nova_data_collection_root, project_env)

    if args.generate_recording_config:
        generate_recording_config(
            output_path=Path(args.recording_output),
            cameras_base_url=args.cameras_base_url,
            motion_group=args.motion_group,
            dataset=args.dataset,
            task=args.task,
            operator=args.operator,
            camera_ids=args.camera_ids,
        )

    print("\nNext commands:")
    print("1) Start collector: cd /home/shamreen-tabassum/Documents/nova-data-collection/app && uv run nova-collect")
    print("2) Start export:   cd /home/shamreen-tabassum/Documents/nova-data-collection/export-service && uv run python -m nova_export.main")
    print("3) Push config:    curl -X POST http://localhost:8000/api/v1/config -H \"Content-Type: application/json\" -d @data_collection/recording_steps_1_3.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
