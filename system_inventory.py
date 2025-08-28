
import argparse
import csv
import json
import os
import platform
import socket
import time
from datetime import datetime


import psutil


def get_uptime_seconds() -> float:
    try:
        return time.time() - psutil.boot_time()
    except Exception:
        return float("nan")


def human_bytes(n: int) -> str:
    symbols = ("B", "KB", "MB", "GB", "TB")
    i = 0
    f = float(n)
    while f >= 1024 and i < len(symbols) - 1:
        f /= 1024
        i += 1
    return f"{f:.2f} {symbols[i]}"


def collect_inventory(tags: list[str] | None = None) -> dict:
    uname = platform.uname()
    mem = psutil.virtual_memory()

    # CPU load averages (may not exist on Windows)
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = None

    # Disks
    disks = []
    for p in psutil.disk_partitions(all = False):
        try:
            usage = psutil.disk_usage(p.mountpoint)
            disks.append({
                "device": p.device,
                "fstype": p.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent_used": usage.percent,
            })
        except PermissionError:
            continue
        
    # Network interfaces
    nics = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    for ifname, addr_list in addrs.items():
        entry = {"iface": ifname, "is_up": bool(stats.get(ifname).isup) if ifname in stats else None, "ipv4": [], "ipv6": []}
        for a in addr_list:
            if getattr(a, 'family', None) == socket.AF_INET:
                entry["ipv4"].append(a.address)
            elif getattr(a, 'family', None) == socket.AF_INET6:
                # strip %zone
                entry["ipv6"].append(a.address.split('%')[0])
        nics.append(entry)
        
    # Basic packages (Linux)
    pkg_summary = None
    if uname.system.lower() == "linux":
        try:
            import subprocess
            if os.path.exists("/usr/bin/dpkg-query"):
                out = subprocess.check_output(["dpkg-query", "-f", "${binary:Package}\n", "-W"], text = True, timeout = 10)
                pkg_summary = {"manager": "dpkg", "count": len([l for l in out.splitlines() if l.strip()])}
            elif os.path.exists("/usr/bin/rpm"):
                out = subprocess.check_output(["rpm", "-qa"], text = True, timeout = 10)
                pkg_summary = {"manager": "rpm", "count": len([l for l in out.splitlines() if l.strip()])}
        except Exception:
            pkg_summary = None
            
    info = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "os": {
        "system": uname.system,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "processor": uname.processor,
        },
        "cpu": {
            "physical_cores": psutil.cpu_count(logical = False),
            "logical_cpus": psutil.cpu_count(logical = True),
            "loadavg_1m": load1,
            "loadavg_5m": load5,
            "loadavg_15m": load15,
            "freq_mhz": getattr(psutil.cpu_freq(), 'current', None),
        },
        "memory": {
            "total_bytes": int(mem.total),
            "available_bytes": int(mem.available),
            "percent_used": float(mem.percent),
        },
        "uptime_seconds": get_uptime_seconds(),
        "disks": disks,
        "network": nics,
        "packages": pkg_summary,
        "tags": tags or [],
    }
    return info   
        
        
def write_csv(data: dict, out_path: str | None):
    # Flatten a subset of fields for CSV row
    row = {
        "timestamp": data["timestamp"],
        "hostname": data["hostname"],
        "fqdn": data["fqdn"],
        "os_system": data["os"]["system"],
        "os_release": data["os"]["release"],
        "logical_cpus": data["cpu"]["logical_cpus"],
        "mem_total": human_bytes(data["memory"]["total_bytes"]),
        "mem_used_pct": data["memory"]["percent_used"],
        "uptime_seconds": int(data["uptime_seconds"] if data["uptime_seconds"] == data["uptime_seconds"] else 0),
        "disk_count": len(data["disks"]),
        "iface_count": len(data["network"]),
        "tags": ",".join(data.get("tags", [])),
    }
    writer = csv.DictWriter(open(out_path, "w") if out_path else os.fdopen(1, "w"), fieldnames = row.keys())
    writer.writeheader()
    writer.writerow(row)
    
    
def main():
    ap = argparse.ArgumentParser(description = "Collect system inventory and export to CSV or JSON")
    ap.add_argument("--format", choices = ["csv", "json"], default = "json")
    ap.add_argument("--out", help = "Output file (default: stdout)")
    ap.add_argument("--pretty", action = "store_true", help = "Pretty‑print JSON")
    ap.add_argument("--tags", help = "Comma‑separated tags to add, e.g. 'lab,linux'")
    args = ap.parse_args()


    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    data = collect_inventory(tags = tags)


    if args.format == "json":
        dump = json.dumps(data, indent = 2 if args.pretty else None)
        if args.out:
            with open(args.out, "w") as f:
                f.write(dump + "\n")
        else:
            print(dump)
    else:
        write_csv(data, args.out)
        
        
if __name__ == "__main__":
    main()
