# Mô hình triển khai

Windows VS Code → SSH → VM Ubuntu26.04 VMware (controller và Local lab).
VM → SSH → bốn EC2 Ubuntu24.04 (Remote managed nodes).
Manual và Local sửa NGINX trên VM; Remote sửa NGINX trên từng EC2.
Controller nhận module results rồi ghi evidence bằng user thường; target cần become root.

| Thành phần | Địa chỉ | Công cụ | Trách nhiệm |
|---|---|---|---|
|Windows|[điền thật]|VS Code + Remote SSH, OpenSSH|Terminal điều khiển VM|
|VM|[IP ens33 thực tế]|Python3, venv/Ansible, Git, SSH client/server, NGINX, curl/OpenSSL|Manual/Local và Remote controller|
|nginx01|[public/private IP]|Ubuntu24.04, Python3, SSH, sudo, NGINX, công cụaudit|EC2 người1|
|nginx02|[public/private IP]|Như nginx01|EC2 người2|
|nginx03|[public/private IP]|Như nginx01|EC2 người3|
|nginx04|[public/private IP]|Như nginx01|EC2 người4|

Điền VERSION_ID, hostname, subnet/route, user, điều kiệnsudo, phiênbảncôngcụ trước nghiệmthu.
Không giả định private IP giữa các VPC có thể truy cập trực tiếp.
