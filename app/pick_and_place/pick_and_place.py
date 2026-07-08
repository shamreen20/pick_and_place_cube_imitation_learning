import asyncio
import logging
import os
import sys
from pathlib import Path
import nova
from nova import run_program
from nova.actions import cartesian_ptp
from nova.types import MotionSettings
from pydantic import Field

# Project root is 3 levels up: app/pick_and_place/pick_and_place.py -> project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.gripper_helper import MockGripper, ZimmerGripper  # noqa: E402
from app.pick_and_place.pick_and_place_env import clamp_percent, env_int, load_env_file  # noqa: E402
from app.pick_and_place.pick_and_place_motion import move_with_retry, select_tcp  # noqa: E402
from app.pick_and_place.pick_and_place_poses import (  # noqa: E402
    HOME_POSE,
    TARGET_APPROACH,
    TARGET_PICK,
    offset_z_down,
    random_table_pose,
)

PLACE_TOUCHDOWN_DZ_MM = 4.0
RANDOM_TOUCHDOWN_DZ_MM = 1.0
RELEASE_LIFT_DZ_MM = 5.0

load_env_file(_PROJECT_ROOT)
os.environ.pop("NATS_BROKER", None)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
RANDOM_RELEASE_EXTRA_DZ_MM = env_int("RANDOM_RELEASE_EXTRA_DZ_MM", 10)


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
    zimmer_port: int = Field(default=env_int("ZIMMER_PORT", 502)),
    zimmer_unit_id: int = Field(default=env_int("ZIMMER_UNIT_ID", 1)),
    zimmer_io_link_port: int = Field(default=env_int("ZIMMER_IO_LINK_PORT", 0)),
    zimmer_force_percent: int = Field(
        default=env_int("ZIMMER_FORCE_PERCENT", 5),
        ge=1,
        le=100,
        description="Zimmer grip force in percent",
    ),
    zimmer_hold_force_percent: int = Field(
        default=env_int("ZIMMER_HOLD_FORCE_PERCENT", 3),
        ge=1,
        le=100,
        description="Zimmer hold force while carrying the part in percent",
    ),
    zimmer_startup_timeout_s: int = Field(
        default=env_int("ZIMMER_STARTUP_TIMEOUT_S", 60),
        ge=5,
        le=180,
        description="Zimmer startup/homing timeout in seconds",
    ),
):
    cell = ctx.cell
    controller = await cell.controller(controller_name)
    motion_group = controller[0]
    cycle = ctx.cycle(extra={"app": "pick-and-place"})

    slow = MotionSettings(tcp_velocity_limit=50)
    avg = MotionSettings(tcp_velocity_limit=80)
    place = MotionSettings(tcp_velocity_limit=40)

    tcps = await motion_group.tcp_names()
    tcp = select_tcp(tcps)
    print(f"Available TCPs: {tcps}")
    print(f"Using TCP: {tcp}")

    grip_force_percent = max(5, clamp_percent(zimmer_force_percent))
    hold_force_percent = min(clamp_percent(zimmer_hold_force_percent), grip_force_percent)

    if zimmer_host:
        gripper = ZimmerGripper(
            host=zimmer_host,
            port=zimmer_port,
            unit_id=zimmer_unit_id,
            io_link_port=zimmer_io_link_port,
            force_percent=grip_force_percent,
            startup_timeout_s=float(zimmer_startup_timeout_s),
        )
        print(
            f"[Gripper] ZimmerGripper @ {zimmer_host}:{zimmer_port} "
            f"grip_force={grip_force_percent}% hold_force={hold_force_percent}% "
            f"startup_timeout={zimmer_startup_timeout_s}s"
        )
    else:
        gripper = MockGripper()
        print("[Gripper] ZIMMER_HOST is empty, using MockGripper")

    async def move(action_list, label: str) -> None:
        await move_with_retry(
            motion_group=motion_group,
            action_list=action_list,
            label=label,
            tcp=tcp,
            controller_name=controller_name,
        )

    async def close_grip(stage: str) -> None:
        print(f"[Gripper] CLOSE at {stage}")
        await gripper.set_force_percent(grip_force_percent)
        await gripper.close()
        await gripper.wait_until_stopped()
        await gripper.set_force_percent(hold_force_percent)

    async def open_grip(stage: str) -> None:
        print(f"[Gripper] OPEN at {stage}")
        await gripper.open()
        await gripper.wait_until_stopped()

    await cycle.start()
    try:
        print("[Gripper] Initializing...")
        await gripper.wait_until_ready()
        await open_grip("startup")

        await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME startup")

        for cycle_index in range(1, count + 1):
            print(f"\n===== CYCLE {cycle_index}/{count} =====")
            random_approach, random_pose = random_table_pose()

            # 1. Move to fixed target and pick object.
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET_APPROACH")
            await move([cartesian_ptp(TARGET_PICK, settings=avg)], "TARGET_PICK descend")
            await close_grip("TARGET_PICK")

            # 2. Carry to random table position and place object.
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET lift")
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM_APPROACH")
            await move([cartesian_ptp(random_pose, settings=place)], "RANDOM descend")
            await move(
                [cartesian_ptp(
                    offset_z_down(random_pose, RANDOM_TOUCHDOWN_DZ_MM + float(RANDOM_RELEASE_EXTRA_DZ_MM)),
                    settings=place,
                )],
                "RANDOM touchdown",
            )
            await open_grip("RANDOM place")
            await move(
                [cartesian_ptp(offset_z_down(random_pose, -RELEASE_LIFT_DZ_MM), settings=place)],
                "RANDOM gentle lift",
            )
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM retreat")
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME mid")

            # 3. Return to random table position and pick object back.
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM return")
            await move([cartesian_ptp(random_pose, settings=avg)], "RANDOM descend pick")
            await close_grip("RANDOM_PICK")

            # 4. Carry back to fixed target and place object.
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM lift")
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET return")
            await move([cartesian_ptp(TARGET_PICK, settings=place)], "TARGET descend place")
            await move(
                [cartesian_ptp(offset_z_down(TARGET_PICK, PLACE_TOUCHDOWN_DZ_MM), settings=place)],
                "TARGET touchdown",
            )
            await open_grip("TARGET place")

            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET retreat")
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME end")

        print("[Done] Program finished")
    finally:
        await gripper.shutdown()
        await cycle.finish()


if __name__ == "__main__":
    run_program(start)