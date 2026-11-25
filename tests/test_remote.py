"""Controller regressions. Synthetic rows here are not VM/EC2 evidence."""
import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cis_remote", ROOT / "scripts/remote.py")
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


def args(**kw):
    return argparse.Namespace(**(dict(action="run", stage="before", section="all", idempotence=False,
                                      vars_file=None, ask_become_pass=False, connect_timeout=5) | kw))


def inventory():
    return {"nginx_servers": {"children": ["team"]}, "team": {"hosts": ["nginx01", "nginx02"]},
            "_meta": {"hostvars": {f"nginx0{i}": {"ansible_host": f"192.0.2.{i}", "ansible_user": "ubuntu"}
                                    for i in (1, 2)}}}


def make_report(path, section="all", stage="before", status="PASS", hostname="ec2-test"):
    path.mkdir(exist_ok=True, parents=True)
    rows = [{"cis_id": cid, "status": status, "detail": "synthetic test data"}
            for cid in remote.expected_ids(section)]
    counts = {s: len(rows) if s == status else 0 for s in remote.STATUSES}
    remote.write_json(path / "audit.json", {"source": "live", "section": section, "stage": stage,
                                          "hostname": hostname, "counts": counts, "results": rows})
    rc = 2 if status == "ERROR" else (0 if status == "PASS" else 1)
    remote.write_json(path / "collector-result.json", {"exit_code": rc})
    return rc


class FakeTransport:
    def __init__(self, before="FAIL", after="PASS", failed=None, changed=0):
        self.before, self.after, self.failed, self.changed = before, after, failed, changed
        self.calls = []

    def call(self, host, folder, operation):
        self.calls.append((host, operation))
        (folder / f"{operation}.log").write_text("synthetic test log\n")
        if operation == self.failed:
            raise RuntimeError("unreachable or failed task")
        if operation in ("before", "after", "after-idempotence"):
            return make_report(folder / operation, stage="before" if operation == "before" else "after",
                               status=self.before if operation == "before" else self.after)
        if operation == "idempotence":
            remote.write_json(folder / "idempotence-recap.json", {host: {"changed": self.changed}})
        return 0


def test_group_membership_limit_and_empty_selection():
    assert list(remote.selected_hosts(inventory(), "nginx02")) == ["nginx02"]
    with pytest.raises(ValueError):
        remote.selected_hosts(inventory(), "controller")
    with pytest.raises(ValueError):
        remote.selected_hosts({})


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "0.0.0.0", "localhost", "[IP_NGINX01]", "REPLACE_IP", "host.invalid"])
def test_reject_controller_or_placeholder(address):
    inv = inventory()
    inv["_meta"]["hostvars"]["nginx01"]["ansible_host"] = address
    with pytest.raises(ValueError):
        remote.selected_hosts(inv)


def test_reject_local_connection_duplicate_endpoints_and_path_alias():
    inv = inventory()
    inv["_meta"]["hostvars"]["nginx01"]["ansible_connection"] = "local"
    with pytest.raises(ValueError):
        remote.selected_hosts(inv)
    inv = inventory()
    inv["_meta"]["hostvars"]["nginx02"] = inv["_meta"]["hostvars"]["nginx01"]
    with pytest.raises(ValueError):
        remote.selected_hosts(inv)
    with pytest.raises(ValueError):
        remote.safe_id("../escape")


def test_fail_baseline_remediates_and_compares_30_controls(tmp_path):
    transport = FakeTransport()
    data = remote.run_host(args(), "nginx01", tmp_path, transport)
    assert data["exit_code"] == 0 and len(data["comparison"]) == 30
    assert data["before"]["FAIL"] == 30 and data["after"]["PASS"] == 30
    assert [s for _, s in transport.calls] == ["before", "remediate", "after"]


def test_review_is_not_a_collection_error(tmp_path):
    transport = FakeTransport(before="REVIEW", after="REVIEW")
    assert remote.run_host(args(), "nginx01", tmp_path, transport)["exit_code"] == 1
    assert ("nginx01", "remediate") in transport.calls


def test_baseline_error_blocks_only_that_host(tmp_path):
    transport = FakeTransport(before="ERROR")
    data = remote.run_host(args(), "nginx01", tmp_path, transport)
    assert data["exit_code"] == 2 and len(transport.calls) == 1


def test_unreachable_has_no_fabricated_cis_rows(tmp_path):
    transport = FakeTransport(failed="before")
    data = remote.run_host(args(), "nginx01", tmp_path, transport)
    assert data["exit_code"] == 2 and "before" not in data and "comparison" not in data
    assert not (tmp_path / "before/audit.json").exists()


def test_partial_remediation_still_gets_diagnostic_audit(tmp_path):
    transport = FakeTransport(failed="remediate")
    data = remote.run_host(args(), "nginx01", tmp_path, transport)
    assert data["exit_code"] == 2 and data["after"]["PASS"] == 30
    assert "execution_error" in data


