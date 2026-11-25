# CIS NGINX v3.0.0 — Ansible only

Kiểm tra → áp dụng cấu hình mong muốn → kiểm tra lại, bằng playbook/role/module/Jinja Ansible.
Không còn `cisctl`, Python collector/engine/runner hay callback Python tự viết. Ansible vẫn cần
Python để hoạt động; `.venv` chỉ cô lập cài đặt Ansible, không phải một phương pháp audit riêng.

Phạm vi: 30 tiêu chí được liệt kê ở `roles/cis_audit/vars/main.yml`; không tuyên bố bao phủ toàn bộ
CIS Benchmark. Manual có 5 tiêu chí Section 5; ví dụ Manual riêng 5.3.3. Máy lab riêng, role thay
thế toàn bộ nginx.conf và website lab. Ubuntu Server 26.04 VMware / 24.04 EC2 (role hỗ trợ cả hai).

## Cài công cụ trên VM controller

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip openssh-client curl openssl
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ansible-playbook -i inventory/hosts.yml site.yml --syntax-check
```

Máy đích cần Python 3, sudo, NGINX và các lệnh `curl`, `openssl`, `timeout`, `ss`, `find`, `getent`,
`id`, `passwd`, `apt-cache`. Chuẩn bị baseline và snapshot trước hardening. Để audit được trước
khi Section 1 cài công cụ, cài các phụ thuộc hệ thống trước: `sudo apt install -y nginx curl openssl iproute2 sudo`.
Trước audit, chạy `sudo systemctl enable --now nginx`, `sudo nginx -t` và thử `curl --noproxy '*' -sSI http://127.0.0.1/`. Nếu baseline không có dịch vụ HTTP truy cập được, audit ghi ERROR và chặn remediation cho tới khi sửa nguyên nhân chuẩn bị.
Manual không cần `.venv`.

## Ví dụ Local — đọc audit trước rồi quyết định khắc phục

Trong terminal VM của VS Code, tại thư mục repo, đã kích hoạt `.venv`:

```bash
CIS_RUN_ID=local-ansible-01
ansible-playbook -i inventory/hosts.yml site.yml -K \
  -e cis_action=audit -e cis_audit_stage=before -e cis_section=5 -e cis_run_id="$CIS_RUN_ID"
cat "evidence/$CIS_RUN_ID/nginx-cis-server/before/audit-summary.csv"
```

Audit có FAIL/REVIEW vẫn xuất đầy đủ kết quả rồi lệnh kết thúc nonzero; điều này không tự thực
hiện remediation. Đọc CSV và raw trước. `nginx-cis-server` ở đường dẫn là **alias inventory**,
không phải tên user hay kết quả `hostname`. Nếu đổi alias thì đổi đường dẫn tương ứng.

Khi bạn quyết định áp dụng chính sách Section 5:

```bash
ansible-playbook -i inventory/hosts.yml site.yml -K \
  -e cis_action=remediate -e cis_section=5 -e cis_run_id="$CIS_RUN_ID"
ansible-playbook -i inventory/hosts.yml site.yml -K \
  -e cis_action=audit -e cis_audit_stage=after -e cis_section=5 -e cis_run_id="$CIS_RUN_ID"
cat "evidence/$CIS_RUN_ID/nginx-cis-server/after/audit-summary.csv"
cat "evidence/$CIS_RUN_ID/comparison.csv"
```

Dùng cùng run ID, alias, host set, section, biến cấu hình và code cho ba lệnh. Cả Local/Remote
`remediate` đều yêu cầu before live hợp lệ, không ERROR. Đây là kiểm tra kỹ thuật, không có
bản ghi phê duyệt điện tử; việc bạn chủ động chạy `remediate` thể hiện quyết định sửa.

## Chạy trọn chu trình và kiểm tra lũy đẳng

Đây là cách thay thế ví dụ tách lệnh, không chạy thêm trên cùng run ID. Khôi phục baseline,
sao lưu evidence ra ngoài VM trước nếu quay demo lại; dùng run ID mới.

```bash
set -o pipefail
mkdir -p evidence
ansible-playbook -i inventory/hosts.yml site.yml -K \
  -e cis_action=run -e cis_section=5 -e cis_run_id=local-full-01 \
  -e cis_idempotence=true 2>&1 | tee evidence/local-full-01.log
CIS_RC=${PIPESTATUS[0]}
printf 'ansible exit=%s\n' "$CIS_RC"
```

`run` không hỏi đồng ý sau audit: đã chọn run là chọn tự audit → remediation → re-audit.
Before ERROR chặn thay đổi host đó; FAIL/REVIEW không chặn. `-K` xác thực sudo, không phải phê duyệt.
Không dùng `--check` để thay audit: audit thật đã chỉ đọc NGINX, còn `--check` có thể bỏ qua lệnh đọc.
Mặc định action là **audit**, không mặc định sửa cấu hình. `cis_section=all` chọn đủ 30 tiêu chí.

