# Audit thủ công — phương pháp và cách duyệt

Ba bảng trong thư mục này phục vụ ba khía cạnh cần chấm tay theo [GUIDE.md](../../GUIDE.md): coherence, grounding và metadata. Text đầy đủ của từng chunk (để đọc khi chấm) nằm ở `results/private/audit_*_fulltext.csv`. Thư mục đó bị gitignore vì là nội dung sách có bản quyền; chạy `python -m src.run` để tạo lại.

| File | Mẫu | Thang |
|---|---|---|
| `coherence_labels.csv` | 10 vị trí × 3 chiến lược = 30 chunk | 0 = cắt giữa ý, thiếu chủ thể nên không hiểu · 1 = hiểu một phần, thiếu ngữ cảnh · 2 = tự hiểu được, giữ trọn ý |
| `grounding_labels.csv` | 5 câu test × 3 chiến lược, chấm cả top-3 | 0 = không có bằng chứng · 1 = có nhưng thiếu điều kiện/ngữ cảnh · 2 = đủ để trả lời và truy nguồn |
| `metadata_check.csv` | 5 câu test × top-3 × 3 chiến lược = 45 bản ghi | Đủ và đúng (1/0) |

## Chọn mẫu (cố định trước khi xem điểm)

- **Coherence:** 10 trang cách đều trong 914 trang nội dung đã sắp xếp (công thức `round(i·913/9)`, i = 0..9), gồm các trang 12, 113, 215, 323, 425, 526, 635, 736, 838, 939. Vị trí là điểm giữa văn bản của trang. Với mỗi chiến lược, chấm chunk chứa vị trí đó.
- **Grounding và metadata:** toàn bộ 5 câu test (q16–q20).

## Cột nhãn và nguồn gốc

| Cột | Ý nghĩa |
|---|---|
| `label_0_1_2`, `reason` | Nhãn cuối cùng và lý do |
| `labeled_by` | Ai gán nhãn. `student` / `student (reviewed …)` = học viên tự chấm hoặc đã duyệt và đồng ý (được tính vào `student_reviewed`); `claude-llm-judge`, `claude-review-v3` = Claude chấm, học viên chưa duyệt |
| `claude_suggested_0_1_2`, `claude_reason` | Đề xuất lượt 1 của Claude, giữ lại để đối chiếu |
| `needs_label` | `1` khi chunk/top-3 thay đổi sau một lần chạy lại và chưa có nhãn |
| `auto_*` (metadata) | Pipeline đối chiếu với cache trang đã chuẩn hóa |
| `manual_ok`, `note`, `checked_by` (metadata) | Lần kiểm tra thứ hai và người/công cụ thực hiện |

**Trạng thái hiện tại (2026-11-14):**
- 30/30 nhãn coherence và 15/15 nhãn grounding đã được **học viên duyệt và xác nhận**:
  - coherence: `labeled_by = student (reviewed claude-review-v3)`
  - grounding: `labeled_by = student (reviewed claude-llm-judge)`
- Nhãn do Claude soạn, học viên đọc lại và đồng ý toàn bộ; không có nhãn nào do học viên tự chấm từ đầu.
- 45/45 bản ghi metadata được `scripts/verify_metadata_raw.py` xác nhận lại với PDF gốc.

`python -m src.run --stage audit-summary` ghi [`../audit_summary.json`](../audit_summary.json): `label_source` đếm nhãn theo `labeled_by`, còn `student_reviewed` = số nhãn có `labeled_by` bắt đầu bằng `student`. Hiện tại: coherence 10/10, grounding 5/5 cho cả A/B/C.

Khi chạy lại pipeline, nhãn của mẫu không đổi (cùng `chunk_id`, hoặc cùng bộ `top3_chunk_ids`) được giữ nguyên. Mẫu nào đổi thì nhãn bị xóa và được đánh dấu `needs_label=1`. `audit-summary` sẽ dừng với thông báo lỗi nếu còn dòng chưa có nhãn nào, nên không bao giờ ghi ra số liệu `null`.

## Quy tắc quyết định coherence (áp dụng từ v3)

Diễn giải thang của [GUIDE.md](../../GUIDE.md) để mọi dòng được chấm cùng một cách:

| Nhãn | Khi nào |
|---|---|
| **0** | Đọc chunk **không xác định được ý chính** (sự việc/nhận định chính): chủ thể của ý chính bị mất và không suy ra được từ phần còn lại, hoặc chỗ cắt bỏ đi chính ý đó |
| **1** | Ý chính đọc ra được, nhưng đầu hoặc cuối bị cắt (mảnh câu, mất người nói, câu dở dang), **hoặc** câu mở đầu phụ thuộc nội dung của chunk trước (vd. "That's right" đáp lại lời ai đó) |
| **2** | Bắt đầu và kết thúc ở ranh giới câu/đoạn, ý trọn vẹn |

