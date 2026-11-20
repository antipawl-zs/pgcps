#!/usr/bin/env python3
"""Discover and inventory Aruba switches across configured sites."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
SITES_PATH = Path(__file__).with_name("sites.json")
OUT_JSON = ROOT / "www" / "data" / "inventory.json"
ENV_PATH = ROOT / ".env"

ARUBA_HINTS = re.compile(
    r"aruba|procurve|hpe|aos-?cx|aos-?s|jl\d|jl\d{3}|r8|6300|6200|6100|2930|3810|5400|8320|8325|8400",
    re.I,
)

COMMANDS = [
    "show system",
    "show version",
    "show inventory",
    "show modules",
    "show interface brief",
    "show interfaces brief",
    "show vlan summary",
    "show vlans",
    "hostname",
]


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def credential_profiles() -> list[dict]:
    load_dotenv()
    profiles = []
    for key in ("DACLARK", "ADMIN"):
        user = os.environ.get(f"SWITCH_USER_{key}", "").strip()
        password = os.environ.get(f"SWITCH_PASS_{key}", "")
        if user and password:
            profiles.append({"name": key.lower(), "username": user, "password": password})
    return profiles


def candidate_ips(site: dict, discovery: dict) -> list[str]:
    first = int(site["first_octet"])
    second = int(site["second_octet"])
    ips = []
    for third in discovery["third_octets"]:
        for host in discovery["host_octets"]:
            ips.append(f"{first}.{second}.{third}.{host}")
    return ips


def port_open(ip: str, port: int, timeout: float) -> bool:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((ip, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def discover_hosts(site: dict, discovery: dict) -> list[dict]:
    timeout = float(discovery.get("connect_timeout_sec", 0.5))
    ports = discovery.get("ports", [22])
    ips = candidate_ips(site, discovery)
    found = []

    def check(ip: str):
        open_ports = [p for p in ports if port_open(ip, p, timeout)]
        if open_ports:
            return {"ip": ip, "open_ports": open_ports}
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
        for result in pool.map(check, ips):
            if result:
                found.append(result)
    return found


def run_ssh_commands(ip: str, username: str, password: str) -> dict:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    outputs = {}
    banner = ""
    try:
        client.connect(
            ip,
            username=username,
            password=password,
            timeout=8,
            allow_agent=False,
            look_for_keys=False,
            auth_timeout=8,
        )
        transport = client.get_transport()
        if transport and transport.remote_version:
            banner = transport.remote_version
        for command in COMMANDS:
            try:
                _stdin, stdout, stderr = client.exec_command(command, timeout=12)
                text = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                if text.strip():
                    outputs[command] = text
                elif err.strip():
                    outputs[command] = err
            except Exception as exc:  # noqa: BLE001
                outputs[command] = f"[error] {exc}"
        return {"ok": True, "banner": banner, "outputs": outputs, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "banner": banner, "outputs": outputs, "error": str(exc)}
    finally:
        client.close()


def first_match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return match.group(1).strip()
    return None


def count_up_interfaces(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if re.search(r"\bup\b", line, re.I) and re.search(r"\b(eth|1\/|2\/|3\/|gigabit|trk|lag|port)\b", line, re.I):
            count += 1
        elif re.search(r"^\S+\s+.+\s+up\s+", line, re.I):
            count += 1
    return count


def parse_switch(ip: str, profile: str, ssh_result: dict) -> dict:
    outputs = ssh_result.get("outputs") or {}
    blob = "\n".join(outputs.values())
    hostname = first_match(
        [
            r"^Hostname\s*:\s*(.+)$",
            r"^System Name\s*:\s*(.+)$",
            r"^hostname\s+(\S+)",
        ],
        blob,
    ) or ip
    model = first_match(
        [
            r"^Chassis\s*:\s*(.+)$",
            r"^System Description\s*:\s*(.+)$",
            r"Product Name\s*:\s*(.+)$",
            r"\b(JL\d+\w*|R8\w+|6300[A-Z0-9\-]+|6200[A-Z0-9\-]+|2930[A-Z0-9\-]+|3810[A-Z0-9\-]+)\b",
        ],
        blob,
    )
    serial = first_match(
        [
            r"Serial\s*(?:Number|#)\s*:\s*(\S+)",
            r"^Serial Number\s*:\s*(\S+)",
        ],
        blob,
    )
    version = first_match(
        [
            r"Software Version\s*:\s*(\S+)",
            r"Primary Image\s*:\s*(\S+)",
            r"Version\s*:\s*([^\n]+)",
            r"ArubaOS(?:-CX)?\s+([^\s,]+)",
        ],
        blob,
    )
    up_ifaces = 0
    for key in ("show interface brief", "show interfaces brief"):
        if key in outputs:
            up_ifaces = max(up_ifaces, count_up_interfaces(outputs[key]))
    vlan_count = None
    for key in ("show vlan summary", "show vlans"):
        if key in outputs:
            vlan_count = len(re.findall(r"^\s*\d+\s+", outputs[key], re.M))
            if vlan_count:
                break

    is_aruba = bool(ARUBA_HINTS.search(blob) or ARUBA_HINTS.search(ssh_result.get("banner") or ""))
    if not is_aruba and ssh_result.get("ok") and any(k in outputs for k in ("show system", "show inventory")):
        # Aruba CLI accepted show commands; treat as likely Aruba if auth succeeded with useful output
        is_aruba = "show system" in outputs or "show inventory" in outputs

    return {
        "ip": ip,
        "profile_used": profile,
        "reachable": bool(ssh_result.get("ok")),
        "is_aruba": is_aruba,
        "hostname": hostname,
        "model": model,
        "serial": serial,
        "software": version,
        "up_interfaces": up_ifaces,
        "vlan_count": vlan_count,
        "banner": ssh_result.get("banner"),
        "error": ssh_result.get("error"),
        "raw_commands": sorted(outputs.keys()),
    }


def inventory_host(host: dict, profiles: list[dict]) -> dict:
    last_error = None
    for profile in profiles:
        result = run_ssh_commands(host["ip"], profile["username"], profile["password"])
        if result["ok"]:
            parsed = parse_switch(host["ip"], profile["name"], result)
            parsed["open_ports"] = host.get("open_ports", [])
            return parsed
        last_error = result.get("error")
    return {
        "ip": host["ip"],
        "profile_used": None,
        "reachable": False,
        "is_aruba": False,
        "hostname": host["ip"],
        "model": None,
        "serial": None,
        "software": None,
        "up_interfaces": 0,
        "vlan_count": None,
        "banner": None,
        "error": last_error or "authentication failed for all profiles",
        "open_ports": host.get("open_ports", []),
        "raw_commands": [],
    }


def scan_site(site: dict, discovery: dict, profiles: list[dict]) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    hosts = discover_hosts(site, discovery)
    switches = []
    for host in hosts:
        switches.append(inventory_host(host, profiles))

    aruba = [s for s in switches if s.get("is_aruba")]
    reachable = [s for s in switches if s.get("reachable")]
    return {
        "id": site["id"],
        "name": site["name"],
        "abbreviation": site.get("abbreviation"),
        "network_prefix": site.get("network_prefix"),
        "scanned_at": started,
        "candidates_probed": len(candidate_ips(site, discovery)),
        "ssh_open_hosts": len(hosts),
        "switch_count": len(aruba) if aruba else len(reachable),
        "aruba_count": len(aruba),
        "reachable_count": len(reachable),
        "up_interface_total": sum(s.get("up_interfaces") or 0 for s in aruba or reachable),
        "switches": aruba or reachable or switches,
        "discovery_hosts": hosts,
        "status": "ok" if hosts else "unreachable",
        "message": None
        if hosts
        else "No SSH listeners found on discovery ranges. Confirm VIA/VPN reachability to this site network.",
    }


def main() -> int:
    config = json.loads(SITES_PATH.read_text(encoding="utf-8"))
    profiles = credential_profiles()
    if not profiles:
        print("No switch credentials found in environment/.env", file=sys.stderr)
        return 2

    sites_out = []
    for site in config["sites"]:
        print(f"Scanning {site['name']} ({site.get('network_prefix')}) ...", flush=True)
        result = scan_site(site, config["discovery"], profiles)
        print(
            f"  ssh_open={result['ssh_open_hosts']} aruba={result['aruba_count']} "
            f"reachable={result['reachable_count']} status={result['status']}",
            flush=True,
        )
        sites_out.append(result)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "vendor": "Aruba",
        "site_count": len(sites_out),
        "totals": {
            "sites_scanned": len(sites_out),
            "sites_reachable": sum(1 for s in sites_out if s["status"] == "ok"),
            "ssh_open_hosts": sum(s["ssh_open_hosts"] for s in sites_out),
            "aruba_switches": sum(s["aruba_count"] for s in sites_out),
            "reachable_switches": sum(s["reachable_count"] for s in sites_out),
            "up_interfaces": sum(s["up_interface_total"] for s in sites_out),
        },
        "sites": sites_out,
        "credentials_profiles": [p["name"] for p in profiles],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
