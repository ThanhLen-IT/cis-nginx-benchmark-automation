# Manual bằng câu lệnh — 5 tiêu chí

Thực hiện trên **VM lab có NGINX đang chạy**, qua terminal VS Code Remote SSH.
Dùng baseline sạch riêng cho Manual, không chạy sau profile Local đã hardening rồi coi đó là “before”.
Không chạy Ansible trong phương pháp Manual; người thực hiện nhập lệnh, đọc kết quả, chỉnh cấu hình và kiểm tra lại.

## Kiểm tra trước và lưu bằng chứng

```bash
mkdir -p evidence/manual-demo/before evidence/manual-demo/after
sudo nginx -T > evidence/manual-demo/before/nginx-T.txt 2>&1
curl --noproxy '*' -sSI http://127.0.0.1/ > evidence/manual-demo/before/200.txt
curl --noproxy '*' -sSI http://127.0.0.1/not-found-cis > evidence/manual-demo/before/404.txt
sudo cp -a /etc/nginx /var/backups/nginx-manual-demo
```

Tên backup phải mới cho mỗi lần thực nghiệm; nếu đã tồn tại, đặt tên khác để không ghi đè baseline.
Các lệnh dưới giả định baseline NGINX có include `/etc/nginx/conf.d/*.conf` trong context http và chưa khai báo trùng các directive ở cùng context.

## Khắc phục bằng các lệnh trực tiếp

```bash
sudo tee /etc/nginx/conf.d/manual-cis-section5.conf >/dev/null <<'CONF'
client_header_timeout 10s;
client_body_timeout 10s;
send_timeout 10s;
client_max_body_size 2M;
large_client_header_buffers 4 8k;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
CONF
sudo chown root:root /etc/nginx/conf.d/manual-cis-section5.conf
sudo chmod 0640 /etc/nginx/conf.d/manual-cis-section5.conf
sudo nginx -t && sudo systemctl reload nginx
```

Nếu `nginx -t` lỗi, sửa directive trùng/context trước khi reload. Các `add_header` ở server/location có thể làm thay đổi kế thừa; phải thử đúng website, đúng HTTP 200 và 404.

## Kiểm tra sau và bảng báo cáo

```bash
sudo nginx -T > evidence/manual-demo/after/nginx-T.txt 2>&1
curl --noproxy '*' -sSI http://127.0.0.1/ > evidence/manual-demo/after/200.txt
curl --noproxy '*' -sSI http://127.0.0.1/not-found-cis > evidence/manual-demo/after/404.txt
systemctl is-active nginx
```

| Tiêu chí | Lệnh kiểm tra trước/sau | Giá trị áp dụng | Kết quả thực đo |
|---|---|---|---|
| 5.2.1 | `sudo nginx -T` | header/body/send timeout 10s | Điền từ lần chạy |
| 5.2.2 | `sudo nginx -T` | body 2M | Điền từ lần chạy |
| 5.2.3 | `sudo nginx -T` | buffer 4 8k | Điền từ lần chạy |
| 5.3.1 | `curl -I` với 200/404 | nosniff | Điền từ lần chạy |
| 5.3.3 | `curl -I` với 200/404 | strict-origin-when-cross-origin | Điền từ lần chạy |

Đây là hướng dẫn, không phải bằng chứng rằng các lệnh đã chạy trên VM của nhóm. Đổi URL nếu website thực tế cần hostname hoặc HTTPS.
