# NGINX CIS Benchmark 3.0.0 + Ansible

Bộ lab của nhóm 12: **Manual 5 tiêu chí**, **Local Automated 30 tiêu chí**.
**Remote Automated đã có mã điều phối**, dùng cùng 30 tiêu chí trên mỗi EC2; xem [hướng dẫn điền và chạy bốn EC2](docs/REMOTE.md).
IP, khóa SSH, kết nối, baseline, minh chứng và video thực tế do nhóm bổ sung.
Dùng **VS Code Remote SSH → VM Ubuntu VMware** để sửa code và chạy lệnh.

## Phạm vi sử dụng

Role dành cho **VM Ubuntu Server 26.04 trên VMware riêng để làm lab**, có systemd, Python 3, sudo và Internet.
Role quản lý toàn bộ `/etc/nginx/nginx.conf`, thay website bằng website lab, đổi worker account và nguồn gói. Chụp baseline trước khi chạy; không trỏ vào server ứng dụng đang dùng.
EC2 dùng Ubuntu Server 24.04 LTS sau khi nhóm xác nhận VERSION_ID. Bản Local cũng cho phép Ubuntu 24.04 để kiểm thử tương thích. Ansible Core 2.21 hỗ trợ Python 3.14 trên VM 26.04 và Python 3.12 trên Ubuntu 24.04.
Self-signed TLS phục vụ lab; CIS 4.1.2 không thuộc 30 tiêu chí đã chọn.
Repo không chứa Terraform hoặc chức năng tạo EC2.

## Bắt đầu trên terminal của VM

```bash
git clone https://github.com/ThanhLen-IT/cis-nginx-benchmark-automation.git
cd cis-nginx-benchmark-automation
# Nếu dùng PR chưa merge, checkout đúng nhánh trong PR trước.
sudo apt update
sudo apt install -y python3-venv python3-pip sudo curl openssl iproute2 git
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
ansible-playbook -i inventory/hosts.yml site.yml --syntax-check
./cisctl run --ask-become-pass --idempotence
```

Mỗi lần chạy có ID mới. Đường dẫn bằng chứng được in ra trên terminal. Kết quả được đo trên VM; repo không kèm số liệu PASS cho máy của bạn.
Lần chạy đầy đủ có Section 1 nên có thể cài/nâng cấp NGINX từ nguồn nginx.org; các section 2–5 chạy riêng cần NGINX sẵn có.

## Lệnh sử dụng

| Mục đích | Lệnh |
|---|---|
| Audit độc lập 30 tiêu chí | `./cisctl audit --ask-become-pass` |
| Khắc phục toàn bộ | `./cisctl remediate --ask-become-pass` |
| Audit → khắc phục → audit | `./cisctl run --ask-become-pass` |
| Kiểm tra thêm tính lũy đẳng | `./cisctl run --ask-become-pass --idempotence` |
| Chạy một section | `./cisctl run --section 5 --ask-become-pass` |
| Đổi tên website lab | Thêm `--vars-file config/lab.example.yml` |
| Remote một EC2 | `./cisctl run --mode remote --inventory inventory/hosts-aws.local.yml --limit nginx01 --run-id remote-one-01 --idempotence` |
| Remote đủ bốn EC2 | `./cisctl run --mode remote --inventory inventory/hosts-aws.local.yml --run-id remote-four-01 --idempotence` |

Chọn section bằng `--section` của cisctl, **không dùng `--tags` trực tiếp** với bản role này. Các task dùng chung phải chạy để kiểm tra phụ thuộc và biên dịch website đầy đủ.
Profile lưu ở `/var/lib/nginx-cis/profile.json`; chạy section sau giữ các section đã bật trước. Vì có cấu hình chung, không diễn giải lựa chọn section như cam kết chỉ chạm một directive.
Run theo section chỉ đánh giá số tiêu chí trong section đó; lượt nghiệm thu dùng `--section all`.

### Tách ba lệnh, cùng một lần thực nghiệm

```bash
./cisctl audit --stage before --section all --run-id demo01 --ask-become-pass
# audit trả 1 nếu có FAIL/REVIEW; kiểm tra báo cáo trước khi chạy bước tiếp.
./cisctl remediate --section all --run-id demo01 --ask-become-pass
./cisctl audit --stage after --section all --run-id demo01 --ask-become-pass
```

Không nối audit bằng `&&` khi muốn khắc phục baseline FAIL. Lệnh `run` đã xử lý việc này.
Một run ID giữ nguyên section và vars file. Stage đã tồn tại bị từ chối ghi đè; dùng run ID khác khi quay lại.

## Remote

```bash
cp inventory/hosts-aws.example.yml inventory/hosts-aws.local.yml
# Điền IP/DNS, SSH user/key và kiểm tra kết nối theo docs/REMOTE.md.
./cisctl run --mode remote --inventory inventory/hosts-aws.local.yml \
  --limit nginx01 --run-id remote-one-01 --idempotence
```

