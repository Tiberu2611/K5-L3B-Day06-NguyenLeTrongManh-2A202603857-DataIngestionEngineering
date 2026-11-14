# Pipeline · Harry Potter (Books 1–3) · PostgreSQL + pgvector · multilingual-e5-small

Bản hiện thực pipeline Day 06 trên corpus `harrypotter.pdf`. Toàn bộ chạy **local**: embedding model chạy trên máy, PostgreSQL + pgvector trong Docker, không gửi dữ liệu tới API nào.

> **Quyền dữ liệu.** PDF có bản quyền (© J.K. Rowling / Pottermore); **giảng viên đã chấp nhận dùng làm corpus cho bài lab** (2026-11-14). Sự chấp nhận không bao gồm quyền tái phân phối, nên PDF, text trích xuất, chunk và trace đầy đủ vẫn nằm trong `.gitignore` hoặc trong volume Docker. Repo chỉ chứa manifest, ID, metadata, điểm số và đoạn trích ngắn. Người chấm tái tạo bằng bản PDF của mình (SHA-256 trong `data/manifest.json`).

## Thành phần

| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Đọc PDF | `pypdf` + tọa độ dòng | Dựng lại đoạn văn theo thụt lề (x = lề + 14,4pt) và khoảng cách dòng; nối drop-cap; bỏ tiêu đề chương |
| Metadata | `document_id`, `source`, `page`, `page_end`, `book_no`, `book_title`, `chapter_no`, `chapter_title` | `book_no`/`chapter_*` lấy từ **outline (bookmark) của PDF**, không đoán; schema ở `data/manifest.json` → `metadata_schema` |
| Embedding | `intfloat/multilingual-e5-small` (384 chiều, CPU) | tiền tố `query: ` / `passage: ` theo model card; vector chuẩn hóa L2 |
| Vector store | **PostgreSQL 16 + pgvector 0.8.7** (`docker-compose.yml`) | bảng `chunks`, cột `vector(384)`; cosine `<=>`; tìm kiếm **chính xác** (sequential scan); lọc bằng `WHERE book_no = %s` |
| Chiến lược | A: cố định 500/50 · B: theo đoạn ≤1000 · C: B + filter `book_no` | C dùng đúng chunk/vector của B; khác B **chỉ** ở filter |

Backend thay thế: `VECTOR_STORE=chroma` (Chroma lưu ở `data/index/chroma`, dùng cho lần chạy trước khi máy chưa có Docker). Nếu backend đã chọn không chạy, pipeline báo lỗi và dừng, không tự chuyển sang store khác.

## Cài đặt và chạy

Cần Docker Desktop, Python 3.11–3.14. Chạy từ thư mục `starter/`:

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   ·   macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
# Windows: Copy-Item .env.example .env   ·   macOS/Linux: cp .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py           # kỳ vọng: PostgreSQL 16.x | pgvector 0.8.7 | Setup OK
# Đặt harrypotter.pdf vào starter/data/raw/ (gitignored), hoặc khai báo CORPUS_PDF=... trong .env
python -m src.run                       # ingest → index → eval → audit
```

- Chạy từng bước: `python -m src.run --stage ingest|index|eval|audit|audit-summary`.
- Lần đầu tải model (~470 MB) từ Hugging Face; sau đó chạy offline.
- Biến tùy chọn trong `.env`: `CORPUS_PDF` (mặc định `starter/data/raw/harrypotter.pdf`; đường dẫn tương đối tính từ `starter/`), `BOOKS` (mặc định `1,2,3`), `EMBEDDING_MODEL`, `VECTOR_STORE` (`pgvector` | `chroma`).
- Kiểm tra đúng bản PDF: SHA-256 phải là `29a4779794a47c5eeef4df7ccd8bfdbc32978e7dce89764777c547b0b602a694` (ghi trong `data/manifest.json`). Nếu khác, bước ingest sẽ in cảnh báo.
- Dừng DB nhưng giữ dữ liệu: `docker compose -p day6_student_starter stop`.

**Nhãn audit:**
- Nhãn coherence/grounding do LLM soạn và đã được học viên duyệt (`labeled_by = student (reviewed …)`); metadata được `python scripts/verify_metadata_raw.py` kiểm tra lại với PDF gốc.
- Khi chạy lại pipeline, nhãn của mẫu không đổi được giữ nguyên. Mẫu nào đổi sẽ được đánh dấu `needs_label=1` để chấm lại bằng `results/private/review_sheet.md`.
- Sau đó chạy `python -m src.run --stage audit-summary`. Phương pháp chi tiết ở [results/audit/README.md](../results/audit/README.md).

## Mã nguồn

| File | Nội dung |
|---|---|
| `src/config.py` | Đường dẫn, phạm vi sách, model, store, tham số A/B/C, schema metadata |
| `src/ingestion.py` | Đọc outline và trang, chuẩn hóa, log lỗi, manifest (kèm danh sách trang và số ký tự) |
| `src/chunking.py` | Dòng văn bản theo chương; `fixed_size` (A), `by_paragraph` (B/C); ánh xạ chunk → trang |
| `src/embeddings.py` | Adapter Sentence Transformers, không có fallback giả |
| `src/store.py` | `PgVectorStore` (mặc định) và `ChromaStore`: upsert idempotent (ID ổn định + hash), xóa chunk lỗi thời, search có filter whitelist |
| `src/evaluation.py` | Hit@1, Evidence Hit@3, MRR@3, phân loại lỗi, tuân thủ filter |
| `src/run.py` | Điều phối, trace, metrics, bảng audit (giữ nhãn khi chạy lại), phiếu chấm, audit summary |
| `scripts/check_setup.py` | Kiểm tra kết nối PostgreSQL + extension pgvector |
| `scripts/verify_metadata_raw.py` | Kiểm tra metadata lần 2: đối chiếu chunk với PDF gốc (`pypdf.extract_text`) và outline |

## Đầu ra

| Đường dẫn | Commit? | Nội dung |
|---|---|---|
| `data/manifest.json` | ✅ | Nguồn, quyền, SHA-256, quy tắc đếm trang, danh sách 914 trang + số ký tự, schema metadata |
| `benchmark/questions.json` | ✅ | 20 câu (15 dev / 5 test), gold page, evidence, filter |
| `results/ingest_log.json`, `index_stats.json` | ✅ | Log chuẩn hóa và giới hạn, số chunk, phân bố độ dài, token, thời gian, kiểm tra nạp lại |
| `results/metrics.json`, `metrics.md`, `traces.jsonl` | ✅ | Chỉ số dev/test, trace top-3 (đoạn trích ≤160 ký tự) |
| `results/audit/*.csv`, `audit_summary.json` | ✅ | Nhãn coherence / grounding / metadata và bảng tổng hợp |
| `results/audit/history/` | ✅ | Các phiên bản nhãn coherence v1, v2 |
| `results/history/` | ✅ | Kết quả các lần chạy trước (lỗi tách đoạn; Chroma), xem README trong đó |
| `results/private/` | ❌ | Trace full text, bảng audit full text, phiếu chấm `review_sheet.md` |
| `starter/data/raw/harrypotter.pdf` | ❌ | Corpus gốc (có bản quyền); chỉ thư mục và `.gitkeep` được commit |
| `data/processed/`, `data/index/`, volume `pg_data` | ❌ | Text trang, chunk, vector |
