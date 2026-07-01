#!/usr/bin/env python3
"""Local RealSense connector without using the web app UI.

This script talks directly to the RealSense backend API served at:
http://172.31.11.129/cell/realsense/

It can:
- list connected devices
- inspect sensors/profiles
- start one stream with an auto-selected profile
- check stream status
- optionally stop the stream again
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "http://172.31.11.129/cell/realsense"


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Connection error for {url}: {exc}") from exc


def _join(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _pick_first_profile(sensor: dict[str, Any]) -> dict[str, Any] | None:
    profiles = sensor.get("supported_stream_profiles") or []
    if not profiles:
        return None

    p = profiles[0]
    resolutions = p.get("resolutions") or [[640, 480]]
    fps_list = p.get("fps") or [30]
    formats = p.get("formats") or ["rgb8"]

    width, height = resolutions[0]
    return {
        "sensor_id": sensor["sensor_id"],
        "stream_type": p.get("stream_type", "color"),
        "format": formats[0],
        "resolution": {"width": int(width), "height": int(height)},
        "framerate": int(fps_list[0]),
        "enable": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect to RealSense backend without app UI")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL for Realsense app")
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Only list devices/sensors without starting stream",
    )
    parser.add_argument(
        "--keep-stream",
        action="store_true",
        help="Do not stop stream at end",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    api_base = _join(base_url, "api/")

    print(f"[INFO] Backend base: {api_base}")

    devices = _request_json("GET", _join(api_base, "devices"))
    if not isinstance(devices, list) or not devices:
        print("[WARN] No devices found")
        return 0

    print(f"[INFO] Found {len(devices)} device(s)")
    for d in devices:
        print(
            f"  - id={d.get('device_id')} name={d.get('name', 'unknown')} "
            f"is_streaming={d.get('is_streaming')}"
        )

    target = devices[0]
    device_id = target["device_id"]

    sensors = _request_json("GET", _join(api_base, f"devices/{device_id}/sensors"))
    if not isinstance(sensors, list) or not sensors:
        print(f"[WARN] Device {device_id} has no sensors")
        return 0

    print(f"[INFO] Device {device_id} has {len(sensors)} sensor(s)")
    for s in sensors:
        profiles = s.get("supported_stream_profiles") or []
        print(
            f"  - sensor_id={s.get('sensor_id')} name={s.get('sensor_name', 'unknown')} "
            f"profiles={len(profiles)}"
        )

    status_before = _request_json("GET", _join(api_base, f"devices/{device_id}/stream/status"))
    print(f"[INFO] Status before start: {status_before}")

    if args.no_start:
        return 0

    first_cfg = _pick_first_profile(sensors[0])
    if first_cfg is None:
        print(f"[WARN] Sensor {sensors[0].get('sensor_id')} has no stream profiles")
        return 0

    payload = {"configs": [first_cfg], "align_to": None}
    print(f"[INFO] Start payload: {payload}")
    start_resp = _request_json("POST", _join(api_base, f"devices/{device_id}/stream/start"), payload)
    print(f"[INFO] Start response: {start_resp}")

    status_after = _request_json("GET", _join(api_base, f"devices/{device_id}/stream/status"))
    print(f"[INFO] Status after start: {status_after}")

    if not args.keep_stream:
        stop_resp = _request_json("POST", _join(api_base, f"devices/{device_id}/stream/stop"), {})
        print(f"[INFO] Stop response: {stop_resp}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
