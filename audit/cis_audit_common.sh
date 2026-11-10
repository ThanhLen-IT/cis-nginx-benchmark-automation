#!/usr/bin/env bash
# Shared 30-control CIS NGINX Benchmark v3.0.0 audit runner (TV3 - feature/audit-headers)
set -euo pipefail

# --- Configurable parameters (override via environment variables if needed) ---
TARGET_HOST="${TARGET_HOST:-}"
HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/etc/nginx}"
MIN_NGINX_VERSION="${MIN_NGINX_VERSION:-1.28.0}"
ALLOWED_PORTS="${ALLOWED_PORTS:-80 443}"
ALLOWED_DYNAMIC_MODULES="${ALLOWED_DYNAMIC_MODULES:-}"
MAX_KEEPALIVE_TIMEOUT="${MAX_KEEPALIVE_TIMEOUT:-10}"
MAX_SEND_TIMEOUT="${MAX_SEND_TIMEOUT:-10}"
MIN_REQ_TIMEOUT="${MIN_REQ_TIMEOUT:-1}"
MAX_REQ_TIMEOUT="${MAX_REQ_TIMEOUT:-20}"

export LC_ALL=C.UTF-8
export PYTHONIOENCODING=utf-8

run_cis_audit() {
  local stage="${1:-before}"
  local project_root="${2:?Missing project root}"
  local evidence_dir="${project_root}/evidence/${stage}"

  if [[ "${EUID}" -ne 0 ]]; then
    echo "[ERROR] Script kiem tra can quyen root de doc day du 'nginx -T', 'passwd -S' va kiem tra quyen file trong ${NGINX_CONF_DIR}." >&2
    echo "        Vui long chay lai bang lenh: sudo $0" >&2
    return 2
  fi

  mkdir -p "${evidence_dir}"

  local report_txt="${evidence_dir}/audit-report.txt"
  local summary_csv="${evidence_dir}/audit-summary.csv"
  local nginx_snapshot="${evidence_dir}/nginx-T-snapshot.txt"

  local nginx_t_file nginx_v_file ss_file apt_file
  nginx_t_file="$(mktemp)"
  nginx_v_file="$(mktemp)"
  ss_file="$(mktemp)"
  apt_file="$(mktemp)"
  trap 'rm -f "${nginx_t_file}" "${nginx_v_file}" "${ss_file}" "${apt_file}"' RETURN

  # Collect read-only system snapshots once
  if command -v nginx >/dev/null 2>&1; then
    nginx -V >"${nginx_v_file}" 2>&1 || true
    nginx -T >"${nginx_t_file}" 2>/dev/null || true
  fi
  cp "${nginx_t_file}" "${nginx_snapshot}"

  if command -v ss >/dev/null 2>&1; then
    LC_ALL=C ss -tulnp >"${ss_file}" 2>&1 || true
  fi
  if command -v apt-cache >/dev/null 2>&1; then
    LC_ALL=C apt-cache policy nginx >"${apt_file}" 2>&1 || true
  fi

  local exit_rc=0
  STAGE="${stage}" \
  REPORT_TXT="${report_txt}" \
  SUMMARY_CSV="${summary_csv}" \
  NGINX_T_FILE="${nginx_t_file}" \
  NGINX_V_FILE="${nginx_v_file}" \
  SS_FILE="${ss_file}" \
  APT_FILE="${apt_file}" \
  TARGET_HOST="${TARGET_HOST}" \
  HTTP_PORT="${HTTP_PORT}" \
  HTTPS_PORT="${HTTPS_PORT}" \
  NGINX_CONF_DIR="${NGINX_CONF_DIR}" \
  MIN_NGINX_VERSION="${MIN_NGINX_VERSION}" \
  ALLOWED_PORTS="${ALLOWED_PORTS}" \
  ALLOWED_DYNAMIC_MODULES="${ALLOWED_DYNAMIC_MODULES}" \
  MAX_KEEPALIVE_TIMEOUT="${MAX_KEEPALIVE_TIMEOUT}" \
  MAX_SEND_TIMEOUT="${MAX_SEND_TIMEOUT}" \
  MIN_REQ_TIMEOUT="${MIN_REQ_TIMEOUT}" \
  MAX_REQ_TIMEOUT="${MAX_REQ_TIMEOUT}" \
  python3 - <<'PYEOF' || exit_rc=$?
import csv
import datetime
import fnmatch
import ipaddress
import os
import re
import socket
import stat
import subprocess
import sys

STAGE = os.environ["STAGE"]
REPORT_TXT = os.environ["REPORT_TXT"]
SUMMARY_CSV = os.environ["SUMMARY_CSV"]
NGINX_T_FILE = os.environ["NGINX_T_FILE"]
NGINX_V_FILE = os.environ["NGINX_V_FILE"]
SS_FILE = os.environ["SS_FILE"]
APT_FILE = os.environ["APT_FILE"]

TARGET_HOST_ENV = os.environ.get("TARGET_HOST", "").strip()
HTTP_PORT = int(os.environ.get("HTTP_PORT", "80"))
HTTPS_PORT = int(os.environ.get("HTTPS_PORT", "443"))
NGINX_CONF_DIR = os.environ.get("NGINX_CONF_DIR", "/etc/nginx")
MIN_NGINX_VERSION = os.environ.get("MIN_NGINX_VERSION", "1.28.0")
ALLOWED_PORTS = {int(x) for x in os.environ.get("ALLOWED_PORTS", "80 443").split() if x.isdigit()}
ALLOWED_DYN_MODS = {x.strip() for x in os.environ.get("ALLOWED_DYNAMIC_MODULES", "").split() if x.strip()}
MAX_KEEPALIVE_TIMEOUT = float(os.environ.get("MAX_KEEPALIVE_TIMEOUT", "10"))
MAX_SEND_TIMEOUT = float(os.environ.get("MAX_SEND_TIMEOUT", "10"))
MIN_REQ_TIMEOUT = float(os.environ.get("MIN_REQ_TIMEOUT", "1"))
MAX_REQ_TIMEOUT = float(os.environ.get("MAX_REQ_TIMEOUT", "20"))

USE_COLOR = sys.stdout.isatty()
C_GREEN = "\033[32m" if USE_COLOR else ""
C_RED = "\033[31m" if USE_COLOR else ""
C_YELLOW = "\033[33m" if USE_COLOR else ""
C_CYAN = "\033[36m" if USE_COLOR else ""
C_BOLD = "\033[1m" if USE_COLOR else ""
C_RESET = "\033[0m" if USE_COLOR else ""


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def run_cmd(cmd, timeout=8):
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 1, str(exc)


def strip_nginx_comments(raw):
    out_lines = []
    for line in raw.splitlines():
        out = []
        in_sq = False
        in_dq = False
        esc = False
        for ch in line:
            if esc:
                out.append(ch)
                esc = False
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                continue
            if ch == "'" and not in_dq:
                in_sq = not in_sq
                out.append(ch)
            elif ch == '"' and not in_sq:
                in_dq = not in_dq
                out.append(ch)
            elif ch == "#" and not in_sq and not in_dq:
                break
            else:
                out.append(ch)
        s = "".join(out).strip()
        if s:
            out_lines.append(s)
    return "\n".join(out_lines)


def parse_nginx_ast(clean_text):
    """Parse comment-stripped NGINX config into nested directives/blocks."""
    root = {"header": "main", "directives": [], "blocks": []}
    stack = [root]
    buf = []
    in_sq = False
    in_dq = False
    esc = False
    for ch in clean_text:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if ch == "\\":
            buf.append(ch)
            esc = True
            continue
        if ch == "'" and not in_dq:
            in_sq = not in_sq
            buf.append(ch)
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
            buf.append(ch)
        elif not in_sq and not in_dq and ch == ";":
            stmt = " ".join("".join(buf).split())
            buf = []
            if stmt:
                stack[-1]["directives"].append(stmt)
        elif not in_sq and not in_dq and ch == "{":
            hdr = " ".join("".join(buf).split())
            buf = []
            blk = {"header": hdr, "directives": [], "blocks": []}
            stack[-1]["blocks"].append(blk)
            stack.append(blk)
        elif not in_sq and not in_dq and ch == "}":
            stmt = " ".join("".join(buf).split())
            buf = []
            if stmt:
                stack[-1]["directives"].append(stmt)
            if len(stack) > 1:
                stack.pop()
        else:
            buf.append(ch)
    return root


def iter_all_directives(node):
    for d in node["directives"]:
        yield node["header"], d
    for blk in node["blocks"]:
        yield from iter_all_directives(blk)


def iter_blocks(node, prefix):
    for blk in node["blocks"]:
        if blk["header"] == prefix or blk["header"].startswith(prefix + " "):
            yield blk
        yield from iter_blocks(blk, prefix)


def split_tokens(stmt):
    tokens = []
    cur = []
    in_sq = False
    in_dq = False
    esc = False
    for ch in stmt:
        if esc:
            cur.append(ch)
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == "'" and not in_dq:
            in_sq = not in_sq
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
        elif ch.isspace() and not in_sq and not in_dq:
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


def parse_time_seconds(val):
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h|d)?", val.strip(), re.I)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "s").lower()
    mult = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}[unit]
    return num * mult


