#!/usr/bin/env python3
"""Collect live local snapshots; engine never writes system configuration."""
import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


def capture(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=25,
                           env={**os.environ, "LC_ALL": "C"})
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["before", "after"], required=True)
    p.add_argument("--section", choices=["all", "1", "2", "3", "4", "5"], default="all")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if os.geteuid() != 0:
        p.error("audit cần root để đọc cấu hình, quyền và trạng thái tài khoản")
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o750)
    raw = out / "raw"; raw.mkdir(mode=0o750)
    env = dict(os.environ)
    snapshots = {"NGINX_T_FILE": ["nginx", "-T"], "NGINX_V_FILE": ["nginx", "-V"],
                 "SS_FILE": ["ss", "-tulnp"], "APT_FILE": ["apt-cache", "policy", "nginx"]}
    codes = {}
    for key, cmd in snapshots.items():
        rc, stdout, stderr = capture(cmd)
        codes[key] = rc
        f = raw / (key.lower() + ".txt")
        f.write_text((stdout + stderr) if key == "NGINX_V_FILE" else stdout)
        (raw / (key.lower() + ".stderr.txt")).write_text(stderr)
        env[key] = str(f)
    env.update(STAGE=a.stage, AUDIT_SECTION=a.section, AUDIT_SOURCE="live",
               REPORT_TXT=str(out / "audit-report.txt"), SUMMARY_CSV=str(out / "audit-summary.csv"),
               REPORT_JSON=str(out / "audit.json"), SNAPSHOT_STATUS=json.dumps(codes),
               AUDIT_RAW_DIR=str(raw), NGINX_CONF_DIR="/etc/nginx")
    (raw / "commands.json").write_text(json.dumps({"hostname": socket.gethostname(),
                                                    "commands": snapshots, "exit_codes": codes}, indent=2))
    try:
        return subprocess.call([sys.executable, str(Path(__file__).with_name("engine.py"))], env=env)
    finally:
        uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
        for f in out.rglob("*"):
            f.chmod(0o750 if f.is_dir() else 0o640)
            if uid and gid: os.chown(f, int(uid), int(gid))
        if uid and gid: os.chown(out, int(uid), int(gid))


if __name__ == "__main__":
    raise SystemExit(main())
