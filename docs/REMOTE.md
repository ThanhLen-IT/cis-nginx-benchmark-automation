# Remote Automated — mã nguồn đã có, nhóm thực nghiệm trên EC2

Controller là VM Ubuntu Server 26.04 trên VMware; bốn managed nodes là EC2 Ubuntu Server 24.04 LTS. Windows dùng VS Code Remote SSH để vào VM. Không cần EC2 thứ năm.

Remote dùng cùng 30 tiêu chí, engine và role với Local. Mã điều phối, playbook chuyển audit/fetch, xử lý lỗi và tổng hợp đã được triển khai. **Kết quả kiểm thử code/CI không phải minh chứng VMware/EC2 của nhóm.** IP, khóa SSH, kết nối, baseline, kết quả và video thực tế do nhóm thực hiện.

## 1. Phần đã viết và phần nhóm tự làm

| Thành phần | Đã có trong repo | Nhóm thực hiện |
|---|---|---|
| `scripts/remote.py` | Chọn host; khóa chạy đồng thời; run ID; chuỗi before/remediate/after; kiểm tra lũy đẳng; summary | Chạy trên controller và đọc log |
| `playbooks/remote-audit.yml` | Chuyển collect/engine lên EC2; chạy với become; fetch JSON/CSV/TXT/raw | Xác nhận SSH, Python và sudo trên từng EC2 |
| `playbooks/remote-remediate.yml` | Dùng role chung qua SSH, validate trước reload | Chuẩn bị EC2 lab riêng và baseline |
| `inventory/hosts-aws.example.yml` | Mẫu bốn EC2 với biến website riêng | Điền IP/DNS, user, đường dẫn khóa, private IP nếu dùng |
| Báo cáo tổng hợp | `summary.json`, `comparison.csv`, `hosts.csv` | Đối chiếu, chụp ảnh, điền báo cáo và quay demo |

Role sở hữu toàn bộ nginx.conf và website lab; dùng máy lab riêng. Backup cấu hình không phải khôi phục toàn bộ gói/tài khoản/dịch vụ. Không có code tạo EC2, thiết lập VPC/Security Group hoặc cấp chứng chỉ công khai.

## 2. Chuẩn bị kết nối thực tế — nhóm làm

Mỗi người cung cấp một EC2: VERSION_ID, hostname, region/VPC, public/private IP, SSH user và quyền sudo. Xác nhận Ubuntu 24.04 LTS thay vì suy ra từ tên 24.xx.

Trên controller, kích hoạt venv đã cài requirements. Tạo bản inventory cục bộ:

```bash
. .venv/bin/activate
cp inventory/hosts-aws.example.yml inventory/hosts-aws.local.yml
code inventory/hosts-aws.local.yml
```

Nếu không có lệnh `code`, mở tệp bằng Explorer của VS Code đã kết nối VM. Điền `ansible_host` cho đủ bốn máy. Khóa có thể khác nhau: khai báo `ansible_ssh_private_key_file` trong từng host, hoặc dùng ssh-agent/SSH config. Đường dẫn khóa phải thuộc VM controller, không phải ổ D: của Windows. Tệp `.local.yml` đã được gitignore. Không commit khóa hoặc mật khẩu.

Các tên `nginx01.cis.local` trong mẫu là tên website lab. Audit chạy tại EC2 và thử dịch vụ trên loopback với Host/SNI phù hợp; không cần DNS public để chạy audit. Nếu muốn kiểm thử từ trình duyệt ngoài, dùng DNS/hosts và điều kiện truy cập phù hợp. `nginx_cis_private_ip` mặc định là loopback cho lab; có thể điền private IP thực tế cho SAN của chứng chỉ. Chứng chỉ self-signed không được xem là chứng chỉ công khai tin cậy.

Cho phép SSH từ địa chỉ nguồn thực tế của controller. VM NAT thường đi Internet qua public IP của mạng đang dùng; private IP của VM không phải nguồn mà Security Group nhìn thấy. Không mặc định private IP ở các VPC độc lập kết nối được.

Kết nối SSH từng EC2 một lần và đối chiếu fingerprint trước khi chấp nhận host key. Runner giữ host key checking bật. Ví dụ, tự thay giá trị thật:

```bash
ssh -i /home/YOUR_VM_USER/.ssh/YOUR_KEY.pem ubuntu@YOUR_EC2_IP
# Chạy tại EC2:
cat /etc/os-release
hostname
python3 --version
sudo -n id -u
exit
```

Nếu máy yêu cầu mật khẩu sudo, dùng `--ask-become-pass` trong các lệnh cisctl; Ansible có thể hỏi lại ở từng giai đoạn/host. EC2 dùng sudo không cần mật khẩu thì không cần tùy chọn này.