## Kết quả cuối cùng

```text
evidence/<run-id>/
  <inventory-alias>/
    manifest.json
    before/{audit.json,audit-summary.csv,audit-report.txt,raw/collected.json}
    remediation/result.json
    after/{audit.json,audit-summary.csv,audit-report.txt,raw/collected.json}
    idempotence.json                  # khi yêu cầu và lần hai thực thi được
    after-idempotence/                # audit sau lần áp dụng thứ hai
    summary.json
  summary.json                       # tổng hợp mọi host được chọn, kể cả host lỗi
  hosts.csv
  comparison.csv
```

`audit-summary.csv`: `CIS_ID,Group,Control,Status,Detail`. JSON còn có đường dẫn evidence cho
mỗi tiêu chí. Status: PASS đạt, FAIL chưa đạt, ERROR không đánh giá được vì lỗi thực thi,
REVIEW cần xem xét. SSH unreachable được ghi lỗi thực thi cấp host; không tạo giả 30 dòng FAIL.

**Mã thoát Ansible không còn quy ước 0/1/2 của cisctl cũ.** 0 là lần gọi hoàn thành theo yêu cầu;
nonzero cần đọc `summary.json` để phân biệt FAIL/REVIEW/ERROR. Với action remediate, thành công
được ghi `REMEDIATED_NOT_REAUDITED`, chưa kết luận tuân thủ. `PLAY RECAP failed=0` không thay
cho Status CIS. Tệp raw có cấu hình hệ thống; giữ trong hồ sơ riêng, không commit evidence/khóa.

## Những hành vi cần hiểu đúng

- Khắc phục theo section, không chỉ các dòng FAIL. `nginx_cis_enabled` tích lũy section cũ + mới;
  section đã bật có thể chạy lại. Audit chỉ đánh giá phạm vi được chọn trong lần gọi.
- Defaults đặt chính sách mong muốn, task kiểm tra đầu vào, template sinh cấu hình;
  module copy so sánh tệp/thông tin owner-mode, handler chỉ reload khi được notify.
- Bộ audit mới dùng command/stat + register + set_fact/Jinja để phân tích, rồi template JSON/CSV.
  Có lexer cấu hình giữ chuỗi trích dẫn, comment, block và include; khi không phân tích trọn vẹn
  trả REVIEW thay vì khẳng định PASS. HTTP/TLS probe kiểm tra website được chọn bằng `cis_probe_host`
  (workflow dùng `nginx_cis_primary_name`); không chứng nhận mọi website/đường dẫn trên máy.
- Một số tiêu chí là chính sách lab: bản NGINX tối thiểu 1.28.0, TLS1.3-only, timeout 10s, body2M,
  buffers4x8k. Không đồng nhất mọi giá trị này với yêu cầu bắt buộc duy nhất của CIS.
- Lũy đẳng dựa trên **các thay đổi thực của role khắc phục lần hai**: mutation tasks gửi notify
  tới handler đánh dấu thay đổi; không tính việc ghi evidence. Cần `idempotent=true` và audit
  sau lần hai đạt. Lỗi lần hai không được ghi thành stable chỉ vì không thấy changed.
- Audit không `apt update`, không sửa cấu hình NGINX và không reload. Kiểm tra candidate dựa trên
  APT metadata đang có; ghi nhận thời điểm và cập nhật metadata trong chuẩn bị nếu cần.
- Manifest khóa identity/code/policy/scope/host set. Audit stages và remediation không được ghi đè.
  Lock ở `evidence/.ansible-workflow.lock` chặn hai lượt đồng thời trên cùng controller/evidence root.
  Nếu bị ngắt cưỡng bức, xác minh không còn playbook chạy rồi mới xóa thư mục lock rỗng.
  Các controller độc lập phải tự phối hợp để không đồng thời sửa cùng một máy đích.

## Quyền và Remote

Local: Ansible nâng quyền root trên VM cho thu thập và khắc phục. Remote: controller chạy bằng
user thường, EC2 nâng quyền root; việc cài công cụ trên controller có thể cần sudo. Không tự
cấp sudo và không yêu cầu blanket `NOPASSWD: ALL`; kiểm tra `sudo -l` trên từng máy.
Nếu EC2 sudo không cần mật khẩu, bỏ `-K`; nếu cần, `-K` hỏi mật khẩu tài khoản EC2. Không lưu
mật khẩu trong inventory hoặc lệnh. Xem [hướng dẫn Remote](docs/REMOTE.md).

Tổ chức mã, luồng thực thi và bảng tiêu chí: [ARCHITECTURE](docs/ARCHITECTURE.md).
Manual: [MANUAL](docs/MANUAL.md). Phân công/quay demo: [DEMO](docs/DEMO.md).
