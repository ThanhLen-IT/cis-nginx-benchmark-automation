# Bốn thành viên và quay demo

| Người | Phần chịu trách nhiệm | EC2 |
|---|---|---|
|1|Section1–2: task audit ở vars/catalog, dữ liệu account/package/find, role khắc phục|nginx01|
|2|Section3–4: task logging/TLS, probe thật và điều kiện JSON|nginx02|
|3|Manual5 tiêu chí, ví dụ5.3.3; Section5 audit/headers; tổng hợp Local|nginx03|
|4 (bạn)|inventory/SSH/sudo, Ansible workflow, báo cáo Remote và tổng hợp|nginx04|

Mỗi người tự chuẩn bị EC2/baseline; mỗi EC2 được kiểm tra đầy đủ30, không chia phạm vi theo người.
Dùng cùng commit đã tích hợp. VMcontroller VMware26.04, EC2Ubuntu24.04; điền thông tin thật.

1. Mở mô hình và bảng thành phần; đọc hostname/commit để biết đang thao tác máy nào.
2. Manual một ví dụ5.3.3: before → sửa bằng lệnh → nginx -t/reload → after, giữ minh chứng200/404.
3. Local: một chu trình tách audit/remediate/audit hoặc một run, không làm hai ví dụ nối tiếp
   trên trạng thái đã sửa rồi gọi đó là baseline chưa harden.
4. Nếu minh chứng lũy đẳng, dùng run có cis_idempotence=true. Đọc idempotence.json và
   after-idempotence/audit-summary.csv; PLAY RECAP chung bao gồm ghi evidence nên changed có thể >0.
5. Remote: inventory+sudo từnghost, auditbefore, quyết địnhremediation, auditafter, comparison.csv4host.
6. Kết luận bằng JSON/CSV thật, ghi FAIL/ERROR/REVIEW nếu có, không chỉnh thành PASS.

Các khung hình còn thiếu để trống. Evidence cũ dùng Python/cisctl phải giữ nguyên như lịch sử,
không đổi tên thành evidence Ansible-native. Quay lại ví dụ theo code mới và run ID mới sau khi
khôi phục baseline. Không xóa VM hay toàn bộ home để chuyển phiên bản.
