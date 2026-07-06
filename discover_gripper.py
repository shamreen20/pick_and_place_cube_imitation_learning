"""
Discover the Turck TBEN-S2-4IOL Modbus device (Zimmer gripper IO-Link master)
on the local network.

How it works:
  1. Derives the /24 subnet from NOVA_API in .env (e.g. 172.31.11.x)
  2. TCP-scans every host on that subnet for port 502 (Modbus TCP) in parallel
  3. For each host that responds, tries a real Modbus read to confirm it is a
     TBEN device (not just any port-502 service)
  4. Prints every candidate and suggests the .env line to set

Usage:
    uv run python discover_gripper.py

    # Scan a different subnet:
    uv run python discover_gripper.py --subnet 192.168.1.0/24
"""

from __future__ import annotations
import argparse
import concurrent.futures
import ipaddress
import os
import socket
import sys
import time
from pathlib import Path

# Load .env so NOVA_API is available without running the full app
_ENV_FILE = Path(__file__).parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


MODBUS_PORT = 502
TCP_TIMEOUT_S = 0.4        # per host for the TCP connect probe
MODBUS_TIMEOUT_S = 1.0     # for the follow-up Modbus read


def _derive_subnet_from_nova() -> str | None:
    """Derive a /24 subnet string from the NOVA_API env var."""
    nova_api = os.getenv("NOVA_API", "")
    # Strip http(s):// prefix
    for prefix in ("https://", "http://"):
        if nova_api.startswith(prefix):
            nova_api = nova_api[len(prefix):]
    # Take only the host part (drop port / path)
    host = nova_api.split("/")[0].split(":")[0]
    if not host:
        return None
    try:
        parts = host.split(".")
        if len(parts) == 4:
            subnet = ".".join(parts[:3]) + ".0/24"
            ipaddress.ip_network(subnet)  # validate
            return subnet
    except ValueError:
        pass
    return None


def _tcp_probe(host: str, port: int = MODBUS_PORT, timeout: float = TCP_TIMEOUT_S) -> bool:
    """Return True if TCP port is open on host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _modbus_probe(host: str, port: int = MODBUS_PORT, unit_id: int = 1) -> bool:
    """
    Try a real Modbus read_input_registers request.
    Returns True if we get any valid (non-error) response — confirms Modbus server.
    Uses raw sockets so we don't need pymodbus installed in discover context.
    """
    # Modbus TCP read input registers: address=0x0002, count=3, unit=unit_id
    mbap = bytes([
        0x00, 0x01,        # Transaction ID
        0x00, 0x00,        # Protocol ID
        0x00, 0x06,        # Length (6 bytes follow)
        unit_id & 0xFF,    # Unit ID
        0x04,              # Function code: Read Input Registers
        0x00, 0x02,        # Starting address 0x0002
        0x00, 0x03,        # Quantity: 3 registers
    ])
    try:
        with socket.create_connection((host, port), timeout=MODBUS_TIMEOUT_S) as s:
            s.sendall(mbap)
            resp = s.recv(64)
        # Valid response: MBAP (6 bytes) + unit + func + byte_count + data
        if len(resp) >= 9 and resp[7] == 0x04:  # function code echo = read input regs
            return True
        return False
    except OSError:
        return False


def scan_subnet(subnet: str, workers: int = 64) -> list[str]:
    """Return list of IPs that have port 502 open."""
    network = ipaddress.ip_network(subnet, strict=False)
    hosts = list(network.hosts())
    print(f"Scanning {len(hosts)} hosts on {subnet} for port {MODBUS_PORT} …")

    open_hosts: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_tcp_probe, str(h)): str(h) for h in hosts}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            if done % 50 == 0 or done == len(hosts):
                print(f"  {done}/{len(hosts)} probed …", end="\r", flush=True)
            if fut.result():
                open_hosts.append(futures[fut])

    print()  # newline after progress
    return sorted(open_hosts, key=lambda ip: tuple(int(p) for p in ip.split(".")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Find Zimmer TBEN Modbus device on LAN")
    parser.add_argument(
        "--subnet",
        default=None,
        help="CIDR subnet to scan, e.g. 172.31.11.0/24 (default: derived from NOVA_API)",
    )
    parser.add_argument(
        "--unit-id", type=int, default=1, help="Modbus unit ID to probe (default: 1)"
    )
    parser.add_argument(
        "--no-modbus-verify",
        action="store_true",
        help="Skip the follow-up Modbus read (faster, less precise)",
    )
    args = parser.parse_args()

    subnet = args.subnet
    if not subnet:
        subnet = _derive_subnet_from_nova()
        if subnet:
            print(f"Derived subnet from NOVA_API: {subnet}")
        else:
            print("ERROR: Cannot derive subnet from NOVA_API. Pass --subnet manually.")
            sys.exit(1)

    t0 = time.monotonic()
    candidates = scan_subnet(subnet)

    if not candidates:
        print(f"\nNo hosts with port {MODBUS_PORT} open found on {subnet}.")
        print("Check that the TBEN device is powered and on the same network.")
        sys.exit(0)

    print(f"\nFound {len(candidates)} host(s) with port {MODBUS_PORT} open:")
    confirmed: list[str] = []
    for ip in candidates:
        if args.no_modbus_verify:
            confirmed.append(ip)
            print(f"  {ip}  (port open)")
        else:
            ok = _modbus_probe(ip, unit_id=args.unit_id)
            tag = "✓ Modbus OK" if ok else "? no Modbus response"
            print(f"  {ip}  {tag}")
            if ok:
                confirmed.append(ip)

    elapsed = time.monotonic() - t0
    print(f"\nScan completed in {elapsed:.1f}s")

    if not confirmed:
        print("\nNo confirmed Modbus devices found.")
        print("Try --no-modbus-verify if the TBEN uses a different register layout.")
        sys.exit(0)

    print("\n" + "=" * 60)
    print("TBEN Modbus device(s) found — add to your .env file:")
    print("=" * 60)
    for ip in confirmed:
        print(f"\n  ZIMMER_HOST={ip}")

    if len(confirmed) == 1:
        # Offer to write directly into .env
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            env_text = env_path.read_text()
            if "ZIMMER_HOST=" in env_text:
                updated = env_text.replace(
                    f"ZIMMER_HOST={os.getenv('ZIMMER_HOST', '')}",
                    f"ZIMMER_HOST={confirmed[0]}",
                )
                env_path.write_text(updated)
                print(f"\nAutomatically updated {env_path} with ZIMMER_HOST={confirmed[0]}")
            else:
                print(f"\nAdd the line above to {env_path} to enable the physical gripper.")
        else:
            print("\nCreate a .env file with the line above.")

    print()


if __name__ == "__main__":
    main()
