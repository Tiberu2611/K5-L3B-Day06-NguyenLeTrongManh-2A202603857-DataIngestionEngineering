# Benchmark · 20 câu · Harry Potter Books 1–3

File: [questions.json](questions.json). Trang là **số trang vật lý của PDF** (`gold_page`), nguồn duy nhất `hp-complete-collection-pottermore`.

## Phân chia và loại câu

| Split | Số câu | Trực tiếp | Diễn đạt lại | Điều kiện | Có filter `book_no` |
|---|---:|---:|---:|---:|---:|
| dev | 15 | 5 | 6 | 1 | 3 (q13, q14, q15) |
| test | 5 | 0 | 1 | 2 | 2 (q16, q17) |

- **Chia theo chương:** 5 câu test lấy từ 5 chương không có câu dev nào (B1 ch10, B1 ch17, B2 ch16, B3 ch1, B3 ch3) để giảm rò rỉ.
- **Rủi ro rò rỉ còn lại:** q04 (dev) và q20 (test) cùng nói về Mirror of Erised nhưng khác chương, khác dữ kiện; nhân vật và địa điểm lặp lại giữa các sách.
- **Câu filter có thiết kế mơ hồ khi không lọc:** đáp án đổi theo từng sách (mật khẩu đầu năm, quà Giáng sinh ẩn danh, giáo viên Phòng chống Nghệ thuật Hắc ám, quà sinh nhật của Hagrid, cây chổi mới). Filter là **ngữ cảnh do người dùng cung cấp trước** ("tôi đang đọc cuốn N"); nó thu hẹp về cả một cuốn sách (~280–370 trang), không phải trang gold.
- **Nhiều evidence hợp lệ:** q03 (trang 72/73/132), q16 (582/583), q19 (523/524) có `alt_evidence`; chunk khớp bất kỳ evidence nào đều được tính hit.

## Kiểm chứng evidence

`python -m src.run --stage eval` gọi `verify_benchmark` trước khi truy xuất: mỗi `evidence_quote` phải nằm trong text đã chuẩn hóa của trang gold (so khớp không phân biệt hoa/thường, ngoặc cong ↔ thẳng, gạch ngang dài ↔ `-`). Kết quả lần đầu: **24/24 evidence được tìm thấy** (20 chính + 4 thay thế). Nếu thiếu, pipeline dừng.

## Tiêu chí chọn chiến lược (chốt trước khi chạy test)

1. Evidence Hit@3 cao nhất trên **dev**.
2. Hòa → Hit@1 dev cao hơn.
3. Vẫn hòa → ít chunk hơn / thời gian embed thấp hơn.

Test chỉ chạy để báo cáo sau khi đã chốt, không dùng để tinh chỉnh.

## Ghi chú trung thực

Bộ câu hỏi được soạn với hỗ trợ của AI (Claude) từ text đã chuẩn hóa, trước lần truy xuất đầu tiên. Học viên cần đọc lại từng câu, đáp án và evidence trước khi nộp.
