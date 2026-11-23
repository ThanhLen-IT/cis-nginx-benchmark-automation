# Luồng chương trình và cách viết chương 2

`cisctl` gọi `scripts/runner.py`. Bộ điều phối nhận action, section và run ID; khóa các lần chạy local đồng thời, tạo manifest và kiểm tra quyền sudo.

## Audit

`audit/collect.py` chạy read-only tại máy đích, thu `nginx -V`, `nginx -T`, `ss`, `apt-cache policy`. Cả stdout, stderr và exit code được lưu trong raw/.
`audit/engine.py` dùng Python chuẩn: bỏ comment, phân tích block/directive và include; đọc quyền/tài khoản, so sánh timeout/dung lượng và thử HTTP/TLS. Trạng thái theo từng CIS ID được xuất JSON, CSV, TXT.
Before và after dùng cùng engine. Cấu hình không đọc được không biến thành PASS nhờ giá trị mặc định. Header cần có ở phản hồi đúng 200/404; TLS cần có handshake TLS 1.3 và từ chối TLS 1.2.
Các kiểm tra HTTP nhắm tới website lab được chọn; repo không phải bộ kiểm toán tổng quát mọi kiến trúc proxy/load balancer. Cipher TLS 1.3 và DH được đánh giá theo cấu hình TLS 1.3-only trong tài liệu benchmark được nhóm cung cấp.

## Remediation

`site.yml` gọi role. Preflight kiểm tra Ubuntu 24.04 hoặc 26.04/local và nạp profile. Section 1 chọn codename theo facts (noble/resolute), cấu hình nguồn gói chính thức và nâng cấp NGINX; section 2 quản lý tài khoản/quyền; section 3 log; section 4 vật liệu TLS; section 5 kiểm tra policy request.
Template `nginx.conf.j2` là nguồn cấu hình duy nhất được nạp; không include cấu hình website cũ để tránh directive xung đột. Các tệp cũ được giữ và backup, nhưng không còn được include bởi cấu hình lab mới.
Role render candidate, chạy `nginx -t -c ...` rồi mới copy vào nginx.conf. Hai handler cùng listen một sự kiện: validate chạy trước reload. Profile chỉ được ghi sau triển khai thành công.
Ansible không đọc CSV để chỉ chạy các dòng FAIL. Module so sánh trạng thái hệ thống với khai báo trong phạm vi/profile đã chọn.

## Điều phối lỗi

`run`: audit before → remediation → audit after → tùy chọn chạy lại remediation và audit lần nữa.
Baseline FAIL cho phép khắc phục; baseline ERROR dừng trước thay đổi. Nếu remediation lỗi, vẫn thử audit sau để chẩn đoán và trả mã lỗi thực thi.
Idempotence dùng số liệu thật của callback Ansible; không ép changed=0 bằng cách bỏ qua thay đổi.

## Hướng viết chương 3

Ghi lệnh → đầu ra → nhận xét theo CIS ID. Dùng cùng run ID cho before/after, ghi commit, host và scope. Các mục code/logic thuộc chương 2; bảng Manual theo docs/MANUAL.md. Không điền kết quả PASS giả hoặc dùng fixture test làm kết quả thực nghiệm.