def parse_size_bytes(val):
    m = re.fullmatch(r"([0-9]+)([kmg]?)", val.strip(), re.I)
    if not m:
        return None
    num = int(m.group(1))
    unit = m.group(2).lower()
    mult = {"": 1, "k": 1024, "m": 1024 * 1024, "g": 1024 * 1024 * 1024}[unit]
    return num * mult


def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_ip(val):
    try:
        ipaddress.ip_address(val)
        return True
    except ValueError:
        return False


def parse_listen_port(tokens):
    # listen address[:port] [params...]
    if len(tokens) < 2:
        return None
    addr = tokens[1]
    if addr.startswith("unix:"):
        return None
    if addr.startswith("["):
        m = re.search(r"\]:(\d+)$", addr)
        return int(m.group(1)) if m else 80
    if ":" in addr:
        p = addr.rsplit(":", 1)[1]
        return int(p) if p.isdigit() else None
    if addr.isdigit():
        return int(addr)
    return 80


def parse_nginx_with_includes(raw_text):
    """Parse nginx -T output and attach each '# configuration file ...:' chunk under its include parent block."""
    chunks = []
    cur_path = "__root__"
    cur_lines = []
    for ln in raw_text.splitlines():
        m = re.match(r"^#\s*configuration file\s+(.+):$", ln.strip())
        if m:
            if cur_lines or cur_path != "__root__":
                chunks.append((cur_path, "\n".join(cur_lines)))
            cur_path = m.group(1).strip()
            cur_lines = []
        else:
            cur_lines.append(ln)
    if cur_lines or cur_path != "__root__":
        chunks.append((cur_path, "\n".join(cur_lines)))

    root = {"header": "main", "directives": [], "blocks": []}
    include_rules = []

    def register_includes(node):
        for d in node["directives"]:
            toks = split_tokens(d)
            if toks and toks[0] == "include" and len(toks) >= 2:
                pat = toks[1]
                pat_abs = pat if os.path.isabs(pat) else os.path.join(NGINX_CONF_DIR, pat)
                include_rules.append((pat_abs, node))
        for blk in node["blocks"]:
            register_includes(blk)

    for fpath, ctext in chunks:
        clean = strip_nginx_comments(ctext)
        parsed = parse_nginx_ast(clean)
        parent = root
        if fpath != "__root__":
            for pat, target_node in reversed(include_rules):
                if fnmatch.fnmatch(fpath, pat) or (os.path.isdir(pat) and fpath.startswith(pat.rstrip("/") + "/")):
                    parent = target_node
                    break
        parent["directives"].extend(parsed["directives"])
        parent["blocks"].extend(parsed["blocks"])
        register_includes(parsed)

    return root


