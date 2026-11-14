# Rà soát yêu cầu Day 06

Đối chiếu từng yêu cầu trong [README](README.md), [GUIDE](GUIDE.md), [BENCHMARK](BENCHMARK.md), [RUBRIC](RUBRIC.md), [SUBMISSION](SUBMISSION.md), [RULES](RULES.md) với bài làm. Cập nhật 2026-11-14, sau lần chạy trên PostgreSQL + pgvector.

**Kiểm tra tự động lần rà soát cuối:**
- Hash benchmark `15c9394a9ad2` giống nhau ở cả 3 lần chạy, tức bộ câu hỏi không bị sửa sau khi chốt.
- 20 câu đủ trường; không có secret trong file sẽ commit.
- Đoạn trích sách trong trace ≤ 161 ký tự; 0 link hỏng; code biên dịch được.
- Mọi số Hit@1/Hit@3, số chunk, thời gian, token, coherence, grounding, filter trong báo cáo khớp với `results/`. Độ trễ dao động giữa các lần đo, báo cáo ghi cả hai lần.
- **Đồng bộ chéo giữa các file kết quả:**
  - `metrics.json` ↔ `metrics.md` ↔ `traces.jsonl` ↔ `experiment_log.csv` khớp nhau.
  - `grounding_labels.csv` trỏ đúng top-3 trong trace; 45/45 nhãn đã duyệt, 45/45 metadata đạt.
  - Không file JSON nào trong `results/` (kể cả `history/`) hay `data/manifest.json` còn `null`.
  - `run_log.txt` ghi cả các lần chạy lại từng bước.

✅ đạt · ⚠️ đạt về kỹ thuật nhưng cần học viên xác nhận/duyệt · ❌ chưa làm (việc của học viên)

## 1. Corpus và xử lý (Rubric 20đ)

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| ≥ 30 trang nội dung, không nhân bản | ✅ | 914 trang (B1 263, B2 284, B3 367), [manifest](data/manifest.json) |
| Quy tắc đếm trang, trang vật lý, loại bìa/mục lục/trang trống | ✅ | `page_counting_rule`, `physical_pages_in_pdf` = 3.623, `empty_pages` = [] |
| Manifest: `source_id`, `title`, `source_path_or_url`, `license_or_permission`, `accessed_at`, danh sách trang, số ký tự, snapshot | ✅ | `page_list` (914 dòng: trang, sách, chương, ký tự), `sha256`, `snapshot_or_version` |
| Kiểm tra giấy phép từng tài liệu; chỉ dùng tài liệu được phép | ✅ | Có bản quyền ("all rights reserved"); **giảng viên đã chấp nhận dùng cho lab** (học viên xác nhận ngày 2026-11-14, ghi ở `manifest.json → permission_status`). Vẫn xử lý local, không commit, không gửi API vì sự chấp nhận không bao gồm quyền tái phân phối |
| Đọc bằng Python, chuẩn hóa Unicode, giữ nguồn/trang, ghi lỗi | ✅ | [ingest_log.json](results/ingest_log.json): 0 lỗi, 0 trang rỗng, các bước chuẩn hóa, `known_limitations` |
| Scan/OCR | ✅ | PDF có text, không cần OCR (ghi trong manifest `tools`) |