Kiểm tra bằng inventory, từ VM:

```bash
ansible-inventory -i inventory/hosts-aws.local.yml --graph
ansible -i inventory/hosts-aws.local.yml nginx_servers -m ping
ansible -i inventory/hosts-aws.local.yml nginx_servers --become -m command -a 'id -u'
```

Đầu ra `0` của `id -u` xác nhận nâng quyền root. Ping thành công chưa chứng minh tiêu chí CIS đạt. Các công cụ audit Python, curl, OpenSSL, ss, apt-cache phải sẵn có trên đích; kiểm tra/cài như điều kiện chuẩn bị. Section 1 trong lượt đầy đủ có thể cài hoặc nâng cấp NGINX; section 2–5 chạy riêng cần NGINX sẵn có.

## 3. Thử một EC2, sau đó cả bốn

Đọc code và lệnh sau trong terminal **VM controller**. Các lệnh Linux do playbook gọi sẽ thực thi trên EC2 qua SSH. Runner không cần sudo trên controller.

Lượt đầu kiểm thử riêng một máy:

```bash
./cisctl run --mode remote \
  --inventory inventory/hosts-aws.local.yml --limit nginx01 \
  --section all --run-id remote-one-01 --idempotence
```

Kiểm tra summary và đối chiếu before/after. Nếu cần quay lại hiệu quả khắc phục, khôi phục baseline trước khi chạy lại và dùng ID mới.

Lượt nghiệm thu đủ bốn máy, dùng **run ID khác** vì tập host khác:

```bash
./cisctl run --mode remote \
  --inventory inventory/hosts-aws.local.yml \
  --section all --run-id remote-four-01 --idempotence
```

Không có `--limit` thì chạy tất cả thành viên của nhóm `nginx_servers`. `--limit` nhận alias chính xác hoặc danh sách phân cách bằng dấu phẩy, ví dụ `nginx01,nginx03`; không nhận pattern Ansible như `all:!nginx04`. Mặc định xử lý lần lượt từng host, mỗi host hoàn thành hoặc được ghi lỗi rồi mới sang host tiếp theo.

Có thể rà một section bằng `--section 1` đến `5`; lượt nghiệm thu cuối dùng `all`. Section/profile có tính tích lũy giống Local. Không tự thay ngưỡng audit để ép PASS.

## 4. Cách tách audit / remediation / re-audit

Đây là giao diện thay thế cho `run`, không chạy thêm khi minh họa cùng một ví dụ đã dùng `run`:

```bash
./cisctl audit --mode remote --inventory inventory/hosts-aws.local.yml \
  --run-id remote-split-01 --stage before --section all
# Đọc báo cáo. Exit 1 (FAIL/REVIEW) là baseline hợp lệ; không nối bằng &&.
./cisctl remediate --mode remote --inventory inventory/hosts-aws.local.yml \
  --run-id remote-split-01 --section all
./cisctl audit --mode remote --inventory inventory/hosts-aws.local.yml \
  --run-id remote-split-01 --stage after --section all
```

Remote `remediate` yêu cầu có before hợp lệ cùng run ID/host/scope; host có ERROR hoặc chưa audit sẽ không được sửa. `--idempotence` chỉ áp dụng với `run`.

Cùng run ID phải giữ nguyên inventory, tập host, code, section và vars-file. Đã có evidence hoặc log của một giai đoạn thì không chạy đè. Khi lỗi kết nối hoặc fetch, giữ hồ sơ lỗi, sửa nguyên nhân và dùng ID mới; không ghép before của máy cũ vào EC2 vừa tạo lại.

## 5. Chương trình làm gì sau Enter?

1. Đọc inventory qua `ansible-inventory --list`, chọn đúng nhóm và alias; từ chối inventory rỗng, placeholder, loopback hoặc connection local. Kiểm tra trùng endpoint, run ID và khóa đồng thời.
2. Tạo manifest chứa commit/source hash, scope, host và hash đầu vào; không ghi toàn bộ inventory hoặc mật khẩu.
3. Với từng host, playbook audit thu facts, kiểm tra Ubuntu/SSH/sudo; chuyển `collect.py` và `engine.py` vào thư mục root riêng trên EC2.
4. Collector chạy tại EC2; thu cấu hình/phiên bản/cổng/package rồi engine đánh giá. Playbook giữ mã trả về thật và fetch cả raw/JSON/CSV/TXT về đúng alias. Runner xác minh đủ CIS ID, Status, scope, counts và mã trả về trước khi quyết định.
5. Before có FAIL/REVIEW vẫn khắc phục; ERROR hoặc lỗi thu thập thì dừng host đó. Ansible áp dụng trạng thái khai báo trong scope/profile, không đọc CSV để chỉ chọn task FAIL.
6. Role tạo backup, render candidate và kiểm tra `nginx -t` trước khi cài/reload. Khi remediation lỗi, vẫn thử audit sau để chẩn đoán; tổng kết giữ mã lỗi thực thi.
7. Re-audit dùng cùng engine/scope. Với `--idempotence`, remediation lần hai có recap riêng và audit thêm, kể cả khi changed > 0. Chỉ ổn định khi changed/failures/unreachable đều 0 và vẫn phải xem kết quả audit.
8. Thu summary từng host rồi ma trận chung. Host lỗi vẫn hiện trong `hosts.csv` và `missing_hosts`; không tạo giả 30 dòng PASS/FAIL/ERROR cho host chưa chạy collector.