NGINX_T_RAW = read_text(NGINX_T_FILE)
NGINX_V_RAW = read_text(NGINX_V_FILE)
SS_RAW = read_text(SS_FILE)
APT_RAW = read_text(APT_FILE)
NGINX_ACTIVE = strip_nginx_comments(NGINX_T_RAW)
AST = parse_nginx_with_includes(NGINX_T_RAW)
ALL_DIRS = list(iter_all_directives(AST))
SERVER_BLOCKS = list(iter_blocks(AST, "server"))
HTTP_BLOCKS = list(iter_blocks(AST, "http"))

# Detect listening ports on OS from ss
listening_ports = set()
for line in SS_RAW.splitlines():
    if "nginx" in line:
        parts = line.split()
        if len(parts) >= 5:
            m = re.search(r":(\d+)$", parts[4])
            if m:
                listening_ports.add(int(m.group(1)))

# Detect effective target host and protocol for live HTTP/HTTPS functional probes
def detect_probe_target():
    if TARGET_HOST_ENV:
        host = TARGET_HOST_ENV
    else:
        host = "127.0.0.1"
        for sb in SERVER_BLOCKS:
            dirs = sb["directives"]
            is_reject = any(re.match(r"return\s+444\b", d) or re.match(r"ssl_reject_handshake\s+on\b", d) for d in dirs)
            if is_reject:
                continue
            for d in dirs:
                toks = split_tokens(d)
                if toks and toks[0] == "server_name":
                    for cand in toks[1:]:
                        if cand not in ("_", "localhost") and not cand.startswith("*") and not cand.startswith("~"):
                            host = cand
                            break
                        if cand == "localhost" and host == "127.0.0.1":
                            host = "localhost"
            if host not in ("127.0.0.1", "localhost"):
                break
    has_https_listen = HTTPS_PORT in listening_ports or any(
        d.startswith("listen ") and ("ssl" in d or "quic" in d or f":{HTTPS_PORT}" in d or f" {HTTPS_PORT} " in d)
        for _, d in ALL_DIRS
    )
    use_https = HTTPS_PORT in listening_ports and has_https_listen
    return host, use_https


EFFECTIVE_HOST, USE_HTTPS = detect_probe_target()


def curl_probe(path="/", host_header=None, force_http=False):
    scheme = "http" if force_http or not USE_HTTPS else "https"
    port = HTTP_PORT if scheme == "http" else HTTPS_PORT
    target_host = host_header or EFFECTIVE_HOST
    if listening_ports and port not in listening_ports:
        return "000", {}, ""
    cmd = ["curl", "-sS", "-k", "-i", "--max-time", "4", "--connect-timeout", "2"]
    if target_host and not is_ip(target_host):
        cmd.extend(["--resolve", f"{target_host}:{port}:127.0.0.1"])
        url = f"{scheme}://{target_host}:{port}{path}"
    else:
        url = f"{scheme}://127.0.0.1:{port}{path}"
        if host_header:
            cmd.extend(["-H", f"Host: {host_header}"])
    cmd.append(url)
    rc, out = run_cmd(cmd, timeout=7)
    if rc != 0 and "\r\n\r\n" not in out and "\n\n" not in out:
        return "000", {}, out
    sep = "\r\n\r\n" if "\r\n\r\n" in out else ("\n\n" if "\n\n" in out else None)
    hdr_raw, body = out.split(sep, 1) if sep else (out, "")
    lines = hdr_raw.splitlines()
    code = "000"
    if lines:
        m = re.search(r"\s(\d{3})\b", lines[0])
        if m:
            code = m.group(1)
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers.setdefault(k.strip().lower(), []).append(v.strip())
    return code, headers, body


LIVE_ROOT = curl_probe("/")
LIVE_404 = curl_probe("/cis-audit-nonexistent-page-check")
LIVE_GIT = curl_probe("/.git/HEAD")

results = []


def add_result(cid, group, title, passed, detail):
    status = "PASS" if passed else "FAIL"
    results.append((cid, group, title, status, detail))