@pytest.mark.parametrize("changed,expected", [(0, 0), (1, 1)])
def test_idempotence_audits_even_if_second_remediation_changes(tmp_path, changed, expected):
    data = remote.run_host(args(idempotence=True), "nginx01", tmp_path, FakeTransport(changed=changed))
    assert data["exit_code"] == expected and data["idempotent"] == (changed == 0)
    assert data["after-idempotence"]["PASS"] == 30


def test_split_remediate_requires_valid_before(tmp_path):
    transport = FakeTransport()
    assert remote.run_host(args(action="remediate"), "nginx01", tmp_path, transport)["exit_code"] == 2
    assert not transport.calls


@pytest.mark.parametrize("change", ["scope", "stage", "count", "duplicate", "source", "returncode"])
def test_reject_invalid_fetched_evidence(tmp_path, change):
    make_report(tmp_path)
    path = tmp_path / "audit.json"
    data = json.loads(path.read_text())
    if change == "scope": data["section"] = "5"
    if change == "stage": data["stage"] = "after"
    if change == "count": data["counts"]["PASS"] = 29
    if change == "duplicate": data["results"][-1] = data["results"][0]
    if change == "source": data["source"] = "fixture"
    if change == "returncode": remote.write_json(tmp_path / "collector-result.json", {"exit_code": 2})
    remote.write_json(path, data)
    with pytest.raises(ValueError):
        remote.load_audit(tmp_path, "all", "before")


def test_four_hosts_keep_missing_host_visible_in_summary(tmp_path):
    for i in range(1, 5):
        folder = tmp_path / f"nginx0{i}"
        folder.mkdir()
        remote.run_host(args(), folder.name, folder, FakeTransport(failed="before" if i == 2 else None))
    assert remote.aggregate(tmp_path, [f"nginx0{i}" for i in range(1, 5)], "all", "run") == 2
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["expected_hosts"] == 4
    assert summary["after"]["counts"]["PASS"] == 90
    assert summary["after"]["missing_hosts"] == ["nginx02"]
    assert len((tmp_path / "comparison.csv").read_text().splitlines()) == 91


def test_transport_passes_exact_host_and_returns_collector_fail_not_ansible_success(tmp_path, monkeypatch):
    config = args(section="5")
    captured = []
    class Process:
        stdout = ["synthetic Ansible console\n"]
        def __init__(self, cmd, **kw):
            captured.append((cmd, kw))
            remote.write_json(tmp_path / "before-recap.json", {"nginx01": {"failures": 0, "unreachable": 0}})
            make_report(tmp_path / "before", section="5", status="FAIL")
            remote.write_json(tmp_path / "before/collector-result.json",
                              {"exit_code": 1, "inventory_alias": "nginx01", "run_id": "test01"})
        def wait(self): return 0
    monkeypatch.setattr(subprocess, "Popen", Process)
    t = remote.Transport(ROOT, config, tmp_path / "inventory.yml", "test01", {})
    assert t.call("nginx01", tmp_path, "before") == 1
    cmd, kwargs = captured[0]
    assert cmd[cmd.index("--limit") + 1] == "nginx01"
    assert "remote-audit.yml" in " ".join(cmd)
    assert kwargs["env"]["CIS_RECAP_PATH"].endswith("before-recap.json")
    with pytest.raises(FileExistsError):
        t.call("nginx01", tmp_path, "before")


def test_main_split_commands_manifest_guard_and_immutable_stage(tmp_path, monkeypatch):
    inv = tmp_path / "inventory.yml"
    inv.write_text("# test inventory\n")
    a = args(action="audit", inventory=inv, limit=None, run_id="split01")
    monkeypatch.setattr(remote.shutil, "which", lambda x: "/test/" + x)
    monkeypatch.setattr(remote, "code_hash", lambda root: "code-hash")
    monkeypatch.setattr(remote.subprocess, "run", lambda *a, **kw: argparse.Namespace(returncode=0, stdout=json.dumps(inventory())))
    monkeypatch.setattr(remote.subprocess, "check_output", lambda *a, **kw: "commit")
    transport = FakeTransport()
    monkeypatch.setattr(remote, "Transport", lambda *a: transport)
    assert remote.main(a, tmp_path) == 1
    assert remote.main(a, tmp_path) == 2  # immutable before
    a.action = "remediate"
    assert remote.main(a, tmp_path) == 0
    a.action, a.stage = "audit", "after"
    assert remote.main(a, tmp_path) == 0
    summary = json.loads((tmp_path / "evidence/split01/summary.json").read_text())
    assert summary["after"]["counts"]["PASS"] == 60
    a.section = "5"
    assert remote.main(a, tmp_path) == 2  # same run ID cannot switch scope
    manifest = (tmp_path / "evidence/split01/manifest.json").read_text()
    assert "ansible_user" not in manifest  # no dumped inventory or credentials


def test_each_section_has_the_expected_controls():
    assert [len(remote.expected_ids(str(i))) for i in range(1, 6)] == [3, 14, 3, 5, 5]
    assert len(set(remote.expected_ids("all"))) == 30
