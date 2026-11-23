"""Real local HTTP responses plus explicit fixture snapshots; never VM compliance evidence."""
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def web():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code = 200 if self.path == "/" else 404
            self.send_response(code)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(b"Lab page")

        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown(); server.server_close(); thread.join()


def audit(tmp_path, port, *, section="5", extra="", codes=None, no_version=False):
    config = f'''# configuration file /etc/nginx/nginx.conf:
events {{ worker_connections 64; }}
http {{
 client_header_timeout 10s; client_body_timeout 10s; send_timeout 10s;
 client_max_body_size 2M; large_client_header_buffers 4 8k;
 add_header X-Content-Type-Options "nosniff" always;
 add_header Referrer-Policy "strict-origin-when-cross-origin" always;
 {extra}
 server {{ listen {port}; server_name cis.local; }}
}}
'''
    env = dict(os.environ, STAGE="after", AUDIT_SECTION=section, AUDIT_SOURCE="fixture",
               HTTP_PORT=str(port), HTTPS_PORT="18443", NGINX_CONF_DIR=str(tmp_path / "config"),
               REPORT_JSON=str(tmp_path / "audit.json"), REPORT_TXT=str(tmp_path / "report.txt"),
               SUMMARY_CSV=str(tmp_path / "summary.csv"), SNAPSHOT_STATUS=json.dumps(codes or {}))
    values = {"NGINX_T_FILE": config, "NGINX_V_FILE": "No such file or directory: nginx" if no_version else "nginx version: nginx/1.28.0",
              "SS_FILE": f'tcp LISTEN 0 511 127.0.0.1:{port} 0.0.0.0:* users:(("nginx",pid=1,fd=1))',
              "APT_FILE": "Installed: 1.28.0\nCandidate: 1.28.0"}
    for k, value in values.items():
        p = tmp_path / k; p.write_text(value); env[k] = str(p)
    proc = subprocess.run([sys.executable, str(ROOT / "audit/engine.py")], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode in (0, 1, 2), proc.stderr
    data = json.loads((tmp_path / "audit.json").read_text())
    return proc.returncode, {r["cis_id"]: r for r in data["results"]}


def test_section5_checks_real_headers_on_200_and_404(tmp_path, web):
    rc, rows = audit(tmp_path, web)
    assert len(rows) == 5 and rc == 0
    assert rows["5.3.1"]["status"] == rows["5.3.3"]["status"] == "PASS"


def test_invalid_config_cannot_pass_by_default_values(tmp_path, web):
    rc, rows = audit(tmp_path, web, codes={"NGINX_T_FILE": 1})
    assert rc == 2 and all(r["status"] == "ERROR" for r in rows.values())


def test_missing_nginx_is_a_remediable_baseline_not_collection_error(tmp_path, web):
    rc, rows = audit(tmp_path, web, codes={"NGINX_T_FILE": 127, "NGINX_V_FILE": 127}, no_version=True)
    assert rc == 1 and all(r["status"] == "FAIL" for r in rows.values())


def test_warning_error_log_level_does_not_satisfy_info(tmp_path, web):
    _, rows = audit(tmp_path, web, section="3", extra="error_log /tmp/error.log warn;")
    assert rows["3.3"]["status"] == "FAIL"


def test_http_healthy_without_unknown_host_rejection_does_not_pass(tmp_path, web):
    _, rows = audit(tmp_path, web, section="2")
    assert rows["2.4.2"]["status"] == "FAIL"


def test_missing_socket_snapshot_is_error(tmp_path, web):
    _, rows = audit(tmp_path, web, section="2", codes={"SS_FILE": 127})
    assert rows["2.4.1"]["status"] == "ERROR"


def test_full_audit_has_30_distinct_controls(tmp_path, web):
    _, rows = audit(tmp_path, web, section="all")
    assert len(rows) == 30
    assert all(row["status"] in {"PASS", "FAIL", "ERROR", "REVIEW"} for row in rows.values())


@pytest.mark.parametrize("file_mode,expected", [(0o640, "PASS"), (0o644, "FAIL")])
def test_permissions_follow_cis_find_without_following_symlink_targets(tmp_path, web, file_mode, expected):
    config = tmp_path / "config"
    config.mkdir(mode=0o750)
    actual = config / "nginx.conf"
    actual.write_text("# fixture")
    actual.chmod(file_mode)
    external_modules = tmp_path / "external-modules"
    external_modules.mkdir(mode=0o755)
    (config / "modules").symlink_to(external_modules, target_is_directory=True)
    _, rows = audit(tmp_path, web, section="2")
    assert rows["2.3.2"]["status"] == expected
