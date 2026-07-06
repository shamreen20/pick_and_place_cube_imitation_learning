import os
from pathlib import Path


def sanitize_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return value
    # Allow inline comments in .env values, e.g. "4  # force".
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(sanitize_env_value(raw))
    except ValueError:
        print(f"[WARN] Invalid int for {name}={raw!r}. Using default {default}.")
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default

    value = sanitize_env_value(raw).lower()
    truthy = {"1", "true", "yes", "y", "on"}
    falsy = {"0", "false", "no", "n", "off"}
    if value in truthy:
        return True
    if value in falsy:
        return False

    print(f"[WARN] Invalid bool for {name}={raw!r}. Using default {default}.")
    return default


def clamp_percent(value: int) -> int:
    return max(1, min(100, int(value)))


def load_env_file(base_dir: Path) -> None:
    env_path = base_dir / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = sanitize_env_value(value)
        if key and key not in os.environ:
            os.environ[key] = value