def check_1_installation():
    grp = "1. Installation"
    # 1.1.1
    m = re.search(r"nginx/(\d+\.\d+\.\d+)", NGINX_V_RAW)
    if not m:
        add_result("1.1.1", grp, "NGINX installed (>= " + MIN_NGINX_VERSION + ")", False, "Khong tim thay lenh nginx hoac phien ban")
    else:
        ver = m.group(1)
        ok = ver_tuple(ver) >= ver_tuple(MIN_NGINX_VERSION)
        add_result("1.1.1", grp, "NGINX installed (>= " + MIN_NGINX_VERSION + ")", ok, f"Phien ban hien tai: nginx/{ver} (yeu cau >= {MIN_NGINX_VERSION})")

    # 1.2.1
    urls = re.findall(r"https?://[^\s]+", APT_RAW)
    trusted = [u for u in urls if re.search(r"(ubuntu\.com|nginx\.org)", u, re.I)]
    untrusted = [u for u in urls if not re.search(r"(ubuntu\.com|nginx\.org)", u, re.I)]
    if not APT_RAW.strip():
        add_result("1.2.1", grp, "Trusted package manager repositories", False, "Khong doc duoc apt-cache policy nginx")
    else:
        ok = bool(trusted) and not untrusted
        msg = f"Nguon tin cay: {len(trusted)} repo" + (f"; nguon la: {untrusted}" if untrusted else "")
        add_result("1.2.1", grp, "Trusted package manager repositories", ok, msg)

    # 1.2.2
    mi = re.search(r"^\s*Installed:\s*(\S+)", APT_RAW, re.M)
    mc = re.search(r"^\s*Candidate:\s*(\S+)", APT_RAW, re.M)
    inst = mi.group(1) if mi else "(none)"
    cand = mc.group(1) if mc else "(none)"
    ok = inst not in ("(none)", "") and cand not in ("(none)", "") and inst == cand
    add_result("1.2.2", grp, "Latest NGINX package installed", ok, f"Installed={inst}, Candidate={cand}")


