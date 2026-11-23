# Remote Automated — để nhóm bổ sung sau

Remote **chưa được triển khai hoặc kiểm thử** trong phiên bản này.
`./cisctl ... --mode remote` trả mã lỗi 2 trước khi tác động hệ thống.
`site.yml` cũng kiểm tra `ansible_connection == local` để ngăn vô tình chạy role hiện tại lên EC2.

## Mô hình dự kiến

Windows chạy VS Code Remote SSH → VM Ubuntu Server 26.04 trên VMware làm controller → SSH tới nginx01–nginx04 trên EC2 Ubuntu Server 24.04 LTS. Nhóm cần xác nhận VERSION_ID trên từng EC2; không coi mọi bản 24.xx là tương đương.
Không cần tạo EC2 thứ năm làm controller. VS Code chỉ là giao diện; Ansible chạy trên VM.

## Thông tin nhóm cần điền

| Host | Thành viên | Public IP/DNS | Private IP | SSH user | Tên website | Region/VPC |
|---|---|---|---|---|---|---|
| nginx01 | ... | ... | ... | ubuntu | ... | ... |
| nginx02 | ... | ... | ... | ubuntu | ... | ... |
| nginx03 | ... | ... | ... | ubuntu | ... | ... |
| nginx04 | ... | ... | ... | ubuntu | ... | ... |

Điền `inventory/hosts-aws.yml` sau khi có thông tin; khóa SSH để trên VM, không commit.
Security Group cho phép SSH từ IP public đường ra của controller; HTTP/HTTPS từ nơi thử nghiệm.
Các máy khác tài khoản/VPC có thể dùng địa chỉ public nếu kết nối được; không mặc định private IP của các VPC độc lập thông nhau.

## Các phần mã nguồn cần bổ sung trước khi chạy

1. Tạo playbook remote riêng và thay điều kiện local bằng điều kiện đích phù hợp; không bỏ chốt local khỏi bản hiện tại trước khi có kiểm thử.
2. Lưu biến hostname, địa chỉ và TLS theo host. Một EC2 chạy đủ 30 tiêu chí, không chỉ section của chủ máy.
3. Chuyển `audit/collect.py` và `audit/engine.py` lên từng host, gọi với become. Các lệnh nginx/stat/passwd/ss phải chạy tại EC2.
4. Dùng fetch để thu `audit.json`, CSV, TXT và raw snapshots về VM theo run ID/hostname/stage; giữ riêng lỗi unreachable.
5. Thêm inventory/limit vào bộ điều phối thay vì chạy script audit của controller để suy ra trạng thái EC2.
6. Kiểm thử một host, sau đó bốn host; xử lý lỗi và báo cáo 120 cặp host–tiêu chí mỗi giai đoạn.
7. Bổ sung test remote và bằng chứng thực tế rồi mới gỡ trạng thái placeholder.

## Những lệnh chỉ dùng để kiểm tra kết nối sau khi điền inventory

```bash
ansible-inventory -i inventory/hosts-aws.yml --graph
ansible -i inventory/hosts-aws.yml nginx_servers -m ping
```

Ping thành công chưa chứng minh đủ quyền sudo, NGINX hoặc 30 tiêu chí đạt. Chưa có lệnh triển khai remote hoàn chỉnh trong repo này.