## 2. Ba chiến lược và lưu trữ (Rubric 20đ)

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| ≥ 3 cấu hình chạy được, ghi tham số | ✅ | [config.py](starter/src/config.py), [experiment_log.csv](artifacts/experiment_log.csv), `index_stats.json → strategies.*.params` |
| So sánh có kiểm soát: A–B chỉ đổi chunking, B–C chỉ đổi filter | ✅ | C dùng đúng chunk và vector của B (`vectors_reused_from_earlier_strategy` = 1.800) |
| Embedding model thật, ghi provider/model/version/số chiều/cách xử lý query–document | ✅ | `intfloat/multilingual-e5-small` rev `614241f6`, 384 chiều, tiền tố `query:`/`passage:`, chuẩn hóa L2 |
| Vector store lưu bền vững, vector search, metadata filter; ghi version, cách khởi tạo, lệnh chạy; exact hay approximate | ✅ | **PostgreSQL 16.16 + pgvector 0.8.7** (docker compose, volume `pg_data`), cosine `<=>`, tìm **chính xác**, `WHERE book_no` ([store.py](starter/src/store.py)) |
| Cùng store và metric cosine cho cả ba | ✅ | Một bảng `chunks`, một collection cho mỗi chiến lược |
| Metadata `document_id`, `source`, `page` + ≥ 1 trường lọc; ghi kiểu, nguồn giá trị, lý do | ✅ | `manifest.json → metadata_schema`; trường lọc `book_no` lấy từ outline PDF |
| Đo số chunk, phân bố độ dài, ký tự/token, thời gian ingest, chi phí | ✅ | [index_stats.json](results/index_stats.json): A 3.476 / B 1.800 chunk, token, 564 s / 484 s, $0 |
| Nạp lại không nhân đôi; xử lý tài liệu đổi | ✅ | Nạp lại: 0 embed lại, 0 xóa; DB: số dòng = số ID phân biệt. Khi đổi ingestion v2 → v3: embed lại 879 chunk đổi, xóa 31 chunk cũ |
| Backend lỗi thì báo lỗi, không fallback sang mock | ✅ | `make_store` raise khi DB không tới được; không có vector giả |

## 3. Benchmark và retrieval (Rubric 20đ)

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| ≥ 20 câu, tách ≥ 15 dev / ≥ 5 test trước khi chạy | ✅ | [questions.json](benchmark/questions.json), `frozen_at` |
| Đủ trường `id`, `split`, `question`, `expected_answer`, `gold_source_id`, `gold_page`, `evidence_quote`, `filter` | ✅ | Có thêm `type`, `alt_evidence` |
| Câu trực tiếp / diễn đạt lại / điều kiện | ✅ | 5 / 7 / 3 |
| ≥ 3 câu có filter, ≥ 1 ở test; filter là ngữ cảnh cho trước, không chứa gold | ✅ | 5 câu (dev q13–q15, test q16–q17), lọc cả cuốn sách |
| Evidence được kiểm chứng trên trang nguồn trước khi chạy | ✅ | `verify_benchmark`: 24/24 |
| Chia theo chủ đề, ghi nguy cơ rò rỉ | ✅ | [benchmark/README.md](benchmark/README.md) |
| Bộ câu do học viên tự xây | ⚠️ | AI soạn nháp; học viên cần đọc lại |
| Trace top-3: câu hỏi, ID và text chunk, score, metadata, nhãn | ✅ | [traces.jsonl](results/traces.jsonl) (đoạn trích ≤ 160 ký tự); full text ở `results/private/` (gitignored vì bản quyền, tái tạo bằng `python -m src.run`) |
| Hit@1, Evidence Hit@3 dạng n/N, dev/test riêng, cả ba cấu hình | ✅ | [metrics.md](results/metrics.md) |

## 4. Năm khía cạnh (Rubric 25đ)

| Khía cạnh | Trạng thái | Bằng chứng |
|---|---|---|
| Retrieval accuracy | ✅ | Hit@1 / Hit@3 / MRR@3, phân loại lỗi (`evidence_split_across_chunks`, `right_page_but_evidence_missing`, `wrong_location`) |
| Chunk coherence: 10 vị trí cố định trước, thang 0–2, lý do, trung bình | ✅ | [coherence_labels.csv](results/audit/coherence_labels.csv): 30/30 có nhãn và lý do; A 1,0 · B 1,9 · C 1,9; quy tắc quyết định và lịch sử v1→v3 trong [results/audit/README.md](results/audit/README.md). LLM soạn, **học viên duyệt 30/30** |
| Metadata usefulness: 5 test × top-3, đủ/đúng n/N, lỗi, tuân thủ filter, 1 trường hữu ích + 1 hạn chế | ✅ | 45/45 đúng qua 2 lần kiểm tra (pipeline + script đọc PDF gốc), `errors: []`; filter test A 0/2 · B 0/2 · C 2/2; giải thích trong báo cáo |
| Grounding: 5 test × top-3, 0/1/2, lý do, phân bố, trung bình; không gọi là độ chính xác LLM | ✅ | [grounding_labels.csv](results/audit/grounding_labels.csv): 15/15 có nhãn; A 1,4 · B 0,6 · C 0,8. LLM soạn, **học viên duyệt 15/15** |
| Data strategy impact A–B, B–C, đánh đổi, mẫu nhỏ | ✅ | Báo cáo mục Phân tích |
| Ghi người chấm, nguy cơ thiên lệch, phương pháp nếu dùng AI | ✅ | [results/audit/README.md](results/audit/README.md), `audit_summary.json → label_policy`, `label_source` |