Remote không chạy sudo hoặc audit NGINX trên controller. Chỉ dùng các EC2 lab riêng.
Remote hỗ trợ `audit`, `remediate`, `run`, `--section` và `--idempotence` (với run).
`--limit` là danh sách alias chính xác; mỗi run ID giữ cùng tập host/inventory/code/scope.
Các tệp `evidence/<run-id>/summary.json`, `comparison.csv`, `hosts.csv` tổng hợp kết quả và lỗi theo host.
Xem [hướng dẫn đầy đủ, đầu ra và phân công](docs/REMOTE.md).

## Mã trả về và trạng thái

- `0`: audit trong phạm vi đều PASS / tác vụ hoàn tất.
- `1`: còn FAIL, REVIEW hoặc lần chạy lại chưa lũy đẳng.
- `2`: lỗi thu thập, quyền, thực thi hoặc dữ liệu.
- PASS/FAIL đánh giá tiêu chí; ERROR là phép kiểm tra không thực hiện được; REVIEW cần ngữ cảnh.
- `failed=0` của Ansible không phải kết luận 30/30 PASS.
- Baseline ERROR dừng trước thay đổi. Remediation lỗi vẫn có post-audit chẩn đoán và mã lỗi thực thi.

## Bằng chứng

```text
evidence/<run-id>/<hostname>/
  manifest.json                 # commit, host, scope, thời điểm, hash vars
  before/                       # audit.json, audit-summary.csv, audit-report.txt, raw/
  remediate.log
  after/
  idempotence.log               # khi chọn --idempotence
  after-idempotence/
  ansible-recap.json
  summary.json                  # so sánh trước/sau và mã trả về từng giai đoạn
```

Snapshot chứa cấu hình máy; kiểm tra trước khi chia sẻ. Không có TLS private key trong evidence.
Backup cấu hình nằm ở `/var/backups/nginx-cis/<run-id>/etc-nginx.tar.gz`. Backup này không khôi phục gói, tài khoản, dịch vụ hoặc toàn bộ VM; xem [demo và baseline](docs/DEMO.md).
`examples/legacy-evidence/` là kết quả cũ từ main d296bef, không phải bằng chứng chạy code mới.

## 30 tiêu chí đã chọn

| Nhóm | CIS ID | Số lượng |
|---|---|---:|
| Installation | 1.1.1, 1.2.1, 1.2.2 | 3 |
| Basic Configuration | 2.1.1, 2.2.1–2.2.3, 2.3.1–2.3.3, 2.4.1–2.4.4, 2.5.1–2.5.3 | 14 |
| Logging | 3.1–3.3 | 3 |
| TLS | 4.1.1, 4.1.3–4.1.6 | 5 |
| Request Controls / Headers | 5.2.1–5.2.3, 5.3.1, 5.3.3 | 5 |

Xem [luồng xử lý](docs/ARCHITECTURE.md), [mô hình và bảng thành phần](docs/MODEL.md), [Manual](docs/MANUAL.md), [demo](docs/DEMO.md) và [Remote](docs/REMOTE.md).
Điều kiện được đối chiếu bản PDF CIS NGINX v3.0.0 của nhóm; nhãn Manual trong benchmark không phải tên hình thức chạy của repo.

## Phân công bốn thành viên

| Vai trò | Mã nguồn chính | Đầu ra báo cáo |
|---|---|---|
| TV1 | Section 1–2 | 17 tiêu chí; phiên bản, tài khoản, quyền và cấu hình cơ bản |
| TV2 | Section 3–4 | 8 tiêu chí; log, TLS và phép kiểm chứng |
| TV3 | Section 5, audit engine | 5 tiêu chí, cơ chế đánh giá 30 tiêu chí và bảng Manual |
| TV4 | runner, profile, template chung, inventory, callback | Tích hợp, evidence, inventory và điều phối Remote |

Mỗi section có chủ trì; sửa template/profile dùng chung cần kiểm tra chéo với các chủ section. Bốn EC2 đều nhận đủ 30 tiêu chí. Mẫu inventory chưa có IP; nhóm tự chuẩn bị và kết nối máy.

## Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest -q
python -m compileall -q audit scripts callback_plugins
bash -n audit/baseline-audit.sh audit/post-hardening-audit.sh
ansible-playbook site.yml --syntax-check
ansible-playbook -i inventory/hosts-aws.yml playbooks/remote-audit.yml --syntax-check
ansible-playbook -i inventory/hosts-aws.yml playbooks/remote-remediate.yml --syntax-check
```

GitHub Actions có kiểm thử SSH thật tới một runner dùng một lần và kiểm tra host unreachable; không phải minh chứng EC2. Ngoài ra có regression tests và ma trận Ubuntu 24.04/26.04 chạy full workflow cùng idempotence, upload evidence kể cả khi thất bại.
Trạng thái workflow/artefact thực tế mới xác nhận lượt CI thành công; file workflow không phải bằng chứng đã chạy.
Tests dùng fixture HTTP/config không được dùng làm kết quả tuân thủ của VM/EC2.

## Nguồn tham khảo

- Tài liệu CIS NGINX Benchmark v3.0.0 do nhóm cung cấp; không phân phối PDF trong repo.
- https://nginx.org/en/linux_packages.html
- https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_handlers.html
- https://code.visualstudio.com/docs/remote/ssh
- Repo Kundanlyl/nginx-cis-hardening-ansible: tham khảo tổ chức và website; không sao chép nguyên repository.
