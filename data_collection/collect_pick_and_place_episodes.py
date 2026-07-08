#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


DEFAULT_COLLECTOR_URL = "http://localhost:8000"
DEFAULT_BACKEND_URL = "http://localhost:8001"
DEFAULT_DATASET = "pick_and_place_1000"
DEFAULT_TASK = "pick-and-place"
DEFAULT_OPERATOR = "shamreen"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_base(url: str) -> str:
    return url.rstrip("/")


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout_s: float = 30.0,
) -> tuple[int, str, Any | None]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url=url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            parsed = None
            if body.strip():
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = None
            return resp.status, body, parsed
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        parsed = None
        if body.strip():
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
        return exc.code, body, parsed
    except URLError as exc:
        return 0, str(exc), None
    except (TimeoutError, socket.timeout) as exc:
        return 0, f"timeout: {exc}", None


def api_ok(status: int) -> bool:
    return 200 <= status < 300


def count_finalized(recordings_root: Path, dataset: str) -> int:
    dataset_dir = recordings_root / dataset
    if not dataset_dir.exists() or not dataset_dir.is_dir():
        return 0

    finalized = 0
    for child in dataset_dir.iterdir():
        if not child.is_dir():
            continue
        meta = child / "meta.json"
        recording = child / "recording.rrd"
        if meta.exists() and recording.exists():
            finalized += 1
    return finalized


def get_finalized_ids(recordings_root: Path, dataset: str) -> set[str]:
    dataset_dir = recordings_root / dataset
    ids: set[str] = set()
    if not dataset_dir.exists() or not dataset_dir.is_dir():
        return ids

    for child in dataset_dir.iterdir():
        if not child.is_dir():
            continue
        meta = child / "meta.json"
        recording = child / "recording.rrd"
        if meta.exists() and recording.exists():
            ids.add(child.name)
    return ids


def wait_for_new_finalized_recording(
    recordings_root: Path,
    dataset: str,
    before_ids: set[str],
    timeout_s: float,
    poll_s: float = 2.0,
) -> list[str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        after_ids = get_finalized_ids(recordings_root, dataset)
        new_ids = sorted(after_ids - before_ids)
        if new_ids:
            return new_ids
        time.sleep(poll_s)
    return []


def wait_backend_idle(backend_base: str, timeout_s: float, poll_s: float = 1.0) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_s
    last_program = ""
    while time.monotonic() < deadline:
        status, body, parsed = request_json("GET", f"{backend_base}/status", timeout_s=10.0)
        if not api_ok(status):
            return False, f"backend /status failed with {status}: {body}"

        is_running = bool(parsed.get("is_running")) if isinstance(parsed, dict) else False
        running_program = parsed.get("running_program") if isinstance(parsed, dict) else None
        last_program = str(running_program)
        if not is_running:
            return True, "idle"
        time.sleep(poll_s)

    return False, f"timeout waiting backend idle (last running_program={last_program})"


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=True) + "\n")


def is_transient_camera_error(status: int, body: str) -> bool:
    if status == 0:
        return True
    text = (body or "").lower()
    transient_terms = [
        "timed out",
        "timeout",
        "camera",
        "webrtc",
        "source",
        "first sample",
        "check_available",
        "warmup",
        "connection reset",
    ]
    return any(term in text for term in transient_terms)


def safe_discard_episode(collector_base: str) -> tuple[int, str]:
    status, body, _ = request_json("POST", f"{collector_base}/api/v1/episodes/discard")
    return status, body