## 6. Đầu ra thực tế cần bàn giao

Đường dẫn được in trên terminal:

```text
evidence/<run-id>/
  manifest.json
  summary.json                 # tổng hợp tất cả host, expected và missing
  comparison.csv               # Host, CIS_ID, Before_Status, After_Status
  hosts.csv                    # Host, Target_Hostname, Exit_Code, Execution_Error
  nginx01/                     # alias inventory, không suy ra từ tên controller
    manifest.json
    before/                    # audit.json, CSV, TXT, raw/, collector-result.json
    before.log
    before-recap.json
    remediate.log
    remediate-recap.json
    after/
    after.log
    after-recap.json
    idempotence.log            # khi chọn --idempotence
    idempotence-recap.json
    after-idempotence/
    after-idempotence.log
    after-idempotence-recap.json
    summary.json
  nginx02/ ...
```

Bản gốc audit nằm tại EC2 ở `/var/lib/nginx-cis/evidence/<run-id>/`. Backup cấu hình ở `/var/backups/nginx-cis/<run-id>/`. Không thu TLS private key vào evidence. Snapshot cấu hình có thể chứa thông tin môi trường, cần rà trước khi chia sẻ.

Đọc kết quả từ controller:

```bash
cat evidence/remote-four-01/summary.json
cat evidence/remote-four-01/hosts.csv
cat evidence/remote-four-01/comparison.csv
cat evidence/remote-four-01/nginx01/before/audit-summary.csv
cat evidence/remote-four-01/nginx01/after/audit-summary.csv
cat evidence/remote-four-01/nginx01/idempotence-recap.json
```

Exit code: `0` thành công/đạt trong phạm vi; `1` còn FAIL/REVIEW hoặc chưa lũy đẳng; `2` có ERROR/lỗi thực thi. Một host lỗi khiến tổng lượt trả 2, các host khác vẫn được thực hiện. Counts chỉ cộng kết quả thực thu, luôn xem cả `missing_hosts`; không báo 90/90 như thể đã kiểm tra đủ 120 cặp.

## 7. Chia việc và nghiệm thu

| Vai trò | Phần code đã có cần hiểu/kiểm tra | Công việc thực tế và bàn giao |
|---|---|---|
| TV1 — nginx01 | Section 1–2, 17 tiêu chí | Điền máy; phối hợp lượt thử một EC2; giải thích package/account/permissions/config; log và nhận xét |
| TV2 — nginx02 | Section 3–4, 8 tiêu chí | Điền máy; kiểm chứng access/error log, redirect, key permissions, TLS handshake |
| TV3 — nginx03 | Section 5 và engine | Điền máy; kiểm tra phép đánh giá, Status và header 200/404; đối chiếu đủ 30 ID |
| TV4 — nginx04/controller | Runner, remote playbooks, manifest/fetch/summary | Điền máy; gom inventory; chạy đúng cùng commit; tổng hợp bốn host, ảnh, báo cáo và video |

Mỗi EC2 chạy đủ 30 tiêu chí. Không yêu cầu nhóm viết lại adapter; nếu kiểm thử thực tế phát hiện lỗi thì giữ log để sửa. Trước nghiệm thu kiểm tra: bốn host đúng máy; 30 dòng before và after mỗi host hoặc lỗi được nêu rõ; re-audit độc lập với recap; lần chạy lại có số liệu thật; ảnh có hostname/run ID; kết quả khớp commit và baseline.

## 8. Phạm vi kiểm thử

`tests/test_remote.py` kiểm tra lựa chọn host, dữ liệu hỏng/thiếu, lỗi từng host, bốn host, bất biến evidence, split commands và idempotence bằng dữ liệu mô phỏng. `.github/workflows/remote.yml` chạy chuỗi SSH thật tới một runner CI dùng một lần và kiểm tra host không kết nối được. Đây không phải bốn EC2 hoặc VMware của nhóm. Theo dõi kết quả CI trên PR/Actions, không xem sự tồn tại của workflow là bằng chứng đã chạy thành công.
