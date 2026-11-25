# Remote bằng Ansible

Thực hiện trên terminal VM controller trong VS Code. Windows → SSH → VM → SSH → bốn EC2.
Không SSH thủ công vào từng EC2 để chạy bộ audit: các task audit chạy tại EC2 qua Ansible,
module trả dữ liệu về controller, task delegate_to localhost ghi JSON/CSV tại VM. Không cần
fetch collector Python nữa vì không có collector riêng.

## Mỗi thành viên chuẩn bị một EC2

Ubuntu 24.04 LTS, một máy lab riêng cho NGINX, Python3 và công cụ nêu trong README.
Ghi VERSION_ID, hostname, public/private IP, user, key path trên VM và điều kiện sudo.
Chuẩn bị baseline phục hồi được. Điền thông tin thật vào Bảng 3.1 của báo cáo, không đoán IP.
Security Group SSH phải cho phép nguồn kết nối thực tế từ VM; private IP chỉ dùng khi có đường mạng.

```bash
cp inventory/hosts-aws.example.yml inventory/hosts-aws.local.yml
code inventory/hosts-aws.local.yml
```

Điền `ansible_host` cho nginx01–04, user và key path đúng. Các tên host website đã có mẫu.
Chỉ máy thật của nhóm được dùng cho evidence nghiệm thu. Xác minh host key trước khi chấp nhận,
giữ host_key_checking bật. Khóa riêng ở VM, không nằm trong repo.

```bash
ssh -i ~/.ssh/YOUR_KEY.pem ubuntu@YOUR_EC2_IP
# Trong EC2: whoami; hostname; cat /etc/os-release; sudo -l; rồi exit
ansible-inventory -i inventory/hosts-aws.local.yml --graph
ansible -i inventory/hosts-aws.local.yml nginx_servers -m ansible.builtin.ping
ansible -i inventory/hosts-aws.local.yml nginx_servers -b -m ansible.builtin.command -a 'id -u'
# Thêm -K khi tài khoản trên EC2 cần mật khẩu sudo; kết quả nâng quyền mong đợi: 0.
```

## Thử một host rồi nghiệm thu bốn host

Dùng `--limit nginx01` chọn thử một host; giữ đúng limit cho cả ba lệnh tách của lượt đó.
Không dùng lại run ID của lượt một host cho lượt bốn host. Lượt nghiệm thu phải đủ30 mỗi máy.
Ví dụ dưới là MỘT chu trình tách lệnh trên bốn host:

```bash
CIS_RUN_ID=remote-ansible-01
ansible-playbook -i inventory/hosts-aws.local.yml playbooks/remote.yml \
  -e cis_action=audit -e cis_audit_stage=before -e cis_run_id="$CIS_RUN_ID"
cat "evidence/$CIS_RUN_ID/hosts.csv"
cat "evidence/$CIS_RUN_ID/nginx01/before/audit-summary.csv"
```

Xem before cho từng host. Chỉ khi quyết định áp dụng cấu hình:

```bash
ansible-playbook -i inventory/hosts-aws.local.yml playbooks/remote.yml \
  -e cis_action=remediate -e cis_run_id="$CIS_RUN_ID"
ansible-playbook -i inventory/hosts-aws.local.yml playbooks/remote.yml \
  -e cis_action=audit -e cis_audit_stage=after -e cis_run_id="$CIS_RUN_ID"
cat "evidence/$CIS_RUN_ID/comparison.csv"
cat "evidence/$CIS_RUN_ID/hosts.csv"
```

Nếu cần `-K`, thêm vào từng lần gọi. Mỗi host cần cùng run ID/scope/vars/code. Before ERROR chặn
remediation; host unreachable có summary ERROR, không tạo kết quả tuân thủ giả. Các host còn lại
tiếp tục. Kết quả phải đủ 120 cặp host-tiêu chí cho mỗi giai đoạn mới công bố hoàn thành cả bốn.

Cách thay thế: khôi phục baseline và dùng run ID mới, chạy `cis_action=run -e cis_idempotence=true`
để thực hiện trọn chu trình không chờ duyệt. Không chạy thêm lệnh tách cho cùng lượt run.

Ảnh cần bổ sung, hiện để trống: inventory đã che key, kết nối/sudo đủ4host, before, remediation,
after/comparison, idempotence nếu có, tổng hợp4host. Không dùng ảnh CI làm ảnh EC2 của nhóm.
