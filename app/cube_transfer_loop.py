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

# Project root is 2 levels up: app/cube_transfer_loop.py -> project root
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.gripper_helper import MockGripper, ZimmerGripper  # noqa: E402
from app.pick_and_place.pick_and_place_env import clamp_percent as _clamp_percent, env_int as _env_int, load_env_file  # noqa: E402
from app.pick_and_place.pick_and_place_motion import move_with_retry, select_tcp  # noqa: E402
from app.pick_and_place.pick_and_place_poses import (  # noqa: E402
    HOME_POSE,
    TARGET_APPROACH,
    TARGET_PICK,
    offset_z_down,
    random_table_pose,
)

load_env_file(_PROJECT_ROOT)
os.environ.pop("NATS_BROKER", None)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

TOUCHDOWN_DZ_MM = 2.0


@nova.program(
    id="cube_transfer_loop",
    name="Cube Transfer Loop",
)
async def start_cube_transfer(
    ctx: nova.ProgramContext,
    count: int = Field(default=1000, ge=1, le=5000, description="Number of episodes"),
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
        default=_env_int("ZIMMER_FORCE_PERCENT", 5),
        ge=1,
        le=100,
        description="Zimmer force while closing/gripping in percent",
    ),
    zimmer_hold_force_percent: int = Field(
        default=_env_int("ZIMMER_HOLD_FORCE_PERCENT", 3),
        ge=1,
        le=100,
        description="Zimmer force while carrying the part in percent",
    ),
    zimmer_startup_timeout_s: int = Field(
        default=_env_int("ZIMMER_STARTUP_TIMEOUT_S", 60),
        ge=5,
        le=180,
        description="Zimmer startup/homing timeout in seconds",
    ),
):
    cell = ctx.cell
    controller = await cell.controller(controller_name)
    motion_group = controller[0]
    cycle = ctx.cycle(extra={"app": "cube-transfer-loop"})

    slow = MotionSettings(tcp_velocity_limit=50)
    avg = MotionSettings(tcp_velocity_limit=80)
    pick_place = MotionSettings(tcp_velocity_limit=20)

    tcps = await motion_group.tcp_names()
    tcp = select_tcp(tcps)
    print(f"Available TCPs: {tcps}")
    print(f"Using TCP: {tcp}")

    grip_force_percent = max(5, _clamp_percent(zimmer_force_percent))
    hold_force_percent = min(_clamp_percent(zimmer_hold_force_percent), grip_force_percent)

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

    await cycle.start()
    try:
        print("[Gripper] Initializing...")
        await gripper.wait_until_ready()
        await gripper.set_force_percent(grip_force_percent)
        await gripper.open()
        await gripper.wait_until_stopped()

        for episode in range(1, count + 1):
            print(f"\n===== EPISODE {episode}/{count} =====")

            # 1) Start from home.
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME start")

            # 2) Pick from target and place at random table position. Store random pose.
            random_approach, random_place_pose = random_table_pose()
            print(
                "[Stored random pose] "
                f"x={float(random_place_pose.position.x):.1f}, "
                f"y={float(random_place_pose.position.y):.1f}, "
                f"z={float(random_place_pose.position.z):.1f}"
            )

            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET_APPROACH")
            await move([cartesian_ptp(TARGET_PICK, settings=pick_place)], "TARGET_PICK descend")
            print("[Gripper] CLOSE at target (grip gap=35mm)")
            await gripper.set_force_percent(grip_force_percent)
            await gripper.close()
            await gripper.wait_until_stopped()
            await gripper.set_force_percent(hold_force_percent)

            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET lift")
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM_APPROACH")
            await move([cartesian_ptp(random_place_pose, settings=pick_place)], "RANDOM descend")
            await move(
                [cartesian_ptp(offset_z_down(random_place_pose, TOUCHDOWN_DZ_MM), settings=pick_place)],
                "RANDOM touchdown",
            )
            print("[Gripper] OPEN at random (release cube)")
            await gripper.open()
            await gripper.wait_until_stopped()
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM retreat")

            # 3) Move back to home.
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME mid")

            # 4) Pick from stored random position and place to target.
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM return")
            await move([cartesian_ptp(random_place_pose, settings=pick_place)], "RANDOM_PICK descend")
            print("[Gripper] CLOSE at stored random")
            await gripper.set_force_percent(grip_force_percent)
            await gripper.close()
            await gripper.wait_until_stopped()
            await gripper.set_force_percent(hold_force_percent)

            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM lift")
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET return")
            await move([cartesian_ptp(TARGET_PICK, settings=pick_place)], "TARGET_PLACE descend")
            await move(
                [cartesian_ptp(offset_z_down(TARGET_PICK, TOUCHDOWN_DZ_MM), settings=pick_place)],
                "TARGET touchdown",
            )
            await asyncio.sleep(0.05)
            print("[Gripper] OPEN at target")
            await gripper.open()
            await gripper.wait_until_stopped()
            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET retreat")

            # 5) Move back to home and loop.
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME end")

        print("[Done] Program finished")
    finally:
        await gripper.shutdown()
        await cycle.finish()


