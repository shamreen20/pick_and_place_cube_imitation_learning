import argparse
import json
import os

from app.camera import CameraClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Check NOVA camera devices and stream status")
    parser.add_argument(
        "--cameras-base-url",
        default=os.getenv("CAMERAS_BASE_URL", "http://172.31.11.129/cell/cameras"),
        help="NOVA camera gateway base URL (example: http://<host>/cell/cameras)",
    )
    parser.add_argument(
        "--device",
        default="",
        help="Optional device id/name to resolve (uses first device if omitted)",
    )
    args = parser.parse_args()

    client = CameraClient(cameras_base_url=args.cameras_base_url)
    devices = client.list_devices()
    if not devices:
        print("No camera devices found")
        return 1

    print("Detected cameras:")
    for d in devices:
        print(
            f"- name={d.name} gateway_id={d.device_id} original_id={d.original_device_id} "
            f"provider={d.provider_type} streaming={d.is_streaming}"
        )

    status = client.get_stream_status(args.device)
    print("\nResolved stream status:")
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())