"""Controller orchestration. All audits and system changes execute through SSH.

Inventory aliases identify evidence folders; audit.json records the actual hostname.
No credentials or resolved inventory contents are written to the manifest.
"""
import csv
import datetime as dt
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

CONTROLS = {
    "1": ["1.1.1", "1.2.1", "1.2.2"],
    "2": ["2.1.1", "2.2.1", "2.2.2", "2.2.3", "2.3.1", "2.3.2", "2.3.3",
          "2.4.1", "2.4.2", "2.4.3", "2.4.4", "2.5.1", "2.5.2", "2.5.3"],
    "3": ["3.1", "3.2", "3.3"],
    "4": ["4.1.1", "4.1.3", "4.1.4", "4.1.5", "4.1.6"],
    "5": ["5.2.1", "5.2.2", "5.2.3", "5.3.1", "5.3.3"],
}
STATUSES = ("PASS", "FAIL", "ERROR", "REVIEW")


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    path.chmod(0o640)


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise ValueError("Invalid run ID or inventory alias")
    return value


def selected_hosts(inventory, limit=None):
    """Use Ansible's resolved inheritance, but select only nginx_servers members."""
    names, visiting = set(), set()

    def visit(group):
        if group in visiting:
            raise ValueError("Inventory group cycle")
        visiting.add(group)
        node = inventory.get(group, {})
        names.update(node.get("hosts", []))
        for child in node.get("children", []):
            visit(child)
        visiting.remove(group)

    visit("nginx_servers")
    if limit:
        chosen = {safe_id(x.strip()) for x in limit.split(",")}
        if not chosen <= names:
            raise ValueError("--limit must name exact hosts in nginx_servers")
        names = chosen
    if not names:
        raise ValueError("Inventory nginx_servers is empty; fill the EC2 information first")
    result = {}
    for name in sorted(names):
        safe_id(name)
        values = inventory.get("_meta", {}).get("hostvars", {}).get(name, {})
        address = str(values.get("ansible_host", "")).strip()
        if values.get("ansible_connection", "ssh") != "ssh":
            raise ValueError(f"{name}: Remote requires ansible_connection: ssh")
        if (not address or not re.fullmatch(r"[A-Za-z0-9_.:-]+", address)
                or address.lower() in {"localhost", "localhost.localdomain", socket.gethostname().lower()}
                or "REPLACE" in address.upper() or "IP_NGINX" in address.upper()):
            raise ValueError(f"{name}: fill an explicit EC2 IP/DNS, not a placeholder or controller hostname")
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            if address.endswith(".invalid"):
                raise ValueError(f"{name}: placeholder DNS is not a target")
        else:
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
                raise ValueError(f"{name}: loopback/unspecified/multicast is not an EC2 target")
        if not values.get("ansible_user"):
            raise ValueError(f"{name}: declare ansible_user explicitly")
        result[name] = values
    # Duplicate endpoints would overwrite the target's per-run evidence.
    endpoints = [(str(v["ansible_host"]), str(v.get("ansible_port", 22))) for v in result.values()]
    if len(set(endpoints)) != len(endpoints):
        raise ValueError("Two aliases select the same SSH endpoint; use one alias per target")
    return result


def expected_ids(section):
    return [cid for key, ids in CONTROLS.items() if section in ("all", key) for cid in ids]


def load_audit(folder, section, stage):
    data = json.loads((folder / "audit.json").read_text())
    rows = data.get("results", [])
    ids = [r["cis_id"] for r in rows]
    if (data.get("source") != "live" or data.get("section") != section
            or data.get("stage") != stage or not data.get("hostname")
            or len(ids) != len(set(ids)) or set(ids) != set(expected_ids(section))
            or any(r.get("status") not in STATUSES for r in rows)):
        raise ValueError("Incomplete or mismatched live audit evidence")
    counts = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    if data.get("counts") != counts:
        raise ValueError("Audit counts do not match the individual rows")
    rc = 2 if counts["ERROR"] else (1 if counts["FAIL"] or counts["REVIEW"] else 0)
    status = json.loads((folder / "collector-result.json").read_text())
    if status.get("exit_code") != rc:
        raise ValueError("Collector exit code does not match audit statuses")
    return data, rc


