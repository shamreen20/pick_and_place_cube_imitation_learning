import asyncio
import logging
import os
import random
import sys
from pathlib import Path
import nova
from nova import run_program
from nova.actions import cartesian_ptp
from nova.exceptions import InitMovementFailed
from nova.types import MotionSettings, Pose
from pydantic import Field
from wandelbots_api_client.v2_pydantic.models import SettableRobotSystemMode

# Ensure imports work when running from project root.
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.gripper_helper import MockGripper, ZimmerGripper  # noqa: E402


def _sanitize_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return value
    # Allow inline comments in .env values, e.g. "4  # force".
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(_sanitize_env_value(raw))
    except ValueError:
        print(f"[WARN] Invalid int for {name}={raw!r}. Using default {default}.")
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(_sanitize_env_value(raw))
    except ValueError:
        print(f"[WARN] Invalid float for {name}={raw!r}. Using default {default}.")
        return default


def _clamp_percent(value: int) -> int:
    return max(1, min(100, int(value)))


def _clamp_gap_mm(value: float) -> float:
    return max(1.0, min(80.0, float(value)))


def _load_env_file() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _sanitize_env_value(value)
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()
os.environ.pop("NATS_BROKER", None)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# Table workspace bounds in millimeters.
X_MIN = -520.2
X_MAX = 507.9
Y_MIN = -522.1
Y_MAX = -192.7
Z_TABLE_APPROACH = 450.0
Z_DROP = 260.0
ORIENTATION = (3.1245, -0.0346, -0.0037)
PLACE_TOUCHDOWN_DZ_MM = 4.0
RANDOM_TOUCHDOWN_DZ_MM = 1.0
RELEASE_LIFT_DZ_MM = 3.0

# Fixed robot poses.
HOME_POSE = Pose((-377.7, -362.7, 557.7, 3.1245, -0.0342, -0.0039))
TARGET_APPROACH = Pose((-377.7, -362.7, 450.0, 3.1245, -0.0343, -0.0037))
TARGET_PICK = Pose((-377.6, -362.7, 264.7, 3.1247, -0.0343, -0.0033))


def random_table_pose() -> tuple[Pose, Pose]:
    x = random.uniform(X_MIN, X_MAX)
    y = random.uniform(Y_MIN, Y_MAX)
    approach = Pose((x, y, Z_TABLE_APPROACH, *ORIENTATION))
    place = Pose((x, y, Z_DROP, *ORIENTATION))
    return approach, place


def offset_z_down(pose: Pose, dz_mm: float) -> Pose:
    return Pose(
        (
            float(pose.position.x),
            float(pose.position.y),
            float(pose.position.z) - dz_mm,
            float(pose.orientation.x),
            float(pose.orientation.y),
            float(pose.orientation.z),
        )
    )


