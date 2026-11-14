# Lịch sử các lần chạy

Kết quả chính của bài nằm ở `results/` (lần chạy 3, PostgreSQL + pgvector). Thư mục này giữ các lần chạy trước để có thể đối chiếu. Bộ câu hỏi của cả ba lần giống hệt nhau (hash `15c9394a9ad2`).

| Thư mục | Lần chạy | Store | Khác biệt | dev Hit@3 A / B / C |
|---|---|---|---|---|
| `run1_paragraph_bug/` | 1 | Chroma 1.5.9 (HNSW) | Lỗi tách đoạn: các đoạn thoại bị gộp trên trang nhiều thoại (ingestion v2). Phát hiện khi audit coherence | 6 / 10 / 10 |
| `run2_chroma/` | 2 | Chroma 1.5.9 (HNSW) | Đã sửa lỗi tách đoạn (ingestion v3) | 6 / 8 / 8 |
| `../` (kết quả chính) | 3 | PostgreSQL 16 + pgvector 0.8.7 (exact) | Cùng chunk với lần 2; top-3 giống hệt ở 60/60 cặp | 6 / 8 / 8 |

## Thay đổi sau khi lưu (chỉ đổi định dạng, không đổi số liệu)

Hai file trong `run2_chroma/` được cập nhật ngày 2026-11-14 để không còn giá trị `null` gây hiểu nhầm:

- **`traces.jsonl`:** các giá trị "không áp dụng" đổi từ `null` sang `"none"` / `"N/A"` / `"none (hit)"` / `"not in top-3"`, giống định dạng của trace hiện tại. ID chunk, điểm số và kết quả hit giữ nguyên.
- **`audit_summary.json`:** bản chụp gốc được tạo lúc chưa có nhãn nào ("labelled 0/n", trung bình rỗng). File được tính lại bằng `stage_audit_summary` với các nhãn đã duyệt trong `results/audit/`. Việc này hợp lệ vì script đã xác minh lần 2 và lần 3 có top-3 trùng 60/60, 15/15 dòng grounding trỏ đúng các chunk đó, cùng chỉ số Hit/filter và cùng kết quả chunking. File có trường `note` ghi lại điều này.

Thư mục `run1_paragraph_bug/` không có `audit_summary.json` và không bị chỉnh sửa. Chunk của lần 1 khác lần 3, nên không áp được bộ nhãn hiện tại.
