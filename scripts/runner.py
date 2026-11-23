"""Local workflow with immutable stage directories and explicit failure outcomes."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_STATUSES = {"PASS", "FAIL", "ERROR", "REVIEW"}


def parser():
    p = argparse.ArgumentParser(description="CIS NGINX: audit / remediate / run (VM local)")
    p.add_argument("action", choices=["audit", "remediate", "run"])
    p.add_argument("--mode", choices=["local", "remote"], default="local")
    p.add_argument("--section", choices=["all", "1", "2", "3", "4", "5"], default="all")
    p.add_argument("--stage", choices=["before", "after"], default="before")
    p.add_argument("--run-id", help="Use the same ID for separate before/remediate/after calls")
    p.add_argument("--idempotence", action="store_true", help="Run remediation a second time")
    p.add_argument("--ask-become-pass", action="store_true", help="Prompt sudo once, and Ansible -K")
    p.add_argument("--vars-file", type=Path, help="Additional Ansible YAML vars; see config/lab.example.yml")
    return p


def safe_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise ValueError("run ID / hostname must contain only letters, digits, dot, underscore or dash")
    return value


def execute(argv, logfile):
    """No shell interpolation; keep console output and a copy of the exact argv."""
    with logfile.open("x", encoding="utf-8") as log:
        log.write("ARGV " + json.dumps([str(x) for x in argv], ensure_ascii=False) + "\n")
        log.flush()
        proc = subprocess.Popen([str(x) for x in argv], cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace")
        try:
            for line in proc.stdout:
                print(line, end="", flush=True)
                log.write(line)
            return proc.wait()
        except BaseException:
            proc.terminate()
            proc.wait()
            raise


def summarize(folder, action, section, codes):
    result = {"action": action, "section": section, "stages": codes,
              "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(), "hosts": {}}
    for stage in ["before", "after"]:
        path = folder / stage / "audit.json"
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("section") != section:
                raise ValueError("Cannot compare evidence with different section scopes")
            result[stage] = data["counts"]
    before, after = folder / "before/audit.json", folder / "after/audit.json"
    if before.exists() and after.exists():
        a = {r["cis_id"]: r for r in json.loads(before.read_text())["results"]}
        b = {r["cis_id"]: r for r in json.loads(after.read_text())["results"]}
        result["comparison"] = [{"cis_id": key, "before": a[key]["status"],
                                 "after": b[key]["status"]} for key in a if key in b]
    (folder / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def workflow(args, folder, audit_cmd, remedy_cmd, run=execute):
    """FAIL=1 before is a valid baseline. ERROR=2 must not trigger changes."""
    codes = {}

    def audit(stage):
        target = folder / stage
        if target.exists():
            raise FileExistsError(f"Evidence already exists: {target}; use a new run ID")
        rc = run(audit_cmd + ["--stage", stage, "--section", args.section,
                             "--output", str(target)], folder / f"{stage}.log")
        codes[stage] = rc
        return rc

    def remedy(label):
        rc = run(remedy_cmd, folder / f"{label}.log")
        codes[label] = rc
        return rc

    if args.action == "audit":
        return audit(args.stage), codes
    if args.action == "remediate":
        return (0 if remedy("remediate") == 0 else 2), codes
    if audit("before") not in (0, 1):
        return 2, codes
    remedy_rc = remedy("remediate")
    # Read-only post-audit is useful even if remediation failed part-way.
    after_rc = audit("after")
    if remedy_rc or after_rc >= 2:
        return 2, codes
    if args.idempotence:
        if remedy("idempotence"):
            return 2, codes
        recap = json.loads((folder / "ansible-recap.json").read_text())
        if not recap or any(v.get("changed", 0) or v.get("failures", 0)
                            or v.get("unreachable", 0) for v in recap.values()):
            codes["idempotence_result"] = 1
            return 1, codes
        # The second run may change state; verify again without overwriting after/.
        post = run(audit_cmd + ["--stage", "after", "--section", args.section,
                               "--output", str(folder / "after-idempotence")],
                   folder / "after-idempotence.log")
        codes["after-idempotence"] = post
        if post:
            return post, codes
    return after_rc, codes


def main(argv=None):
    args = parser().parse_args(argv)
    if args.mode == "remote":
        print("Remote chưa triển khai. Xem docs/REMOTE.md và inventory/hosts-aws.yml.", file=sys.stderr)
        return 2
    try:
        run_id = safe_id(args.run_id or (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                        + "-" + uuid.uuid4().hex[:8]))
        vars_hash = hashlib.sha256(args.vars_file.resolve(strict=True).read_bytes()).hexdigest() if args.vars_file else None
        host = safe_id(socket.gethostname())
        folder = ROOT / "evidence" / run_id / host
        folder.mkdir(parents=True, exist_ok=True, mode=0o750)
        lock_path = ROOT / "evidence/.local.lock"
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            metadata = folder / "manifest.json"
            identity = {"run_id": run_id, "hostname": host, "section": args.section,
                        "vars_sha256": vars_hash,
                        "mode": "local", "source": "live", "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            if metadata.exists():
                old = json.loads(metadata.read_text())
                if old["section"] != args.section or old.get("vars_sha256") != vars_hash:
                    raise ValueError("A run ID must keep the same section scope and vars file")
            else:
                try:
                    identity["commit"] = subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
                except (OSError, subprocess.CalledProcessError):
                    identity["commit"] = "uncommitted"
                metadata.write_text(json.dumps(identity, indent=2) + "\n")
            if os.geteuid() == 0:
                prefix = []
            else:
                if not shutil.which("sudo"):
                    raise ValueError("Cần sudo trên VM Ubuntu")
                validation = ["sudo", "-v"] if args.ask_become_pass else ["sudo", "-n", "true"]
                if subprocess.call(validation):
                    raise ValueError("Cần quyền sudo; chạy lại với --ask-become-pass")
                prefix = ["sudo", "-n"]
            audit_cmd = prefix + ["python3", str(ROOT / "audit/collect.py")]
            extra = {"nginx_cis_sections": list(range(1, 6)) if args.section == "all" else [int(args.section)],
                     "nginx_cis_backup_dir": "/var/backups/nginx-cis/" + run_id}
            remedy_cmd = ["ansible-playbook", "-i", str(ROOT / "inventory/hosts.yml"),
                          str(ROOT / "site.yml"), "-e", json.dumps(extra)]
            if args.vars_file:
                var_file = args.vars_file.resolve(strict=True)
                remedy_cmd += ["-e", "@" + str(var_file)]
            if args.ask_become_pass:
                remedy_cmd += ["-K"]
            # Paths, section selection and profile ownership are internal, not overridden by user vars.
            remedy_cmd += ["-e", json.dumps(extra)]
            if args.action != "audit" and not shutil.which("ansible-playbook"):
                raise ValueError("Không tìm thấy ansible-playbook; xem README.md")
            os.environ["CIS_RECAP_PATH"] = str(folder / "ansible-recap.json")
            print(f"RUN {run_id} | HOST {host} | SECTION {args.section}\nEVIDENCE {folder}", flush=True)
            rc, codes = workflow(args, folder, audit_cmd, remedy_cmd)
            result = summarize(folder, args.action, args.section, codes)
            result["exit_code"] = rc
            (folder / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            print(f"Kết thúc: exit={rc}; {folder / 'summary.json'}")
            return rc
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
