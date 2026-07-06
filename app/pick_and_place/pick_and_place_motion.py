import asyncio # for non-blocking waits during retry/reset flow.
import os  # read .env variable . e.g: cell_name
from nova.exceptions import InitMovementFailed
from wandelbots_api_client.v2_pydantic.models import SettableRobotSystemMode  # monitor/control

REQUIRED_TCP = "umi_gripper"


def select_tcp(tcps: list[str]) -> str:
    preferred = [
        REQUIRED_TCP,
        "umi_gripper",
        "OnRobot_Single",
        "flange",
        "tool0",
    ]
    return next((name for name in preferred if name in tcps), tcps[0])  #  Returns first matching preferred TCP, otherwise defaults to first available tcps entry.


async def move_with_retry(
    motion_group, # motion_group parameter provides planning/execution API.
    action_list, # action_list parameter contains movement actions (for example cartesian_ptp actions).
    label: str,
    tcp: str,
    controller_name: str,
) -> None:
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
            cell=os.getenv("CELL_NAME", "cell"), # Uses CELL_NAME env var with fallback cell.
            controller=controller_name,
            mode=SettableRobotSystemMode.ROBOT_SYSTEM_MODE_MONITOR,
        )
        await asyncio.sleep(1.0)  # Waits 1 second to allow mode transition to settle.
        await motion_group._api_client.controller_api.set_default_mode(
            cell=os.getenv("CELL_NAME", "cell"),
            controller=controller_name,
            mode=SettableRobotSystemMode.ROBOT_SYSTEM_MODE_CONTROL,
        )
        await asyncio.sleep(1.0)

        traj_retry = await motion_group.plan(action_list, tcp) # Re-plans trajectory after mode reset (fresh plan).
        await motion_group.execute(traj_retry, tcp, actions=action_list)  # Executes retry trajectory once; if this fails, exception propagates to caller.


"""This module standardizes TCP selection and wraps motion execution with a targeted one-time recovery for controller mode-lock failures, so orchestration code stays clean and robust."""