def check_2_configuration():
    grp = "2. Configuration"
    # 2.1.1
    loaded_mods = []
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "load_module" and len(toks) >= 2:
            loaded_mods.append(toks[1])
    unexpected = [m for m in loaded_mods if os.path.basename(m) not in ALLOWED_DYN_MODS and m not in ALLOWED_DYN_MODS]
    if not loaded_mods:
        add_result("2.1.1", grp, "Only required dynamic modules loaded", True, "Khong nap dynamic module nao (0 load_module)")
    else:
        add_result("2.1.1", grp, "Only required dynamic modules loaded", len(unexpected) == 0, f"Dynamic modules: {', '.join(loaded_mods)}")

    # Identify nginx service user for 2.2.1..2.2.3
    svc_user = None
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "user" and len(toks) >= 2:
            svc_user = toks[1]
            break

    # 2.2.1
    if not svc_user:
        add_result("2.2.1", grp, "Non-privileged dedicated service account", False, "Chua khai bao chi thi 'user' trong nginx.conf")
    else:
        rc_id, out_uid = run_cmd(["id", "-u", svc_user])
        rc_grp, out_grp = run_cmd(["id", "-Gn", svc_user])
        _, out_sudo = run_cmd(["sudo", "-n", "-l", "-U", svc_user])
        priv_groups = {"root", "wheel", "sudo", "admin", "adm"}
        user_groups = set(out_grp.strip().split()) if rc_grp == 0 else set()
        bad_groups = user_groups & priv_groups
        uid_ok = rc_id == 0 and out_uid.strip().isdigit() and int(out_uid.strip()) != 0
        sudo_ok = "not allowed to run sudo" in out_sudo.lower()
        ok = uid_ok and not bad_groups and sudo_ok
        add_result(
            "2.2.1",
            grp,
            "Non-privileged dedicated service account",
            ok,
            f"user={svc_user}, uid={out_uid.strip()}, groups={','.join(sorted(user_groups))}, sudo_blocked={sudo_ok}",
        )

    # 2.2.2
    if not svc_user:
        add_result("2.2.2", grp, "Service account is locked", False, "Khong xac dinh duoc user NGINX")
    else:
        rc_pw, out_pw = run_cmd(["passwd", "-S", svc_user])
        parts = out_pw.strip().split()
        lock_flag = parts[1] if len(parts) >= 2 else "?"
        ok = rc_pw == 0 and lock_flag in ("L", "LK")
        add_result("2.2.2", grp, "Service account is locked", ok, f"passwd -S {svc_user}: trang thai={lock_flag}")

    # 2.2.3
    if not svc_user:
        add_result("2.2.3", grp, "Service account has invalid shell", False, "Khong xac dinh duoc user NGINX")
    else:
        rc_sh, out_sh = run_cmd(["getent", "passwd", svc_user])
        shell = out_sh.strip().split(":")[-1] if rc_sh == 0 and ":" in out_sh else "?"
        ok = shell in ("/usr/sbin/nologin", "/sbin/nologin", "/bin/nologin", "/bin/false")
        add_result("2.2.3", grp, "Service account has invalid shell", ok, f"shell={shell}")

    # 2.3.1 & 2.3.2
    bad_owner = []
    bad_dir_perm = []
    bad_file_perm = []
    if not os.path.isdir(NGINX_CONF_DIR):
        add_result("2.3.1", grp, "Config owned by root:root", False, f"Khong tim thay {NGINX_CONF_DIR}")
        add_result("2.3.2", grp, "Config permissions restricted (750/640)", False, f"Khong tim thay {NGINX_CONF_DIR}")
    else:
        for dirpath, dirnames, filenames in os.walk(NGINX_CONF_DIR):
            paths_to_check = [(dirpath, True)]
            for fn in filenames:
                paths_to_check.append((os.path.join(dirpath, fn), False))
            for dn in dirnames:
                sub = os.path.join(dirpath, dn)
                if os.path.islink(sub):
                    paths_to_check.append((sub, True))
            for p, expect_dir in paths_to_check:
                try:
                    lst = os.lstat(p)
                    if lst.st_uid != 0 or lst.st_gid != 0:
                        bad_owner.append(f"{p} ({lst.st_uid}:{lst.st_gid})")
                    if os.path.islink(p) and not os.path.exists(p):
                        continue
                    st = os.stat(p)
                    if st.st_uid != 0 or st.st_gid != 0:
                        bad_owner.append(f"{p} ({st.st_uid}:{st.st_gid})")
                    mode = stat.S_IMODE(st.st_mode)
                    if stat.S_ISDIR(st.st_mode) or expect_dir:
                        if (mode & 0o027) != 0:
                            bad_dir_perm.append(f"{p} ({oct(mode)[2:]})")
                    else:
                        if (mode & 0o137) != 0:
                            bad_file_perm.append(f"{p} ({oct(mode)[2:]})")
                except OSError:
                    pass
        add_result(
            "2.3.1",
            grp,
            "Config owned by root:root",
            len(bad_owner) == 0,
            "Tat ca thuoc root:root" if not bad_owner else f"Sai owner ({len(bad_owner)}): {', '.join(bad_owner[:3])}",
        )
        perm_ok = len(bad_dir_perm) == 0 and len(bad_file_perm) == 0
        if perm_ok:
            perm_msg = "Thu muc <= 750, tep <= 640"
        else:
            samples = bad_dir_perm[:2] + bad_file_perm[:2]
            perm_msg = f"Vi pham: {len(bad_dir_perm)} thu muc, {len(bad_file_perm)} tep (vd: {', '.join(samples)})"
        add_result("2.3.2", grp, "Config permissions restricted (750/640)", perm_ok, perm_msg)

    # 2.3.3
    pid_path = "/run/nginx.pid"
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "pid" and len(toks) >= 2:
            pid_path = toks[1]
            break
    else:
        mp = re.search(r"--pid-path=(\S+)", NGINX_V_RAW)
        if mp:
            pid_path = mp.group(1)
    if not os.path.exists(pid_path):
        add_result("2.3.3", grp, "NGINX PID file secured", False, f"Khong tim thay PID file: {pid_path}")
    else:
        st = os.stat(pid_path)
        mode = stat.S_IMODE(st.st_mode)
        ok = st.st_uid == 0 and st.st_gid == 0 and (mode & 0o133) == 0
        add_result("2.3.3", grp, "NGINX PID file secured", ok, f"{pid_path}: uid={st.st_uid}, gid={st.st_gid}, mode={oct(mode)[2:]}")

    # 2.4.1
    cfg_ports = set()
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "listen":
            p = parse_listen_port(toks)
            if p is not None:
                cfg_ports.add(p)
    all_seen_ports = cfg_ports | listening_ports
    bad_ports = sorted(p for p in all_seen_ports if p not in ALLOWED_PORTS)
    ok_241 = bool(all_seen_ports) and len(bad_ports) == 0
    add_result(
        "2.4.1",
        grp,
        "Only authorized ports open",
        ok_241,
        f"Cong cau hinh={sorted(cfg_ports)}, cong dang nghe={sorted(listening_ports)}"
        + (f"; cong la={bad_ports}" if bad_ports else ""),
    )

    # 2.4.2
    has_default_reject = False
    has_https_default_reject = False
    for sb in SERVER_BLOCKS:
        dirs = sb["directives"]
        has_def_80 = any(d.startswith("listen ") and "default_server" in d and ":443" not in d and " 443 " not in d and " 443;" not in (d + ";") for d in dirs)
        has_def_443 = any(d.startswith("listen ") and "default_server" in d and ("443" in d) for d in dirs)
        has_ret = any(re.match(r"return\s+(444|40[034])\b", d) for d in dirs)
        has_ssl_rej = any(re.match(r"ssl_reject_handshake\s+on\b", d) for d in dirs)
        if (has_def_80 or has_def_443) and has_ret:
            has_default_reject = True
        if has_def_443 and (has_ssl_rej or has_ret):
            has_https_default_reject = True
    bad_host_http = curl_probe("/", host_header="invalid.example.com", force_http=True)
    http_rej_ok = bad_host_http[0] in ("000", "400", "403", "404", "444")
    https_rej_ok = True
    if USE_HTTPS:
        bad_host_https = curl_probe("/", host_header="invalid.example.com", force_http=False)
        https_rej_ok = bad_host_https[0] in ("000", "400", "403", "404", "444")
    ok_242 = has_default_reject and http_rej_ok and https_rej_ok
    add_result(
        "2.4.2",
        grp,
        "Reject unknown Host requests",
        ok_242,
        f"default_server_444={has_default_reject}, https_reject={has_https_default_reject}, probe_invalid_http={bad_host_http[0]}",
    )

    # 2.4.3
    ka_vals = []
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "keepalive_timeout" and len(toks) >= 2:
            sec = parse_time_seconds(toks[1])
            if sec is not None:
                ka_vals.append(sec)
    ok_243 = bool(ka_vals) and all(0 < v <= MAX_KEEPALIVE_TIMEOUT for v in ka_vals)
    add_result(
        "2.4.3",
        grp,
        "keepalive_timeout <= 10s (not 0)",
        ok_243,
        f"keepalive_timeout={ka_vals if ka_vals else 'chua khai bao (mac dinh 75s)'}",
    )

    # 2.4.4
    st_vals = []
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "send_timeout" and len(toks) >= 2:
            sec = parse_time_seconds(toks[1])
            if sec is not None:
                st_vals.append(sec)
    ok_244 = bool(st_vals) and all(0 < v <= MAX_SEND_TIMEOUT for v in st_vals)
    add_result(
        "2.4.4",
        grp,
        "send_timeout <= 10s (not 0)",
        ok_244,
        f"send_timeout={st_vals if st_vals else 'chua khai bao (mac dinh 60s)'}",
    )

    # 2.5.1
    st_off = any(re.fullmatch(r"server_tokens\s+off", d) for _, d in ALL_DIRS)
    st_on = any(re.fullmatch(r"server_tokens\s+on", d) for _, d in ALL_DIRS)
    srv_hdrs = LIVE_ROOT[1].get("server", [])
    leaks_ver = any(re.search(r"nginx/\d+", h, re.I) for h in srv_hdrs)
    ok_251 = st_off and not st_on and not leaks_ver and LIVE_ROOT[0] not in (None, "000")
    add_result(
        "2.5.1",
        grp,
        "server_tokens set to off",
        ok_251,
        f"server_tokens_off={st_off}, HTTP Server header={srv_hdrs if srv_hdrs else 'none/closed'} (code={LIVE_ROOT[0]})",
    )

    # 2.5.2
    has_err_page = any(d.startswith("error_page ") for _, d in ALL_DIRS)
    body_404_has_nginx = "nginx" in LIVE_404[2].lower()
    body_root_stock = "welcome to nginx" in LIVE_ROOT[2].lower()
    ok_252 = has_err_page and LIVE_404[0] not in (None, "000") and not body_404_has_nginx and not body_root_stock
    add_result(
        "2.5.2",
        grp,
        "Custom error/index hide NGINX",
        ok_252,
        f"error_page={has_err_page}, 404_leaks_nginx={body_404_has_nginx}, stock_index={body_root_stock}",
    )

    # 2.5.3
    has_hidden_deny = False
    for _, d_blk in [(None, blk) for blk in iter_blocks(AST, "location")]:
        hdr = d_blk["header"]
        if re.search(r"/\\\.", hdr):
            if any(re.match(r"deny\s+all\b", x) or re.match(r"return\s+40[34]\b", x) for x in d_blk["directives"]):
                has_hidden_deny = True
                break
    git_code = LIVE_GIT[0]
    ok_253 = has_hidden_deny and git_code in ("403", "404")
    add_result(
        "2.5.3",
        grp,
        "Hidden file serving disabled",
        ok_253,
        f"rule_location_hidden={has_hidden_deny}, probe_/.git/HEAD={git_code}",
    )