def safe_stop_session(collector_base: str) -> tuple[int, str]:
    status, body, _ = request_json("POST", f"{collector_base}/api/v1/session/stop")
    return status, body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect pick-and-place episodes with robust retries and finalized-episode tracking."
    )
    parser.add_argument("--collector-url", default=DEFAULT_COLLECTOR_URL)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument(
        "--config-path",
        default=str(SCRIPT_DIR / "recording_steps_1_3.json"),
        help="Collector config JSON path",
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--operator", default=DEFAULT_OPERATOR)
    parser.add_argument("--target-episodes", type=int, default=1000)
    parser.add_argument("--lookback-s", type=float, default=0.0)
    parser.add_argument("--program-id", default="pick_and_place")
    parser.add_argument("--program-count", type=int, default=1)
    parser.add_argument(
        "--recordings-root",
        default="/home/shamreen-tabassum/Documents/nova-data-collection/app/recordings",
    )
    parser.add_argument("--episode-retries", type=int, default=3)
    parser.add_argument("--max-total-attempts", type=int, default=5000)
    parser.add_argument("--camera-retry-delay-s", type=float, default=8.0)
    parser.add_argument("--run-timeout-s", type=float, default=1200.0)
    parser.add_argument(
        "--episode-stop-timeout-s",
        type=float,
        default=180.0,
        help="HTTP timeout for /api/v1/episodes/stop (collector finalization can take time)",
    )
    parser.add_argument(
        "--stop-finalize-grace-s",
        type=float,
        default=120.0,
        help="Extra wait for finalized recording after stop timeout/error before marking attempt failed",
    )
    parser.add_argument(
        "--stop-session-on-exit",
        action="store_true",
        help="Stop collector session at the end (recommended).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without hitting APIs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    collector_base = normalize_base(args.collector_url)
    backend_base = normalize_base(args.backend_url)
    config_path = Path(args.config_path).expanduser()
    if not config_path.is_absolute():
        cwd_candidate = (Path.cwd() / config_path).resolve()
        project_candidate = (PROJECT_ROOT / config_path).resolve()
        script_candidate = (SCRIPT_DIR / config_path).resolve()
        for candidate in (cwd_candidate, project_candidate, script_candidate):
            if candidate.exists():
                config_path = candidate
                break
        else:
            config_path = cwd_candidate
    else:
        config_path = config_path.resolve()
    recordings_root = Path(args.recordings_root)
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_log = SCRIPT_DIR / "collection_runs" / f"pick_and_place_{run_stamp}.jsonl"

    if args.target_episodes <= 0:
        print("--target-episodes must be > 0")
        return 2

    print("=== Collection Automation ===")
    print(f"collector: {collector_base}")
    print(f"backend:   {backend_base}")
    print(f"dataset:   {args.dataset}")
    print(f"target:    {args.target_episodes}")
    print(f"program:   {args.program_id} count={args.program_count}")
    print(f"run log:   {run_log}")

    if not args.dry_run:
        status, body, _ = request_json("GET", f"{collector_base}/health")
        if not api_ok(status):
            print(f"collector health check failed: {status} {body}")
            return 1

        status, body, _ = request_json("GET", f"{backend_base}/health")
        if not api_ok(status):
            print(f"backend health check failed: {status} {body}")
            return 1

    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    completed_before = count_finalized(recordings_root, args.dataset)
    print(f"finalized episodes before run: {completed_before}")

    if completed_before >= args.target_episodes:
        print("Target already reached; nothing to do.")
        return 0

    if not args.dry_run:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        status, body, _ = request_json("POST", f"{collector_base}/api/v1/config", cfg)
        if not api_ok(status):
            print(f"config upload failed: {status} {body}")
            return 1
        print("config uploaded")

        session_payload = {
            "dataset": args.dataset,
            "task": args.task,
            "operator": args.operator,
        }
        status, body, _ = request_json(
            "POST", f"{collector_base}/api/v1/session/start", session_payload
        )
        if not api_ok(status):
            print(f"session start failed: {status} {body}")
            return 1
        print("session started")

    start_time = time.monotonic()
    total_attempts = 0
    successful_attempts = 0
    failed_attempts = 0

    try:
        while total_attempts < args.max_total_attempts:
            finalized_now = count_finalized(recordings_root, args.dataset)
            remaining = args.target_episodes - finalized_now
            if remaining <= 0:
                break

            print(
                f"\n=== Remaining finalized episodes: {remaining} "
                f"(current={finalized_now}/{args.target_episodes}) ==="
            )

            episode_success = False
            for retry_idx in range(1, args.episode_retries + 1):
                total_attempts += 1
                before_ids = get_finalized_ids(recordings_root, args.dataset)

                event = {
                    "ts": utc_now(),
                    "type": "episode_attempt",
                    "attempt": total_attempts,
                    "retry": retry_idx,
                    "dataset": args.dataset,
                    "program_id": args.program_id,
                }

                if args.dry_run:
                    print(f"[DRY RUN] attempt={total_attempts} retry={retry_idx}")
                    append_jsonl(run_log, {**event, "result": "dry_run"})
                    episode_success = True
                    successful_attempts += 1
                    break

                status, body, _ = request_json(
                    "POST",
                    f"{collector_base}/api/v1/episodes/start",
                    {"lookback_s": args.lookback_s},
                )
                if not api_ok(status):
                    reason = f"episode start failed: {status} {body}"
                    print(reason)
                    append_jsonl(run_log, {**event, "result": "start_failed", "reason": reason})

                    if retry_idx < args.episode_retries and is_transient_camera_error(status, body):
                        print(f"retrying after transient source issue in {args.camera_retry_delay_s}s")
                        time.sleep(args.camera_retry_delay_s)
                        continue
                    failed_attempts += 1
                    break

                run_payload = {"count": args.program_count}
                status, body, _ = request_json(
                    "POST",
                    f"{backend_base}/programs/{args.program_id}/start",
                    run_payload,
                    timeout_s=60.0,
                )
                if not api_ok(status):
                    reason = f"program start failed: {status} {body}"
                    print(reason)
                    discard_status, discard_body = safe_discard_episode(collector_base)
                    append_jsonl(
                        run_log,
                        {
                            **event,
                            "result": "program_start_failed",
                            "reason": reason,
                            "discard_status": discard_status,
                            "discard_body": discard_body,
                        },
                    )
                    if retry_idx < args.episode_retries:
                        time.sleep(args.camera_retry_delay_s)
                        continue
                    failed_attempts += 1
                    break

                done, done_reason = wait_backend_idle(backend_base, args.run_timeout_s)
                if not done:
                    print(f"program did not finish cleanly: {done_reason}")
                    discard_status, discard_body = safe_discard_episode(collector_base)
                    append_jsonl(
                        run_log,
                        {
                            **event,
                            "result": "program_timeout",
                            "reason": done_reason,
                            "discard_status": discard_status,
                            "discard_body": discard_body,
                        },
                    )
                    if retry_idx < args.episode_retries:
                        time.sleep(args.camera_retry_delay_s)
                        continue
                    failed_attempts += 1
                    break

                stop_status, stop_body, _ = request_json(
                    "POST",
                    f"{collector_base}/api/v1/episodes/stop",
                    timeout_s=args.episode_stop_timeout_s,
                )
                if not api_ok(stop_status):
                    if is_transient_camera_error(stop_status, stop_body):
                        print(
                            "episode stop timed out/transient error; "
                            f"waiting up to {args.stop_finalize_grace_s}s for finalize"
                        )
                        recovered_ids = wait_for_new_finalized_recording(
                            recordings_root=recordings_root,
                            dataset=args.dataset,
                            before_ids=before_ids,
                            timeout_s=args.stop_finalize_grace_s,
                        )
                        if recovered_ids:
                            recording_id = recovered_ids[-1]
                            print(f"saved recording_id={recording_id} (recovered after stop timeout)")
                            append_jsonl(
                                run_log,
                                {
                                    **event,
                                    "result": "success_recovered_after_stop_timeout",
                                    "stop_status": stop_status,
                                    "stop_body": stop_body,
                                    "recording_id": recording_id,
                                    "new_recording_ids": recovered_ids,
                                },
                            )
                            episode_success = True
                            successful_attempts += 1
                            break

                    reason = f"episode stop failed: {stop_status} {stop_body}"
                    print(reason)
                    discard_status, discard_body = safe_discard_episode(collector_base)
                    append_jsonl(
                        run_log,
                        {
                            **event,
                            "result": "stop_failed",
                            "reason": reason,
                            "discard_status": discard_status,
                            "discard_body": discard_body,
                        },
                    )
                    if retry_idx < args.episode_retries and is_transient_camera_error(stop_status, stop_body):
                        time.sleep(args.camera_retry_delay_s)
                        continue
                    failed_attempts += 1
                    break

                after_ids = get_finalized_ids(recordings_root, args.dataset)
                new_ids = sorted(after_ids - before_ids)
                if not new_ids:
                    reason = "no new finalized recording detected after stop"
                    print(reason)
                    append_jsonl(run_log, {**event, "result": "no_new_recording", "reason": reason})
                    if retry_idx < args.episode_retries:
                        time.sleep(args.camera_retry_delay_s)
                        continue
                    failed_attempts += 1
                    break

                recording_id = new_ids[-1]
                print(f"saved recording_id={recording_id}")
                append_jsonl(
                    run_log,
                    {
                        **event,
                        "result": "success",
                        "recording_id": recording_id,
                        "new_recording_ids": new_ids,
                    },
                )
                episode_success = True
                successful_attempts += 1
                break

            if not episode_success:
                finalized_now = count_finalized(recordings_root, args.dataset)
                print(
                    "episode not finalized after retries; "
                    f"current finalized={finalized_now}/{args.target_episodes}"
                )

        duration_s = time.monotonic() - start_time
        finalized_after = count_finalized(recordings_root, args.dataset)
        summary = {
            "ts": utc_now(),
            "type": "summary",
            "duration_s": round(duration_s, 2),
            "attempts": total_attempts,
            "attempts_success": successful_attempts,
            "attempts_failed": failed_attempts,
            "finalized_before": completed_before,
            "finalized_after": finalized_after,
            "target": args.target_episodes,
            "target_reached": finalized_after >= args.target_episodes,
        }
        append_jsonl(run_log, summary)

        print("\n=== Summary ===")
        print(json.dumps(summary, indent=2))

        if finalized_after < args.target_episodes:
            print(
                "Target not reached in this run. "
                "Re-run script to continue from current finalized count."
            )
            return 3
        return 0
    finally:
        if args.stop_session_on_exit and not args.dry_run:
            stop_status, stop_body = safe_stop_session(collector_base)
            if api_ok(stop_status):
                print("session stopped")
            else:
                print(f"session stop returned {stop_status}: {stop_body}")


if __name__ == "__main__":
    raise SystemExit(main())