# cis-nginx-benchmark-automation
Automated NGINX security hardening based on CIS Benchmark using Ansible and Terraform (CIS NGINX Benchmark v3.0.0).

## Cấu trúc thư mục dự án

```text
cis-nginx-benchmark-automation/
├── README.md
├── LICENSE
├── ansible.cfg
├── site.yml
├── inventory/
│   ├── hosts.yml
│   └── hosts-aws.yml
├── audit/
│   ├── baseline-audit.sh
│   └── post-hardening-audit.sh
├── evidence/
│   ├── before/
│   └── after/
└── roles/
    └── nginx_cis/
        ├── defaults/
        │   └── main.yml
        ├── files/
        ├── handlers/
        │   └── main.yml
        ├── tasks/
        │   ├── main.yml
        │   ├── deploy_site.yml
        │   ├── section_1_installation.yml
        │   ├── section_2_configuration.yml
        │   ├── section_3_logging.yml
        │   ├── section_4_tls.yml
        │   └── section_5_request_controls.yml
        └── templates/
            ├── cis-connection-timeouts.conf.j2
            ├── cis-default-server.conf.j2
            ├── cis-deny-hidden.conf.j2
            ├── cis-logging.conf.j2
            ├── cis-request-controls.conf.j2
            ├── cis-security-headers.conf.j2
            ├── enterprise-site.conf.j2
            ├── enterprise-site-tls.conf.j2
            └── hardened-site.conf.j2
```

## Phân chia nhánh & file giữa các thành viên

| Thành viên | Branch | File chịu trách nhiệm chính | Nhóm tiêu chí CIS (Tổng 30) |
| :--- | :--- | :--- | :--- |
| **TV1** | `feature/configuration` | `section_1_installation.yml`, `section_2_configuration.yml` | Installation (`1.1.1`, `1.2.1`, `1.2.2`) + Configuration (`2.1.1`, `2.2.1–2.2.3`, `2.3.1–2.3.3`, `2.4.1–2.4.4`, `2.5.1–2.5.3`) — **17 tiêu chí** |
| **TV2** | `feature/logging-tls` | `section_3_logging.yml`, `section_4_tls.yml` | Logging (`3.1–3.3`) + SSL/TLS (`4.1.1`, `4.1.3–4.1.6`) — **8 tiêu chí** |
| **TV3** | `feature/audit-headers` | `section_5_request_controls.yml`, `audit/`, bộ kiểm tra 30 tiêu chí | Request Controls / Headers (`5.2.1–5.2.3`, `5.3.1`, `5.3.3`) — **5 tiêu chí** + Script Audit |
| **TV4** | `feature/aws-remote` | `inventory/hosts-aws.yml`, hướng dẫn AWS, tích hợp & báo cáo | Remote Automated & Tích hợp hệ thống |

## Quy trình làm việc với Git

```bash
# 1. Clone hoặc cập nhật nhánh main mới nhất
git checkout main
git pull origin main

# 2. Tạo nhánh riêng theo phân công
git checkout -b <ten-branch-cua-ban>

# 3. Kiểm tra cú pháp Ansible trước khi commit
ansible-playbook site.yml --syntax-check

# 4. Commit & push nhánh lên remote để tạo Pull Request vào main
git add .
git commit -m "feat: implement assigned section"
git push -u origin <ten-branch-cua-ban>
```
