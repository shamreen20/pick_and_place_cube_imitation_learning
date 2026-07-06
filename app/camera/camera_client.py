from __future__ import annotations
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CameraDevice:
    device_id: str
    original_device_id: str
    name: str
    provider_url: str
    provider_type: str
    is_streaming: bool


class CameraClient:
    """Client for NOVA camera gateway and provider APIs.

    The gateway endpoint is usually:
    http://<host>/cell/cameras/api/devices
    """

    def __init__(self, cameras_base_url: str, timeout_s: float = 8.0):
        self.cameras_base_url = cameras_base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _request_json(self, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url=url, method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Connection error for {url}: {exc}") from exc

    def list_devices(self) -> list[CameraDevice]:
        url = f"{self.cameras_base_url}/api/devices"
        payload = self._request_json("GET", url)
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected devices payload type: {type(payload)}")

        devices: list[CameraDevice] = []
        for d in payload:
            devices.append(
                CameraDevice(
                    device_id=str(d.get("device_id", "")),
                    original_device_id=str(d.get("original_device_id", "")),
                    name=str(d.get("name", "unknown")),
                    provider_url=str(d.get("provider_url", "")).rstrip("/"),
                    provider_type=str(d.get("provider_type", "unknown")),
                    is_streaming=bool(d.get("is_streaming", False)),
                )
            )
        return devices

    def resolve_device(self, requested_device: str) -> CameraDevice:
        devices = self.list_devices()
        if not devices:
            raise RuntimeError("No camera devices found")

        # Match in priority order: exact gateway id, exact original id, partial id/name match.
        for d in devices:
            if requested_device and requested_device == d.device_id:
                return d
        for d in devices:
            if requested_device and requested_device == d.original_device_id:
                return d
        if requested_device:
            lowered = requested_device.lower()
            for d in devices:
                if lowered in d.device_id.lower() or lowered in d.name.lower():
                    return d

        # Fallback to first listed device.
        return devices[0]

    def get_stream_status(self, requested_device: str) -> dict[str, Any]:
        device = self.resolve_device(requested_device)
        encoded = urllib.parse.quote(device.original_device_id, safe="")
        url = f"{device.provider_url}/api/devices/{encoded}/stream/status"
        status = self._request_json("GET", url)
        if not isinstance(status, dict):
            raise RuntimeError(f"Unexpected stream status payload type: {type(status)}")
        status["resolved_gateway_device_id"] = device.device_id
        status["resolved_provider_device_id"] = device.original_device_id
        status["provider_url"] = device.provider_url
        return status