def check_3_logging():
    grp = "3. Logging"
    # 3.1
    formats = {}
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "log_format" and len(toks) >= 3:
            name = toks[1]
            fmt_body = " ".join(toks[2:])
            formats[name] = fmt_body
    used_custom = []
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "access_log" and len(toks) >= 3 and toks[1] != "off":
            if toks[2] in formats:
                used_custom.append((toks[1], toks[2]))
    detailed_ok = False
    for _, fmt_name in used_custom:
        body = formats[fmt_name]
        if all(tok in body for tok in ("$remote_addr", "$status", "$http_user_agent")) and ("$request" in body or "$request_uri" in body):
            detailed_ok = True
            break
    add_result(
        "3.1",
        grp,
        "Detailed access log format (JSON/custom)",
        detailed_ok,
        f"log_format={list(formats.keys()) or 'khong co'}, dang dung={used_custom or 'mac dinh combined'}",
    )

    # 3.2
    global_off = False
    active_logs = []
    for ctx, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "access_log" and len(toks) >= 2:
            if toks[1] == "off":
                if not ctx.startswith("location"):
                    global_off = True
            elif toks[1] != "/dev/null":
                active_logs.append(f"{ctx}:{toks[1]}")
    ok_32 = bool(active_logs) and not global_off
    add_result(
        "3.2",
        grp,
        "Access logging enabled",
        ok_32,
        f"access_log={active_logs[:2] or 'khong co'}, global_off={global_off}",
    )

    # 3.3
    err_logs = []
    good_level = False
    for ctx, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "error_log" and len(toks) >= 2:
            path = toks[1]
            lvl = toks[2].lower() if len(toks) >= 3 else "default(error)"
            err_logs.append(f"{ctx}:{path}({lvl})")
            if ctx in ("main", "http") and path != "/dev/null" and lvl in ("info", "notice", "warn", "debug"):
                good_level = True
    add_result(
        "3.3",
        grp,
        "Error log enabled (level info/notice)",
        good_level,
        f"error_log={err_logs or 'khong co'}",
    )