`audit_summary.json` không còn `null`. Mỗi nhãn có `labeled_by`, và `student_reviewed` cho biết học viên đã duyệt bao nhiêu.

## 5. Tái lập và báo cáo (Rubric 15đ)

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| README có lệnh setup/run | ✅ | [starter/README.md](starter/README.md) |
| Version thư viện, model, chi phí, thời điểm chạy, seed | ✅ | [requirements.txt](starter/requirements.txt), `metrics.json → run`, `SEED = 6` |
| Log lỗi, lịch sử chạy | ✅ | [run_log.txt](results/run_log.txt), [results/history/](results/history/) (lần 1: lỗi tách đoạn; lần 2: Chroma) |
| Báo cáo theo mẫu, ví dụ lỗi có ID câu và nguồn, hạn chế | ✅ | [report/individual/2A202603857_NguyenLeTrongManh.md](report/individual/2A202603857_NguyenLeTrongManh.md) |
| Tiêu chí chọn chốt trước test; không tinh chỉnh trên test | ⚠️ | Chọn chỉ dựa vào dev, tham số và câu hỏi không đổi. Nhưng `eval` tính dev và test cùng lượt, và lần chạy lại diễn ra sau khi đã thấy test của lần 1, nên báo cáo ghi theo RULES là **test không được coi là kiểm tra độc lập hoàn toàn** (không báo như holdout độc lập) |
| Ghi nguồn và giấy phép của model, thư viện, mã bên ngoài (RULES) | ✅ | Báo cáo mục "Nguồn và giấy phép bên ngoài": e5-small MIT, pypdf BSD-3, sentence-transformers/transformers/chromadb Apache-2.0, psycopg LGPL-3.0 (theo metadata gói) |
| Ghi công cụ AI và cách kiểm tra (RULES) | ✅ | Dòng cuối báo cáo + [results/audit/README.md](results/audit/README.md) |

## 6. Nộp bài

| Yêu cầu | Trạng thái | Việc cần làm |
|---|---|---|
| Không có secret, dữ liệu không được phép trong repo | ✅ | `.env`, PDF (`starter/data/raw/`, chỉ giữ `.gitkeep`), `data/processed`, `data/index`, `results/private` đều trong `.gitignore` |
| Điền [STUDENT.md](STUDENT.md) (họ tên, MSSV, lớp, link repo, commit chốt) | ⚠️ | Đã có họ tên, MSSV, lớp, chủ đề, link repo; còn **commit chốt** (điền sau khi commit + push) |
| Học viên hiểu và giải thích được bài làm (RULES) | ⚠️ | Đọc báo cáo + `starter/README.md`; nắm 3 điểm chính: vì sao A tốt hơn trên test, vì sao filter không tăng Hit@3, lỗi tách đoạn đã sửa |
| Nhãn coherence/grounding/metadata đã đủ, không còn null | ✅ | LLM judge + script đọc PDF gốc |
| Học viên duyệt nhãn LLM | ✅ | 45/45 đã duyệt (2026-11-14), `student_reviewed` = 10/10 và 5/5 |
| Xác nhận quyền dùng corpus với giảng viên | ✅ | Đã được chấp nhận (2026-11-14) |
| Commit, push lên repo cá nhân, nộp link | ❌ | Học viên làm (chưa có commit nào) |
