"""Minimal synchronous Modbus TCP client wrapper for TBEN-S2-4IOL."""

from __future__ import annotations

from inspect import signature

from pymodbus.client import ModbusTcpClient

from .config import ModbusConfig
from .protocol import InputPDU, OutputPDU


class TbenModbusClient:
    """Read/write Zimmer process data through Turck TBEN Modbus mapping."""

    def __init__(self, config: ModbusConfig):
        self.config = config
        self._client = ModbusTcpClient(
            host=config.host,
            port=config.port,
            timeout=config.timeout_s,
        )
        self._read_unit_kwarg = self._detect_unit_kwarg(self._client.read_input_registers)
        self._write_unit_kwarg = self._detect_unit_kwarg(self._client.write_registers)

    def connect(self) -> bool:
        """Open TCP connection to the Modbus server."""
        return bool(self._client.connect())

    def close(self) -> None:
        """Close TCP connection."""
        self._client.close()

    def read_input_pdu(self) -> InputPDU:
        """Read Zimmer input PDU (StatusWord, Diagnosis, ActualPosition)."""
        rr = self._client.read_input_registers(
            address=self.config.input_base_register,
            count=3,
            **{self._read_unit_kwarg: self.config.unit_id},
        )
        if rr.isError():
            raise RuntimeError(f"Modbus read_input_registers failed: {rr}")
        registers = (
            [self._swap_u16(v) for v in rr.registers]
            if self.config.swap_word_bytes
            else rr.registers
        )
        return InputPDU.from_registers(registers)

    def write_output_pdu(self, pdu: OutputPDU) -> None:
        """Write Zimmer output PDU to 8 holding registers."""
        values = pdu.to_registers()
        if self.config.swap_word_bytes:
            values = [self._swap_u16(v) for v in values]

        wr = self._client.write_registers(
            address=self.config.output_base_register,
            values=values,
            **{self._write_unit_kwarg: self.config.unit_id},
        )
        if wr.isError():
            raise RuntimeError(f"Modbus write_registers failed: {wr}")

    @staticmethod
    def _swap_u16(value: int) -> int:
        return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)

    @staticmethod
    def _detect_unit_kwarg(method) -> str:
        params = signature(method).parameters
        if "device_id" in params:
            return "device_id"
        if "slave" in params:
            return "slave"
        if "unit" in params:
            return "unit"
        raise RuntimeError("Could not detect pymodbus unit-id parameter name")