def check_4_tls():
    grp = "4. SSL/TLS"
    # 4.1.1
    has_redir_cfg = False
    for sb in SERVER_BLOCKS:
        dirs = sb["directives"]
        listens_80 = any(d.startswith("listen ") and (":80" in d or re.search(r"\b80\b", d)) for d in dirs)
        redirects = any(re.search(r"(return\s+30[18]\s+https://|rewrite\s+.*https://)", d) for d in dirs)
        if listens_80 and redirects:
            has_redir_cfg = True
            break
    probe_80 = curl_probe("/", force_http=True)
    redir_live = probe_80[0] in ("301", "308") and any(loc.lower().startswith("https://") for loc in probe_80[1].get("location", []))
    add_result(
        "4.1.1",
        grp,
        "HTTP redirected to HTTPS",
        has_redir_cfg and redir_live,
        f"cfg_redirect={has_redir_cfg}, http_probe={probe_80[0]} loc={probe_80[1].get('location', [])}",
    )

    # 4.1.3
    key_paths = set()
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "ssl_certificate_key" and len(toks) >= 2:
            key_paths.add(toks[1])
    for dp, _, fns in os.walk(NGINX_CONF_DIR) if os.path.isdir(NGINX_CONF_DIR) else []:
        for fn in fns:
            if fn.endswith(".key"):
                key_paths.add(os.path.join(dp, fn))
    bad_keys = []
    if not key_paths:
        add_result("4.1.3", grp, "Private key permissions <= 400", False, "Chua cau hinh ssl_certificate_key hoac file .key")
    else:
        for kp in sorted(key_paths):
            if not os.path.exists(kp):
                bad_keys.append(f"{kp}(khong ton tai)")
                continue
            st = os.stat(kp)
            mode = stat.S_IMODE(st.st_mode)
            if st.st_uid != 0 or (mode & 0o377) != 0:
                bad_keys.append(f"{kp}(mode={oct(mode)[2:]},uid={st.st_uid})")
        add_result(
            "4.1.3",
            grp,
            "Private key permissions <= 400",
            len(bad_keys) == 0,
            f"keys={sorted(key_paths)} -> " + ("Tat ca <= 400" if not bad_keys else f"Vi pham: {', '.join(bad_keys)}"),
        )

    # 4.1.4 & 4.1.5 & 4.1.6
    proto_vals = []
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] in ("ssl_protocols", "proxy_ssl_protocols"):
            proto_vals.append((toks[0], toks[1:]))
    only_tls13 = bool(proto_vals) and all(protos == ["TLSv1.3"] for _, protos in proto_vals)
    add_result(
        "4.1.4",
        grp,
        "Only TLSv1.3 protocol enabled",
        only_tls13,
        f"ssl_protocols={[ ' '.join(p) for _, p in proto_vals ] or 'khong co'}",
    )

    weak_cipher_match = []
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] in ("ssl_ciphers", "proxy_ssl_ciphers"):
            joined = " ".join(toks[1:])
            if re.search(r"(NULL|EXPORT|RC4|DES|MD5|aNULL|eNULL|SHA1)", joined, re.I):
                weak_cipher_match.append(joined)
    ok_415 = only_tls13 and not weak_cipher_match
    add_result(
        "4.1.5",
        grp,
        "Disable weak ciphers (TLS 1.3 only)",
        ok_415,
        f"TLSv1.3_exclusive={only_tls13}, weak_ssl_ciphers={weak_cipher_match or 'none'}",
    )

    has_dhparam = any(split_tokens(d)[:1] == ["ssl_dhparam"] for _, d in ALL_DIRS)
    ok_416 = only_tls13 and not has_dhparam
    add_result(
        "4.1.6",
        grp,
        "TLS 1.3 DH params (no ssl_dhparam)",
        ok_416,
        f"TLSv1.3_exclusive={only_tls13}, ssl_dhparam_present={has_dhparam}",
    )


def check_5_request_controls():
    grp = "5. Request Controls/Headers"
    # 5.2.1
    timeout_map = {}
    for name in ("client_header_timeout", "client_body_timeout", "send_timeout"):
        vals = []
        for _, d in ALL_DIRS:
            toks = split_tokens(d)
            if toks and toks[0] == name and len(toks) >= 2:
                sec = parse_time_seconds(toks[1])
                if sec is not None:
                    vals.append(sec)
        timeout_map[name] = vals
    ok_521 = all(
        bool(vals) and all(MIN_REQ_TIMEOUT <= v <= MAX_REQ_TIMEOUT for v in vals)
        for vals in timeout_map.values()
    )
    summary_521 = ", ".join(f"{k}={v if v else 'unset(60s)'}" for k, v in timeout_map.items())
    add_result("5.2.1", grp, "Client header/body/send timeouts (10-20s)", ok_521, summary_521)

    # 5.2.2
    body_vals = []
    for ctx, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "client_max_body_size" and len(toks) >= 2:
            sz = parse_size_bytes(toks[1])
            body_vals.append((ctx, toks[1], sz))
    has_http_limit = any(ctx in ("http", "server") and sz is not None and sz > 0 for ctx, _, sz in body_vals)
    no_disabled = all(sz is not None and sz > 0 for _, _, sz in body_vals)
    ok_522 = bool(body_vals) and has_http_limit and no_disabled
    add_result(
        "5.2.2",
        grp,
        "Maximum request body size defined",
        ok_522,
        f"client_max_body_size={[(c, r) for c, r, _ in body_vals] or 'unset (mac dinh 1m)'}",
    )

    # 5.2.3
    lchb_vals = []
    for _, d in ALL_DIRS:
        toks = split_tokens(d)
        if toks and toks[0] == "large_client_header_buffers" and len(toks) >= 3:
            num = int(toks[1]) if toks[1].isdigit() else None
            sz = parse_size_bytes(toks[2])
            lchb_vals.append((toks[1], toks[2], num, sz))
    if not lchb_vals:
        add_result("5.2.3", grp, "large_client_header_buffers compliant", True, "Chua khai bao tuong minh (dung mac dinh an toan 4 8k theo CIS v3.0.0)")
    else:
        ok_523 = all(n is not None and sz is not None and n >= 4 and sz >= 8192 for _, _, n, sz in lchb_vals)
        add_result("5.2.3", grp, "large_client_header_buffers compliant", ok_523, f"Gia tri={[(n_s, sz_s) for n_s, sz_s, _, _ in lchb_vals]}")

    # 5.3.1
    cfg_xcto = any(
        re.match(r'^add_header\s+["\']?X-Content-Type-Options["\']?\s+["\']?nosniff["\']?\s+always\b', d, re.I)
        for _, d in ALL_DIRS
    )
    live_root_xcto = any(v.lower() == "nosniff" for v in LIVE_ROOT[1].get("x-content-type-options", []))
    live_404_xcto = any(v.lower() == "nosniff" for v in LIVE_404[1].get("x-content-type-options", []))
    ok_531 = cfg_xcto and live_root_xcto and live_404_xcto
    add_result(
        "5.3.1",
        grp,
        "X-Content-Type-Options: nosniff always",
        ok_531,
        f"cfg_always={cfg_xcto}, live_200={live_root_xcto}, live_404={live_404_xcto}",
    )

    # 5.3.3
    safe_rp = {"no-referrer", "strict-origin", "strict-origin-when-cross-origin", "same-origin"}
    cfg_rp = any(
        re.match(
            r'^add_header\s+["\']?Referrer-Policy["\']?\s+["\']?(no-referrer|strict-origin|strict-origin-when-cross-origin|same-origin)["\']?\s+always\b',
            d,
            re.I,
        )
        for _, d in ALL_DIRS
    )
    rp_200 = [v.lower() for v in LIVE_ROOT[1].get("referrer-policy", [])]
    rp_404 = [v.lower() for v in LIVE_404[1].get("referrer-policy", [])]
    live_root_rp = any(v in safe_rp for v in rp_200)
    live_404_rp = any(v in safe_rp for v in rp_404)
    ok_533 = cfg_rp and live_root_rp and live_404_rp
    add_result(
        "5.3.3",
        grp,
        "Referrer-Policy header always",
        ok_533,
        f"cfg_always={cfg_rp}, live_200={rp_200 or 'missing'}, live_404={rp_404 or 'missing'}",
    )


