import argparse
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner", ROOT / "scripts/runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def args(**changes):
    a = dict(action="run", section="all", stage="before", idempotence=False)
    return argparse.Namespace(**(a | changes))


def fake_run(codes, calls):
    def run(argv, logfile):
        calls.append((list(argv), logfile.name))
        return codes.pop(0)
    return run


def test_noncompliant_baseline_still_gets_remediated(tmp_path):
    calls = []
    rc, stages = runner.workflow(args(), tmp_path, ["audit"], ["remedy"], fake_run([1, 0, 0], calls))
    assert rc == 0
    assert [x[1] for x in calls] == ["before.log", "remediate.log", "after.log"]


def test_audit_collection_error_does_not_change_system(tmp_path):
    calls = []
    rc, _ = runner.workflow(args(), tmp_path, ["audit"], ["remedy"], fake_run([2], calls))
    assert rc == 2 and len(calls) == 1


def test_remediation_failure_keeps_diagnostic_post_audit(tmp_path):
    calls = []
    rc, stages = runner.workflow(args(), tmp_path, ["audit"], ["remedy"], fake_run([1, 2, 0], calls))
    assert rc == 2 and stages["after"] == 0


def test_successful_ansible_is_not_a_compliance_pass(tmp_path):
    rc, _ = runner.workflow(args(), tmp_path, ["audit"], ["remedy"], fake_run([1, 0, 1], []))
    assert rc == 1


def test_evidence_is_never_overwritten(tmp_path):
    (tmp_path / "before").mkdir()
    with pytest.raises(FileExistsError):
        runner.workflow(args(), tmp_path, ["audit"], ["remedy"], fake_run([], []))


def test_changed_second_run_is_reported_as_non_idempotent(tmp_path):
    (tmp_path / "ansible-recap.json").write_text(json.dumps({"local": {"changed": 1}}))
    rc, stages = runner.workflow(args(idempotence=True), tmp_path, ["audit"], ["remedy"],
                                 fake_run([1, 0, 0, 0], []))
    assert rc == 1 and stages["idempotence_result"] == 1


def test_idempotence_has_a_fresh_post_audit(tmp_path):
    (tmp_path / "ansible-recap.json").write_text(json.dumps({"local": {"changed": 0}}))
    calls = []
    rc, _ = runner.workflow(args(idempotence=True), tmp_path, ["audit"], ["remedy"],
                            fake_run([1, 0, 0, 0, 1], calls))
    assert rc == 1 and calls[-1][1] == "after-idempotence.log"


@pytest.mark.parametrize("bad", ["../escape", "/tmp/report", ".hidden", "a/b", "a b", "a;cmd"])
def test_run_id_cannot_escape_evidence_folder(bad):
    with pytest.raises(ValueError):
        runner.safe_id(bad)


def test_remote_never_calls_local_workflow(monkeypatch):
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "remote", SimpleNamespace(main=lambda args, root: 17))
    monkeypatch.setattr(runner, "workflow", lambda *a: pytest.fail("must not execute"))
    assert runner.main(["run", "--mode", "remote"]) == 17


def test_mixed_scopes_cannot_be_compared(tmp_path):
    (tmp_path / "before").mkdir()
    (tmp_path / "before/audit.json").write_text(json.dumps({"section": "5", "counts": {}}))
    with pytest.raises(ValueError):
        runner.summarize(tmp_path, "audit", "all", {})