def code_hash(root):
    h = hashlib.sha256()
    paths = [root / "cisctl", root / "ansible.cfg"]
    for pattern in ("scripts/*.py", "audit/*.py", "roles/nginx_cis/**/*", "playbooks/**/*.yml",
                    "callback_plugins/*.py"):
        paths.extend(p for p in root.glob(pattern) if p.is_file() and "__pycache__" not in p.parts)
    for p in sorted(set(paths)):
        h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


class Transport:
    def __init__(self, root, args, inventory, run_id, env):
        self.root, self.args, self.inventory, self.run_id, self.env = root, args, inventory, run_id, env

    def call(self, host, folder, operation):
        """Ansible exit status describes transport/tasks; audit status comes from fetched JSON."""
        audit = operation in ("before", "after", "after-idempotence")
        stage = "before" if operation == "before" else "after"
        if audit:
            # Fail before SSH, and reserve the local destination to prevent overwrites.
            (folder / operation).mkdir(mode=0o750)
        internal = {
            "cis_run_id": self.run_id, "cis_operation": operation, "cis_stage": stage,
            "cis_section": self.args.section, "cis_source_root": str(self.root),
            "cis_local_stage": str(folder / operation),
            "nginx_cis_execution_mode": "remote", "ansible_connection": "ssh",
            "nginx_cis_sections": list(range(1, 6)) if self.args.section == "all" else [int(self.args.section)],
            "nginx_cis_backup_dir": "/var/backups/nginx-cis/" + self.run_id,
        }
        cmd = ["ansible-playbook", "-i", str(self.inventory),
               str(self.root / "playbooks" / ("remote-audit.yml" if audit else "remote-remediate.yml")),
               "--limit", host, "--timeout", str(self.args.connect_timeout)]
        if self.args.vars_file:
            cmd += ["-e", "@" + str(self.args.vars_file.resolve())]
        # Internal transport/paths/scope cannot be overridden by vars-file or inventory.
        cmd += ["-e", json.dumps(internal)]
        if self.args.ask_become_pass:
            cmd += ["-K"]
        env = dict(self.env, CIS_RECAP_PATH=str(folder / f"{operation}-recap.json"))
        logfile = folder / f"{operation}.log"
        with logfile.open("x", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, cwd=self.root, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace")
            try:
                for line in proc.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                rc = proc.wait()
            except BaseException:
                proc.terminate()
                proc.wait()
                raise
        if rc:
            raise RuntimeError(f"{operation}: Ansible exit={rc}; inspect {logfile.name} and recap")
        recap = json.loads((folder / f"{operation}-recap.json").read_text())
        if set(recap) != {host} or any(recap[host].get(k, 0) for k in ("failures", "unreachable")):
            raise ValueError(f"{operation}: missing or unsuccessful host recap")
        if audit:
            identity = json.loads((folder / operation / "collector-result.json").read_text())
            if identity.get("inventory_alias") != host or identity.get("run_id") != self.run_id:
                raise ValueError("Fetched evidence belongs to a different host or run")
            _, rc = load_audit(folder / operation, self.args.section, stage)
        return rc


def run_host(args, host, folder, transport):
    """Isolate failure per host, never fabricate audit rows for an unreachable node."""
    result = {"host": host, "section": args.section, "stages": {}, "exit_code": 2}
    steps = result["stages"]
    try:
        if args.action == "audit":
            rc = transport.call(host, folder, args.stage)
            steps[args.stage] = rc
        else:
            if args.action == "run":
                steps["before"] = transport.call(host, folder, "before")
            # The split remediate command also requires a valid matching before audit.
            _, before_rc = load_audit(folder / "before", args.section, "before")
            if before_rc == 2:
                raise ValueError("Before audit contains ERROR; remediation is blocked")
            remedy_error = None
            try:
                steps["remediate"] = transport.call(host, folder, "remediate")
            except (OSError, ValueError, RuntimeError) as exc:
                steps["remediate"] = 2
                remedy_error = str(exc)
            if args.action == "remediate":
                if remedy_error:
                    raise RuntimeError(remedy_error)
                rc = 0
            else:
                # Also run after audit for diagnosis after a partial remediation failure.
                steps["after"] = transport.call(host, folder, "after")
                rc = steps["after"]
                if remedy_error:
                    raise RuntimeError(remedy_error)
                if args.idempotence and rc != 2:
                    steps["idempotence"] = transport.call(host, folder, "idempotence")
                    recap = json.loads((folder / "idempotence-recap.json").read_text())[host]
                    stable = not any(recap.get(k, 0) for k in ("changed", "failures", "unreachable"))
                    result["idempotent"] = stable
                    steps["after-idempotence"] = transport.call(host, folder, "after-idempotence")
                    post = steps["after-idempotence"]
                    rc = 2 if post == 2 else max(rc, post, 0 if stable else 1)
        result["exit_code"] = rc
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        result["execution_error"] = str(exc)
    # Read both stages also when split commands run in separate processes.
    audits = {}
    for label in ("before", "after", "after-idempotence"):
        if (folder / label / "audit.json").exists():
            try:
                data, _ = load_audit(folder / label, args.section, "before" if label == "before" else "after")
                audits[label] = data
                result[label] = data["counts"]
                result["target_hostname"] = data["hostname"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                result.update(exit_code=2, execution_error=str(exc))
    if "before" in audits and "after" in audits:
        if audits["before"]["hostname"] != audits["after"]["hostname"]:
            result.update(exit_code=2, execution_error="Target hostname changed between before and after")
        before = {r["cis_id"]: r["status"] for r in audits["before"]["results"]}
        result["comparison"] = [{"cis_id": r["cis_id"], "before": before[r["cis_id"]],
                                 "after": r["status"]} for r in audits["after"]["results"]]
    result["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_json(folder / "summary.json", result)
    for path in folder.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o750 if path.is_dir() else 0o640)
    return result


def aggregate(base, hosts, section, action):
    summaries = {h: json.loads((base / h / "summary.json").read_text()) for h in hosts}
    rc = max(s["exit_code"] for s in summaries.values())
    output = {"mode": "remote", "action": action, "section": section, "hosts": summaries,
              "expected_hosts": len(hosts), "expected_controls_per_host": len(expected_ids(section)),
              "exit_code": rc, "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    for stage in ("before", "after", "after-idempotence"):
        present = [s[stage] for s in summaries.values() if stage in s]
        output[stage] = {"collected_hosts": len(present), "missing_hosts": [h for h, s in summaries.items() if stage not in s],
                         "counts": {k: sum(c[k] for c in present) for k in STATUSES}}
    write_json(base / "summary.json", output)
    with (base / "comparison.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Host", "CIS_ID", "Before_Status", "After_Status"])
        for host, data in summaries.items():
            for row in data.get("comparison", []):
                writer.writerow([host, row["cis_id"], row["before"], row["after"]])
    with (base / "hosts.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Host", "Target_Hostname", "Exit_Code", "Execution_Error"])
        for host, data in summaries.items():
            writer.writerow([host, data.get("target_hostname", ""), data["exit_code"], data.get("execution_error", "")])
    return rc


def main(args, root):
    try:
        if args.connect_timeout < 1 or args.connect_timeout > 300:
            raise ValueError("--connect-timeout must be 1..300")
        if args.idempotence and args.action != "run":
            raise ValueError("--idempotence requires action run")
        for binary in ("ansible-playbook", "ansible-inventory", "ssh"):
            if not shutil.which(binary):
                raise ValueError(f"Missing {binary}; activate .venv and install requirements.txt")
        inventory = (args.inventory or root / "inventory/hosts-aws.yml").resolve(strict=True)
        if not inventory.is_file():
            raise ValueError("Use a static inventory file")
        env = dict(os.environ, ANSIBLE_CONFIG=str(root / "ansible.cfg"),
                   ANSIBLE_HOST_KEY_CHECKING="True", ANSIBLE_NOCOLOR="1",
                   ANSIBLE_CALLBACKS_ENABLED="cis_evidence",
                   ANSIBLE_CALLBACK_PLUGINS=str(root / "callback_plugins"))
        proc = subprocess.run(["ansible-inventory", "-i", str(inventory), "--list"], cwd=root,
                              env=env, capture_output=True, text=True, timeout=60)
        if proc.returncode:
            raise ValueError("ansible-inventory failed; validate the inventory with --graph")
        resolved = json.loads(proc.stdout)
        hosts = selected_hosts(resolved, args.limit)
        run_id = safe_id(args.run_id or (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                        + "-" + uuid.uuid4().hex[:8]))
        base = root / "evidence" / run_id
        (root / "evidence").mkdir(exist_ok=True)
        # One lock for all remote runs: disjoint run IDs can still target the same EC2.
        with (root / "evidence/.remote.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            identity = {"mode": "remote", "run_id": run_id, "section": args.section,
                        "hosts": list(hosts), "source_sha256": code_hash(root),
                        "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
                        "resolved_sha256": hashlib.sha256(json.dumps(hosts, sort_keys=True).encode()).hexdigest(),
                        "vars_sha256": hashlib.sha256(args.vars_file.resolve(strict=True).read_bytes()).hexdigest() if args.vars_file else None}
            manifest = base / "manifest.json"
            if manifest.exists():
                old = json.loads(manifest.read_text())
                if any(old.get(k) != v for k, v in identity.items()):
                    raise ValueError("Run ID must keep the same mode, hosts, inventory, code, scope and vars")
            else:
                if base.exists() and any(base.iterdir()):
                    raise ValueError("Run ID is already used; choose a new one")
                base.mkdir(exist_ok=True, mode=0o750)
                try:
                    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                                     text=True, stderr=subprocess.DEVNULL).strip()
                except (OSError, subprocess.CalledProcessError):
                    commit = "uncommitted"
                write_json(manifest, identity | {"commit": commit, "source": "live",
                           "created_at": dt.datetime.now(dt.timezone.utc).isoformat()})
            operations = (["before", "remediate", "after"] + (["idempotence", "after-idempotence"] if args.idempotence else [])
                          if args.action == "run" else [args.stage if args.action == "audit" else "remediate"])
            # Check all hosts before changing any: an accidental rerun cannot partially execute.
            for host in hosts:
                folder = base / host
                for operation in operations:
                    if (folder / operation).exists() or (folder / f"{operation}.log").exists():
                        raise FileExistsError(f"Evidence exists: {host}/{operation}; use a new run ID")
            transport = Transport(root, args, inventory, run_id, env)
            print(f"RUN {run_id} | REMOTE HOSTS {', '.join(hosts)}\nEVIDENCE {base}", flush=True)
            for host in hosts:
                folder = base / host
                folder.mkdir(exist_ok=True, mode=0o750)
                write_json(folder / "manifest.json", identity | {"inventory_alias": host,
                           "address": str(hosts[host]["ansible_host"]), "source": "live"})
                result = run_host(args, host, folder, transport)
                print(f"HOST {host}: exit={result['exit_code']} {result.get('execution_error', '')}", flush=True)
            rc = aggregate(base, hosts, args.section, args.action)
            print(f"Kết thúc Remote: exit={rc}; {base / 'summary.json'}")
            return rc
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
