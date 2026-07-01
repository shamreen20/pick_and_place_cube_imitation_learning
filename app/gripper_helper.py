import asyncio

from zimmer_gripper_controller import (
    GripperConfig,
    GripperSession,
    JawGapConfig,
    LimitConfig,
    ModbusConfig,
    SessionConfig,
)

# settle_time_s: how long (seconds) to block after issuing a gripper command,
# waiting for the jaw to physically complete the move. Matches minimal_move.py.
GRIPPER_SETTLE_S = 0.5


class MockGripper:
    async def wait_until_ready(self):
        print("[MockGripper] ready")
        await asyncio.sleep(0.1)

    async def open(self, settle_time_s: float = GRIPPER_SETTLE_S):
        print("[MockGripper] open")
        await asyncio.sleep(settle_time_s)

    async def close(self, settle_time_s: float = GRIPPER_SETTLE_S):
        print("[MockGripper] close")
        await asyncio.sleep(settle_time_s)

    async def release(self, settle_time_s: float = GRIPPER_SETTLE_S):
        print("[MockGripper] release")
        await asyncio.sleep(settle_time_s)

    async def set_force_percent(self, force_percent: int):
        print(f"[MockGripper] set_force_percent={force_percent}%")
        await asyncio.sleep(0.01)

    async def shutdown(self):
        return None


class ZimmerGripper:
    """
    Async wrapper around GripperSession (synchronous, threaded).

        All parameters match the working minimal_move.py configuration:
            - force_percent=4, drive_velocity_percent=30
      - device modes: positioning=50, force_outside=62, force_inside=72,
                      preposition_outside=82, preposition_inside=92
      - startup_homing_mode=10
      - jaw range: 1 mm (closed) … 80 mm (open)
      - device position range: 1 mm … 40 mm (GEH6060 physical stroke)
    """

    def __init__(
        self,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        io_link_port: int = 0,
        timeout_s: float = 1.0,
        jaw_gap_open_m: float = 0.080,
        jaw_gap_close_m: float = 0.045,
        device_pos_min_m: float = 0.045,
        device_pos_max_m: float = 0.080,
        force_percent: int = 3,
        drive_velocity_percent: int = 30,
        startup_timeout_s: float = 25.0,
    ):
        jaw_cfg = JawGapConfig(
            jaw_gap_min_m=jaw_gap_close_m,
            jaw_gap_max_m=jaw_gap_open_m,
            device_pos_min_m=device_pos_min_m,
            device_pos_max_m=device_pos_max_m,
        )
        cfg = SessionConfig(
            modbus=ModbusConfig(
                host=host,
                port=port,
                unit_id=unit_id,
                io_link_port=io_link_port,
                timeout_s=timeout_s,
            ),
            gripper=GripperConfig(
                limits=LimitConfig(
                    opening_min_m=jaw_cfg.device_pos_min_m,
                    opening_max_m=jaw_cfg.device_pos_max_m,
                    force_min_percent=1,
                    force_max_percent=100,
                    velocity_min_percent=1,
                    velocity_max_percent=100,
                ),
                grip_force_percent=force_percent,
                drive_velocity_percent=drive_velocity_percent,
                device_mode_positioning=50,
                device_mode_force_outside=62,
                device_mode_force_inside=72,
                device_mode_preposition_outside=82,
                device_mode_preposition_inside=92,
                startup_homing_mode=10,
                invert_opening_direction=False,
            ),
            jaw_gap=jaw_cfg,
            startup_timeout_s=startup_timeout_s,
        )
        self._session = GripperSession(cfg)
        self._connected = False

    async def wait_until_ready(self):
        """Connect to the TBEN and wait for homing + startup to complete.
        The session internally opens the gripper at the end of startup."""
        if self._connected:
            return
        await asyncio.to_thread(self._session.connect)
        await asyncio.to_thread(self._session.wait_until_ready)
        self._connected = True
        print("[ZimmerGripper] ready")

    async def open(self, settle_time_s: float = GRIPPER_SETTLE_S):
        """Open to maximum jaw gap and wait settle_time_s for the move to complete."""
        await asyncio.to_thread(self._session.open, settle_time_s)
        print(f"[ZimmerGripper] open (settled {settle_time_s}s)")

    async def close(self, settle_time_s: float = GRIPPER_SETTLE_S):
        """Close to minimum jaw gap (grip) and wait settle_time_s for the move to complete."""
        await asyncio.to_thread(self._session.close_gripper, settle_time_s)
        print(f"[ZimmerGripper] close (settled {settle_time_s}s)")

    async def move_to_gap_m(self, gap_m: float, settle_time_s: float = GRIPPER_SETTLE_S):
        """Move to an arbitrary jaw gap in metres."""
        await asyncio.to_thread(self._session.move_to_gap_m, gap_m, settle_time_s)
        print(f"[ZimmerGripper] moved to gap {gap_m*1000:.1f} mm (settled {settle_time_s}s)")

    async def release(self, settle_time_s: float = GRIPPER_SETTLE_S):
        await self.open(settle_time_s)

    async def state(self):
        """Return the current SessionState snapshot (non-blocking, thread-safe)."""
        return await asyncio.to_thread(self._session.state)

    async def set_force_percent(self, force_percent: int):
        """Set gripping force while running (1-100%)."""
        clamped = max(1, min(100, int(force_percent)))
        applied = await asyncio.to_thread(self._session.set_force_percent, clamped)
        print(f"[ZimmerGripper] set force to {applied}%")
        return applied

    async def set_velocity_percent(self, velocity_percent: int):
        """Set jaw drive velocity while running (1-100%)."""
        clamped = max(1, min(100, int(velocity_percent)))
        applied = await asyncio.to_thread(self._session.set_velocity_percent, clamped)
        print(f"[ZimmerGripper] set velocity to {applied}%")
        return applied

    async def shutdown(self):
        if not self._connected:
            return
        await asyncio.to_thread(self._session.close)
        self._connected = False
        print("[ZimmerGripper] disconnected")
