# Quay demo và lấy kết quả cho báo cáo

## Một lần chạy tích hợp

1. Mở VS Code Remote SSH vào VM. Hiển thị `hostname`, `git rev-parse HEAD`, inventory local và phiên bản.
2. Chạy `./cisctl run --ask-become-pass --idempotence` từ repo. Giải thích script thu dữ liệu, đánh giá, Ansible đưa hệ thống về trạng thái mong muốn, validate/reload rồi audit lại.
3. Mở `manifest.json`, `before/audit.json`, `remediate.log`, `after/audit.json`, `idempotence.log`, `after-idempotence/audit.json` và `summary.json` trong thư mục lần chạy được in trên terminal.
4. Đối chiếu trạng thái trước/sau, `nginx -t`, HTTP 200/404, redirect và TLS handshake. Chỉ kết luận theo kết quả thực đo.

## Quay theo section

Chạy `./cisctl run --section 3 --ask-become-pass` để tập trung Logging. Section 2–5 cần NGINX đã được cài; nếu thiếu, chạy Section 1 trước.
Phần cấu hình chung luôn được biên dịch lại để không làm mất các section đã bật. `/var/lib/nginx-cis/profile.json` lưu danh sách đó; vì vậy lượt section sau có thể bao gồm tác vụ duy trì trạng thái đã bật trước.
Chỉ lượt `--section all` đánh giá đủ 30 tiêu chí.

## Baseline và quay lại

Dùng snapshot VM hoặc môi trường lab có trạng thái gốc đã xác định để quay lại “before”. Backup `/etc/nginx` trong repo không hoàn tác phiên bản gói, tài khoản, systemd hoặc các thư mục ngoài cây cấu hình.
Không xóa profile và gọi đó là rollback đầy đủ. Không có lệnh reset phá hủy tự động.
Mỗi lần chạy mới dùng run ID mới; tệp stage có sẵn bị từ chối ghi đè.

## Phân công

| Vai trò | Đoạn quay và bàn giao |
|---|---|
| TV1 | Installation/Configuration, 17 tiêu chí, giải thích dữ liệu gói và quyền |
| TV2 | Logging/TLS, 8 tiêu chí, log và handshake |
| TV3 | Manual, Headers và cơ chế audit 30 tiêu chí |
| TV4 | Luồng tổng, evidence, tích hợp báo cáo; điều phối lượt Remote |

Remote có mã và lệnh trong docs/REMOTE.md; nhóm điền IP, chuẩn bị baseline và kiểm thử trước khi quay. Không dùng hình cũ hai node để đại diện cho bốn EC2 chưa kiểm thử.
Giữ video gốc, log, commit, hostname và thời điểm chạy; thỏa thuận thời lượng/thuyết minh theo yêu cầu giảng viên.

## Lượt Remote khi bốn EC2 đã sẵn sàng

TV4 mở inventory và xác định đúng bốn máy, chạy `./cisctl run --mode remote --inventory inventory/hosts-aws.local.yml --run-id remote-demo-01 --idempotence`. Hiển thị từng host before/remediate/after và recap lần hai; mở summary.json, hosts.csv, comparison.csv. Mỗi thành viên giải thích dữ liệu thuộc phần mình trên cùng lượt chạy. Giữ nguyên lỗi nếu có, không coi host mất kết nối là đã đánh giá 30 tiêu chí. Xem hướng dẫn baseline và điều kiện kết nối trong REMOTE.md.