check_1_installation()
check_2_configuration()
check_3_logging()
check_4_tls()
check_5_request_controls()

total = len(results)
passed = sum(1 for r in results if r[3] == "PASS")
failed = total - passed
pct = (passed / total * 100.0) if total else 0.0

now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
hostname = socket.gethostname()
_, os_rel = run_cmd(["bash", "-c", "grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2- | tr -d '\"'"])
nginx_ver_line = NGINX_V_RAW.splitlines()[0] if NGINX_V_RAW.splitlines() else "unknown"

plain_lines = []
term_lines = []

header_block = [
    "==============================================================================",
    f"CIS NGINX BENCHMARK v3.0.0 - AUDIT REPORT ({STAGE.upper()})",
    "==============================================================================",
    f"Timestamp   : {now_str}",
    f"Hostname    : {hostname}",
    f"OS          : {os_rel.strip()}",
    f"NGINX       : {nginx_ver_line}",
    f"Probe Target: {'https' if USE_HTTPS else 'http'}://{EFFECTIVE_HOST}:{HTTPS_PORT if USE_HTTPS else HTTP_PORT} (HTTP={LIVE_ROOT[0]}, 404={LIVE_404[0]})",
    "==============================================================================",
]
plain_lines.extend(header_block)
term_lines.append(C_CYAN + C_BOLD + "\n".join(header_block) + C_RESET)

current_grp = None
for cid, grp, title, status, detail in results:
    if grp != current_grp:
        current_grp = grp
        plain_lines.append(f"\n--- {grp} ---")
        term_lines.append(f"\n{C_BOLD}--- {grp} ---{C_RESET}")
    plain_lines.append(f"[{status:4s}] {cid:<6s} | {title:<42s} | {detail}")
    col = C_GREEN if status == "PASS" else C_RED
    term_lines.append(f"[{col}{status:4s}{C_RESET}] {C_BOLD}{cid:<6s}{C_RESET} | {title:<42s} | {detail}")

plain_lines.append("\n==============================================================================")
plain_lines.append("THONG KE THEO NHOM:")
term_lines.append("\n" + C_CYAN + "==============================================================================" + C_RESET)
term_lines.append(C_BOLD + "THONG KE THEO NHOM:" + C_RESET)

groups_order = []
for _, grp, _, _, _ in results:
    if grp not in groups_order:
        groups_order.append(grp)

for grp in groups_order:
    sub = [r for r in results if r[1] == grp]
    sp = sum(1 for r in sub if r[3] == "PASS")
    line = f"  {grp:<28s}: {sp:2d}/{len(sub):2d} PASS"
    plain_lines.append(line)
    term_lines.append(line)

summary_line = f"TONG KET ({STAGE.upper()}): PASS={passed}/{total} ({pct:.1f}%), FAIL={failed}/{total}"
plain_lines.append("------------------------------------------------------------------------------")
plain_lines.append(summary_line)
plain_lines.append(f"Xuat bao cao: {REPORT_TXT}")
plain_lines.append(f"Xuat CSV    : {SUMMARY_CSV}")
plain_lines.append("==============================================================================")

term_lines.append("------------------------------------------------------------------------------")
sum_col = C_GREEN if failed == 0 else C_YELLOW
term_lines.append(sum_col + C_BOLD + summary_line + C_RESET)
term_lines.append(f"Xuat bao cao: {REPORT_TXT}")
term_lines.append(f"Xuat CSV    : {SUMMARY_CSV}")
term_lines.append(C_CYAN + "==============================================================================" + C_RESET)

with open(REPORT_TXT, "w", encoding="utf-8") as f:
    f.write("\n".join(plain_lines) + "\n")

with open(SUMMARY_CSV, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["CIS_ID", "Group", "Control", "Status", "Detail"])
    for r in results:
        w.writerow(r)

print("\n".join(term_lines))

if STAGE == "after" and failed > 0:
    sys.exit(1)
sys.exit(0)
PYEOF

  # Preserve non-root repo owner permissions on generated evidence files when run with sudo
  if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    chown -R "${SUDO_UID}:${SUDO_GID}" "${evidence_dir}"
  fi

  return "${exit_rc}"
}