@nova.program(
    id="pick_and_place",
    name="Pick and Place",
)
async def start(
    ctx: nova.ProgramContext,
    count: int = Field(default=4, ge=1, le=20, description="Number of cycles"),
    controller_name: str = Field(
        default=os.getenv("ROBOT_CONTROLLER_NAME", "ur10e"),
        description="Controller name in NOVA",
    ),
    zimmer_host: str = Field(
        default=os.getenv("ZIMMER_HOST", ""),
        description="Zimmer TBEN Modbus IP",
    ),
    zimmer_port: int = Field(default=_env_int("ZIMMER_PORT", 502)),
    zimmer_unit_id: int = Field(default=_env_int("ZIMMER_UNIT_ID", 1)),
    zimmer_io_link_port: int = Field(default=_env_int("ZIMMER_IO_LINK_PORT", 0)),
    zimmer_force_percent: int = Field(
        default=_env_int("ZIMMER_FORCE_PERCENT", 2),
        ge=1,
        le=100,
        description="Zimmer force while closing/gripping in percent",
    ),
    zimmer_hold_force_percent: int = Field(
        default=_env_int("ZIMMER_HOLD_FORCE_PERCENT", 1),
        ge=1,
        le=100,
        description="Zimmer force while carrying the part in percent",
    ),
    zimmer_velocity_percent: int = Field(
        default=_env_int("ZIMMER_VELOCITY_PERCENT", 20),
        ge=1,
        le=100,
        description="Zimmer jaw drive velocity in percent",
    ),
    zimmer_grip_gap_mm: float = Field(
        default=_env_float("ZIMMER_GRIP_GAP_MM", 45.0),
        ge=1.0,
        le=80.0,
        description="Target jaw gap during gripping in millimeters",
    ),
):
    cell = ctx.cell
    controller = await cell.controller(controller_name)
    motion_group = controller[0]
    cycle = ctx.cycle(extra={"app": "pick-and-place"})

    slow = MotionSettings(tcp_velocity_limit=50)
    avg = MotionSettings(tcp_velocity_limit=80)
    place = MotionSettings(tcp_velocity_limit=20)

    tcps = await motion_group.tcp_names()
    preferred = ["OnRobot_Single", "flange", "tool0"]
    tcp = next((name for name in preferred if name in tcps), tcps[0])
    print(f"Available TCPs: {tcps}")
    print(f"Using TCP: {tcp}")

    grip_force_percent = _clamp_percent(zimmer_force_percent)
    hold_force_percent = _clamp_percent(zimmer_hold_force_percent)
    velocity_percent = _clamp_percent(zimmer_velocity_percent)
    grip_gap_mm = _clamp_gap_mm(zimmer_grip_gap_mm)
    grip_gap_m = grip_gap_mm / 1000.0
    if hold_force_percent > grip_force_percent:
        print(
            f"[WARN] HOLD force {hold_force_percent}% is greater than GRIP force "
            f"{grip_force_percent}%. Clamping HOLD to {grip_force_percent}%"
        )
        hold_force_percent = grip_force_percent

    if zimmer_host:
        gripper = ZimmerGripper(
            host=zimmer_host,
            port=zimmer_port,
            unit_id=zimmer_unit_id,
            io_link_port=zimmer_io_link_port,
            force_percent=grip_force_percent,
            drive_velocity_percent=velocity_percent,
        )
        print(
            f"[Gripper] ZimmerGripper @ {zimmer_host}:{zimmer_port} "
            f"unit={zimmer_unit_id} io_link_port={zimmer_io_link_port} "
            f"grip_force={grip_force_percent}% hold_force={hold_force_percent}% "
            f"velocity={velocity_percent}% grip_gap={grip_gap_mm:.1f}mm"
        )
    else:
        gripper = MockGripper()
        print("[Gripper] ZIMMER_HOST is empty, using MockGripper")

    async def move(action_list, label: str) -> None:
        print(f"[MOVE] {label}")
        traj = await motion_group.plan(action_list, tcp)
        try:
            await motion_group.execute(traj, tcp, actions=action_list)
        except* InitMovementFailed as eg:
            error_text = str(eg.exceptions[0]) if eg.exceptions else str(eg)
            if "Could not claim ROBOT_MODE_CONTROL" not in error_text:
                raise

            print("[WARN] Controller lock detected. Resetting mode and retrying once...")
            await motion_group._api_client.controller_api.set_default_mode(
                cell=os.getenv("CELL_NAME", "cell"),
                controller=controller_name,
                mode=SettableRobotSystemMode.ROBOT_SYSTEM_MODE_MONITOR,
            )
            await asyncio.sleep(1.0)
            await motion_group._api_client.controller_api.set_default_mode(
                cell=os.getenv("CELL_NAME", "cell"),
                controller=controller_name,
                mode=SettableRobotSystemMode.ROBOT_SYSTEM_MODE_CONTROL,
            )
            await asyncio.sleep(1.0)

            traj_retry = await motion_group.plan(action_list, tcp)
            await motion_group.execute(traj_retry, tcp, actions=action_list)

    await cycle.start()
    try:
        print("[Gripper] Initializing...")
        await gripper.wait_until_ready()
        await gripper.set_force_percent(grip_force_percent)
        if isinstance(gripper, ZimmerGripper):
            await gripper.set_velocity_percent(velocity_percent)
        await gripper.open()

        await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME startup")

        for cycle_index in range(1, count + 1):
            print(f"\n===== CYCLE {cycle_index}/{count} =====")
            random_approach, random_pose = random_table_pose()

            # Pick at target.
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET_APPROACH")
            await move([cartesian_ptp(TARGET_PICK, settings=avg)], "TARGET_PICK descend")
            print(f"[Gripper] GRIP at target (gap={grip_gap_mm:.1f}mm)")
            await gripper.set_force_percent(grip_force_percent)
            if isinstance(gripper, ZimmerGripper):
                await gripper.move_to_gap_m(grip_gap_m)
            else:
                await gripper.close()
            await gripper.set_force_percent(hold_force_percent)

            # Place on random table pose.
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET lift")
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM_APPROACH")
            await move([cartesian_ptp(random_pose, settings=place)], "RANDOM descend")
            await move(
                [cartesian_ptp(offset_z_down(random_pose, RANDOM_TOUCHDOWN_DZ_MM), settings=place)],
                "RANDOM touchdown",
            )
            await asyncio.sleep(0.05)
            print("[Gripper] OPEN at random")
            await gripper.open()
            await asyncio.sleep(0.03)
            await move(
                [cartesian_ptp(offset_z_down(random_pose, -RELEASE_LIFT_DZ_MM), settings=place)],
                "RANDOM gentle lift",
            )
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM retreat")

            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME mid")

            # Pick from random table pose.
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM return")
            await move([cartesian_ptp(random_pose, settings=avg)], "RANDOM descend pick")
            print(f"[Gripper] GRIP at random (gap={grip_gap_mm:.1f}mm)")
            await gripper.set_force_percent(grip_force_percent)
            if isinstance(gripper, ZimmerGripper):
                await gripper.move_to_gap_m(grip_gap_m)
            else:
                await gripper.close()
            await gripper.set_force_percent(hold_force_percent)

            # Place back at target.
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM lift")
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET return")
            await move([cartesian_ptp(TARGET_PICK, settings=place)], "TARGET descend place")
            await move(
                [cartesian_ptp(offset_z_down(TARGET_PICK, PLACE_TOUCHDOWN_DZ_MM), settings=place)],
                "TARGET touchdown",
            )
            await asyncio.sleep(0.05)
            print("[Gripper] OPEN at target")
            await gripper.open()
            await asyncio.sleep(0.03)

            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET retreat")
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME end")

        print("[Done] Program finished")
    finally:
        await gripper.shutdown()
        await cycle.finish()


if __name__ == "__main__":
    run_program(start)