- Đại từ chỉ nhân vật chính ("He" = Harry, "her" = Hermione) **không làm giảm nhãn**; chỉ ghi chú.
- Mảnh câu thiếu chủ ngữ ở đầu chunk là lỗi mức **1**, trừ khi nó làm mất ý chính của cả chunk.

## Lịch sử phiên bản nhãn coherence

| Phiên bản | File | Người gán | Thay đổi |
|---|---|---|---|
| v1 | [history/coherence_labels_v1.csv](history/coherence_labels_v1.csv) | `claude-llm-judge` | Nhãn ban đầu: A 1,0 · B 2,0 · C 2,0 |
| v2 | [history/coherence_labels_v2.csv](history/coherence_labels_v2.csv) | `claude-review-v2` (bản học viên gửi lại) | P01-A, P05-A, P06-A: 1 → 0; P06-B/C: 2 → 1; thêm ghi chú đại từ chưa có tiền ngữ |
| **v3** | `coherence_labels.csv` | `claude-review-v3` | Áp quy tắc trên cho mọi dòng: **giữ** P06-B/C = 1 (câu đáp phụ thuộc chunk trước) và các ghi chú của v2; **trả** P01/P05/P06-A về 1, vì ý chính vẫn đọc ra được và cùng loại lỗi với P03/P04/P07/P08/P10-A (đang là 1); sửa lý do P06-A (v2 ghi "không rõ người nghe" nhưng chunk có nêu tên Lockhart). Kết quả: A 1,0 · B 1,9 · C 1,9 |
| **v3, đã duyệt** | `coherence_labels.csv` | `student (reviewed claude-review-v3)` | Học viên xác nhận đồng ý toàn bộ nhãn v3 (2026-11-14); không đổi điểm. Grounding cũng được xác nhận như vậy |

## Cách Claude chấm (LLM judge)

1. **Lượt 1:** đọc **toàn văn** từng chunk (coherence) hoặc cả top-3 (grounding) trong `results/private/`, đối chiếu với thang điểm ở trên và với `expected_answer`/`evidence_quote`. Ghi một nhãn kèm lý do cụ thể: vị trí bị cắt, cụm từ có hoặc thiếu, trang chứa bằng chứng. Có kiểm tra phụ sự có mặt của cụm then chốt trong top-3 (vd. "crowing of the rooster", "Nimbus Two Thousand").
2. **Lượt 2:** đọc lại toàn văn của 20 chunk coherence (A, B; C trùng B) và các top-3 grounding có chunk đổi sau lần sửa lỗi tách đoạn. Mọi nhãn lượt 1 đều được giữ; chỉ bổ sung lý do cho P09-B/C (lịch thi bị dàn thành một dòng). Kết quả là bản v1 (`labeled_by = claude-llm-judge`).
3. **Coherence v2 → v3:** học viên gửi bản chỉnh v2; Claude áp quy tắc quyết định ở trên để tạo v3 (xem bảng lịch sử).
4. **Học viên duyệt:** học viên xác nhận đồng ý toàn bộ coherence v3 và grounding v1 → `labeled_by = student (reviewed …)`.

Nhãn không suy ra từ Hit@3. Ví dụ q16-C có Hit@3 = 0 nhưng grounding = 1, vì chunk có thiệp của Hagrid và cụm "biting book" nhưng thiếu tên sách.

**Metadata:** `scripts/verify_metadata_raw.py` đọc lại **PDF gốc** bằng `pypdf.extract_text()` thuần (không dùng cache hay bước chuẩn hóa của pipeline, bỏ qua khoảng trắng khi so khớp) và outline PDF. Script kiểm tra 8 từ đầu chunk nằm ở `page`, 8 từ cuối nằm ở `page_end`, `book_no`/`chapter_no` khớp outline, `source` đúng. Đã thử ca sai cố ý (lệch 2 trang, sai số sách) và script bắt được cả hai.

## Nguy cơ thiên lệch

- Người đề xuất (AI) cũng là bên viết pipeline và soạn benchmark, nên không độc lập.
- Chỉ có một người chấm, chưa đo độ đồng thuận.
- Coherence phụ thuộc cách hiểu "đủ ngữ cảnh" trong văn xuôi tiểu thuyết: đại từ chưa rõ người được tính là 2 nếu ý của đoạn vẫn trọn.

**Khi cần chấm lại** (vd. sau khi chạy lại pipeline có dòng `needs_label=1`, hoặc muốn sửa nhãn):
1. Mở `results/private/review_sheet.md` (toàn văn từng mục; nhãn hiện tại ẩn trong khối thu gọn; tạo lại bằng `python -m src.run --stage audit`).
2. Tự chấm trước, rồi mới mở nhãn hiện tại để so.
3. Đồng ý: đổi `labeled_by` thành `student`. Không đồng ý: sửa `label_0_1_2`/`reason` và đặt `labeled_by = student`.
4. Chạy lại `audit-summary` và ghi số nhãn bất đồng vào báo cáo.