@nova.program(
    id="cube_transfer_steps_1_3",
    name="Cube Transfer Steps 1-3",
)
async def start_cube_transfer_steps_1_3(
    ctx: nova.ProgramContext,
    count: int = Field(default=1000, ge=1, le=5000, description="Number of episodes"),
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
        default=_env_int("ZIMMER_FORCE_PERCENT", 5),
        ge=1,
        le=100,
        description="Zimmer force while closing/gripping in percent",
    ),
    zimmer_hold_force_percent: int = Field(
        default=_env_int("ZIMMER_HOLD_FORCE_PERCENT", 3),
        ge=1,
        le=100,
        description="Zimmer force while carrying the part in percent",
    ),
    zimmer_startup_timeout_s: int = Field(
        default=_env_int("ZIMMER_STARTUP_TIMEOUT_S", 60),
        ge=5,
        le=180,
        description="Zimmer startup/homing timeout in seconds",
    ),
):
    cell = ctx.cell
    controller = await cell.controller(controller_name)
    motion_group = controller[0]
    cycle = ctx.cycle(extra={"app": "cube-transfer-steps-1-3"})

    slow = MotionSettings(tcp_velocity_limit=50)
    avg = MotionSettings(tcp_velocity_limit=80)
    pick_place = MotionSettings(tcp_velocity_limit=20)

    tcps = await motion_group.tcp_names()
    tcp = select_tcp(tcps)
    print(f"Available TCPs: {tcps}")
    print(f"Using TCP: {tcp}")

    grip_force_percent = max(5, _clamp_percent(zimmer_force_percent))
    hold_force_percent = min(_clamp_percent(zimmer_hold_force_percent), grip_force_percent)

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

    await cycle.start()
    try:
        print("[Gripper] Initializing...")
        await gripper.wait_until_ready()
        await gripper.set_force_percent(grip_force_percent)
        await gripper.open()
        await gripper.wait_until_stopped()

        for episode in range(1, count + 1):
            print(f"\n===== EPISODE {episode}/{count} (steps 1-3) =====")

            # 1) Start from home.
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME start")

            # 2) Pick from target and place at random table position. Store random pose.
            random_approach, random_place_pose = random_table_pose()
            print(
                "[Stored random pose] "
                f"x={float(random_place_pose.position.x):.1f}, "
                f"y={float(random_place_pose.position.y):.1f}, "
                f"z={float(random_place_pose.position.z):.1f}"
            )

            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET_APPROACH")
            await move([cartesian_ptp(TARGET_PICK, settings=pick_place)], "TARGET_PICK descend")
            print("[Gripper] CLOSE at target (grip gap=35mm)")
            await gripper.set_force_percent(grip_force_percent)
            await gripper.close()             # moves to TARGET_GAP_M
            await gripper.wait_until_stopped()
            await gripper.set_force_percent(hold_force_percent)

            await move([cartesian_ptp(TARGET_APPROACH, settings=avg)], "TARGET lift")
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM_APPROACH")
            await move([cartesian_ptp(random_place_pose, settings=pick_place)], "RANDOM descend")
            await move(
                [cartesian_ptp(offset_z_down(random_place_pose, TOUCHDOWN_DZ_MM), settings=pick_place)],
                "RANDOM touchdown",
            )
            print("[Gripper] OPEN at random (release cube)")
            await gripper.open()
            await gripper.wait_until_stopped()
            await move([cartesian_ptp(random_approach, settings=avg)], "RANDOM retreat")

            # 3) Move back to home.
            await move([cartesian_ptp(HOME_POSE, settings=slow)], "HOME end")

        print("[Done] Program finished")
    finally:
        await gripper.shutdown()
        await cycle.finish()


if __name__ == "__main__":
    run_program(start_cube_transfer)