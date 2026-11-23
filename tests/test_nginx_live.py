"""Optional actual NGINX test without root, systemd, package or /etc changes."""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
BINARY = os.environ.get("NGINX_TEST_BINARY")
pytestmark = pytest.mark.skipif(not BINARY, reason="set NGINX_TEST_BINARY for real HTTP/TLS integration")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_compiled_config_serves_headers_errors_redirect_and_tls(tmp_path):
    defaults = yaml.safe_load((ROOT / "roles/nginx_cis/defaults/main.yml").read_text())
    defaults.update(nginx_cis_enabled=[1, 2, 3, 4, 5], nginx_cis_web_root=str(tmp_path),
                    nginx_cis_tls_certificate=str(tmp_path / "lab.crt"),
                    nginx_cis_tls_private_key=str(tmp_path / "lab.key"))
    for name in ["index.html", "404.html", "50x.html"]:
        (tmp_path / name).write_text("<h1>Lab page</h1>")
    (tmp_path / ".git").mkdir(); (tmp_path / ".git/HEAD").write_text("DO NOT SERVE")
    subprocess.run(["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "1",
                    "-subj", "/CN=cis.local", "-keyout", str(tmp_path / "lab.key"),
                    "-out", str(tmp_path / "lab.crt")], check=True, capture_output=True)
    env = Environment(loader=FileSystemLoader(ROOT / "roles/nginx_cis/templates"))
    config = env.get_template("nginx.conf.j2").render(**defaults)
    # Redirect paths only inside this test's private prefix, use unprivileged ports.
    hp, sp = free_port(), free_port()
    mime = Path(os.environ["NGINX_TEST_MIME"])
    config = config.replace("/etc/nginx/mime.types", str(mime))
    config = config.replace("/var/log/nginx/", str(tmp_path) + "/")
    config = config.replace("/run/nginx.pid", str(tmp_path / "nginx.pid"))
    config = config.replace("worker_processes auto", "worker_processes 1")
    config = config.replace("listen 80", f"listen {hp}").replace("listen 443", f"listen {sp}")
    target = tmp_path / "nginx.conf"; target.write_text(config)
    command = [BINARY, "-p", str(tmp_path), "-c", str(target)]
    subprocess.run(command + ["-t"], check=True, capture_output=True)
    proc = subprocess.Popen(command + ["-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        def curl(scheme, port, path="/", host="cis.local"):
            return subprocess.run(["curl", "--noproxy", "*", "-ksS", "-i", "--max-time", "3",
                                   "--resolve", f"{host}:{port}:127.0.0.1", f"{scheme}://{host}:{port}{path}"],
                                  capture_output=True, text=True)
        for _ in range(60):
            r = curl("https", sp)
            if r.returncode == 0: break
            if proc.poll() is not None: pytest.fail(proc.stderr.read().decode())
            time.sleep(0.05)
        assert "200 OK" in r.stdout and "X-Content-Type-Options: nosniff" in r.stdout
        missing = curl("https", sp, "/missing-cis")
        assert "404 Not Found" in missing.stdout and "Referrer-Policy:" in missing.stdout
        assert "403 Forbidden" in curl("https", sp, "/.git/HEAD").stdout
        assert "301 Moved Permanently" in curl("http", hp).stdout
        rejected = curl("http", hp, host="unknown.invalid")
        assert rejected.returncode == 52  # actual nginx 444 empty reply, not a network refusal
        for protocol, expected in [("-tls1_3", 0), ("-tls1_2", 1)]:
            tls = subprocess.run(["openssl", "s_client", "-brief", "-connect", f"127.0.0.1:{sp}",
                                  "-servername", "cis.local", protocol], input="", capture_output=True,
                                 text=True, timeout=6)
            assert (tls.returncode != 0) == bool(expected), tls.stdout + tls.stderr
        # Exercise the audit engine with the actual config and actual HTTP/TLS server.
        output = subprocess.run(command + ["-T"], capture_output=True, text=True, check=True)
        values = {"NGINX_T_FILE": output.stdout, "NGINX_V_FILE": "nginx version: nginx/1.28.0",
                  "SS_FILE": '\n'.join(f'tcp LISTEN 0 511 127.0.0.1:{port} 0.0.0.0:* users:(("nginx",pid=1,fd=1))' for port in [hp, sp]),
                  "APT_FILE": "Installed: 1.28.0\nCandidate: 1.28.0"}
        import sys
        testenv = dict(os.environ, STAGE="after", AUDIT_SECTION="4", AUDIT_SOURCE="fixture",
                       HTTP_PORT=str(hp), HTTPS_PORT=str(sp), NGINX_CONF_DIR=str(tmp_path),
                       REPORT_JSON=str(tmp_path / "audit.json"), REPORT_TXT=str(tmp_path / "audit.txt"),
                       SUMMARY_CSV=str(tmp_path / "audit.csv"))
        for key, text in values.items():
            f = tmp_path / key; f.write_text(text); testenv[key] = str(f)
        subprocess.run([sys.executable, str(ROOT / "audit/engine.py")], env=testenv,
                       capture_output=True, text=True, timeout=30)
        rows = {r["cis_id"]: r for r in json.loads((tmp_path / "audit.json").read_text())["results"]}
        for cid in ["4.1.1", "4.1.4", "4.1.5", "4.1.6"]:
            assert rows[cid]["status"] == "PASS", rows[cid]
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
