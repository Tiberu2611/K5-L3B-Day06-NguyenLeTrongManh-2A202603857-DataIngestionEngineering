# Báo cáo cá nhân — Day 6

> **Nguồn số liệu:** lần chạy chính trên **PostgreSQL + pgvector** (`results/`; index xong lúc 2026-11-14T04:24Z, lần eval cuối 04:30Z). Nhãn coherence (30) và grounding (15) do **Claude soạn theo phương pháp LLM judge có ghi rõ**, rồi được **học viên duyệt và xác nhận toàn bộ** (`student_reviewed` = 10/10 và 5/5; xem [results/audit/README.md](../../results/audit/README.md)). Metadata được xác nhận lại bằng script đọc PDF gốc (45/45). Đối chiếu đầy đủ yêu cầu: [REQUIREMENTS_CHECK.md](../../REQUIREMENTS_CHECK.md).

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** Harry Potter, Books 1–3, trích từ `harrypotter.pdf` (*Harry Potter: The Complete Collection*, ấn bản số Pottermore, PDF tạo bằng calibre 3.27.1, 3.623 trang vật lý, SHA-256 `29a47797…a694`). Tính **914 trang nội dung**: B1 263 trang (tr. 12–274), B2 284 trang (tr. 282–565), B3 367 trang (tr. 573–939); 57 chương; 1.549.115 ký tự sau chuẩn hóa. Quy tắc: chỉ đếm trang nằm trong dải chương lấy từ outline (bookmark) của PDF; loại trang tựa, mục lục, "Pottermore.com", trang bản quyền. 0 trang rỗng. Chi tiết: [data/manifest.json](../../data/manifest.json).
  - **Quyền:** tác phẩm có bản quyền (© J.K. Rowling / Pottermore), trang bản quyền ghi *"All rights reserved… or stored in a retrieval system… without written permission"*. **Giảng viên đã chấp nhận dùng file này làm corpus cho bài lab** (học viên xác nhận ngày 2026-11-14). Sự chấp nhận áp dụng cho việc xử lý trong lab, không cho phép tái phân phối, nên vẫn giữ nguyên các biện pháp: xử lý local, không gửi API, không commit PDF/text/chunk/index/trace đầy đủ; repo chỉ chứa ID, metadata, điểm số và đoạn trích ngắn.
- **Chuẩn hóa, lỗi và giới hạn:** `pypdf` 6.21.4 trích từng trang kèm tọa độ dòng. Unicode NFC; tab/NBSP → một khoảng trắng; dựng lại đoạn văn từ thụt lề dòng đầu (+14,4pt) và khoảng cách dòng; bỏ 115 dòng tiêu đề chương (giữ thành metadata); nối lại 57/57 chữ drop-cap; 80 dòng kết thúc bằng gạch nối được nối không khoảng trắng; giữ nguyên ngoặc cong, gạch dài. 0 lỗi trích xuất, không cần OCR.
  - **Lỗi đã phát hiện và sửa:** lần chạy 1 lấy lề trái = tọa độ x phổ biến nhất; trên trang nhiều thoại, dòng thụt lề nhiều hơn dòng ở lề nên các lời thoại riêng bị gộp thành một đoạn. Phát hiện khi audit coherence (vị trí P06, tr. 526, chunk B kết thúc lửng ở `“D-did I?`). Sửa ở ingestion v3 (lề = x nhỏ nhất; ngưỡng gap = 1,25 × phân vị 25%): số đoạn tăng 8.381 → 10.938. Kết quả lần 1 lưu ở [results/history/run1_paragraph_bug/](../../results/history/run1_paragraph_bug/).
  - **Giới hạn còn lại:** 4 trang cuối chương mà mọi dòng đều thụt lề (tr. 106, 111, 352, 866, không phải trang gold) vẫn bị gộp đoạn; chương mở đầu bằng thoại mất dấu `“` vì glyph drop-cap không chứa nó (vd. tr. 123). Xem `known_limitations` trong [results/ingest_log.json](../../results/ingest_log.json).
- **Embedding, vector store, lệnh chạy và chi phí:** `intfloat/multilingual-e5-small` (revision `614241f6`), 384 chiều, tối đa 512 token, chạy local CPU bằng sentence-transformers 6.3.0 / torch 2.15.0+cpu; tiền tố `query: ` / `passage: `, vector chuẩn hóa L2. Không chunk nào vượt 512 token.
  - **Vector store:** **PostgreSQL 16.16 + pgvector 0.8.7**, chạy bằng `starter/docker-compose.yml` (image `pgvector/pgvector:0.8.7-pg16`, volume `pg_data`, cổng `127.0.0.1:55433`). Bảng `chunks` có cột `embedding vector(384)`, cột kiểu riêng `book_no`/`chapter_no` để lọc, phần metadata còn lại để ở JSONB; mỗi chiến lược là một giá trị `collection`. Khoảng cách cosine `<=>`, tìm kiếm **chính xác** (`ORDER BY embedding <=> q LIMIT 3`, quét tuần tự, không dùng ANN index vì mỗi chiến lược chỉ ~3,5k dòng; cách này cũng tránh mất recall khi lọc trên HNSW).
  - **Lệnh:** `docker compose -p day6_student_starter up -d --wait`, `python scripts/check_setup.py`, `python -m src.run`.
  - **Chi phí: $0** (không dùng API). Máy: Windows 11, 8 CPU, không GPU, Python 3.14.6.
  - **Lịch sử store:** hai lần chạy đầu dùng Chroma 1.5.9 (HNSW xấp xỉ, `ef_search=200`) khi máy chưa có Docker. Khi chuyển sang pgvector, **top-3 giống hệt ở 60/60 cặp câu hỏi × chiến lược và điểm trùng đến 4 chữ số thập phân**, nên HNSW ở quy mô này cho kết quả như tìm chính xác ([results/history/run2_chroma/](../../results/history/run2_chroma/)).
- **Metadata và trường lọc:** bắt buộc `document_id`, `source`, `page` (+ `page_end` cho chunk vắt trang). Trường lọc `book_no` (int, lấy từ outline PDF), kèm `book_title`, `chapter_no`, `chapter_title`. Kiểu, nguồn giá trị và lý do của từng trường có trong `data/manifest.json → metadata_schema`. Lý do chọn `book_no`: nhân vật và sự kiện lặp lại giữa các cuốn nên nhiều câu hỏi có đáp án khác nhau theo từng cuốn, và người đọc thường biết mình đang đọc cuốn nào.

## Cấu hình và benchmark

- **A / B / C:**
  - **A:** cửa sổ cố định 500 ký tự, overlap 50, điểm cắt lùi về khoảng trắng gần nhất, không vượt ranh giới chương, không lọc.
  - **B:** ghép trọn đoạn văn đến tối đa 1.000 ký tự; đoạn dài hơn thì tách ở ranh giới câu; không overlap; không lọc.
  - **C:** dùng **đúng chunk và vector của B**, thêm `where book_no = X` chỉ khi câu hỏi có filter. Khác biệt duy nhất B–C là filter; A–B chỉ đổi chunking.
- **Benchmark (20 câu):** 15 dev / 5 test, chia theo chương (5 chương của test không có câu dev nào). Loại câu: 5 trực tiếp, 7 diễn đạt lại, 3 điều kiện, 5 có filter (dev q13–q15, test q16–q17). Câu filter được thiết kế mơ hồ khi không lọc (mật khẩu đầu năm, quà ẩn danh, giáo viên Phòng chống Nghệ thuật Hắc ám, quà sinh nhật của Hagrid, cây chổi mới). Filter là ngữ cảnh người dùng cung cấp trước ("đang đọc cuốn N"), thu hẹp về cả một cuốn, không phải trang gold. Evidence được script kiểm chứng trên trang gold trước khi truy xuất: **24/24** (20 chính + 4 thay thế). Bộ câu do AI hỗ trợ soạn, học viên cần đọc lại. Xem [benchmark/README.md](../../benchmark/README.md).
- **Tiêu chí chọn (chốt trước test):** Evidence Hit@3 dev → Hit@1 dev → ít chunk / thời gian embed thấp hơn.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian embed + ghi (pgvector) | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 3/15 | 6/15 | 3.476 | 564 s | $0 |
| A | test | 0/5 | 2/5 | | | |
| B | dev | 6/15 | 8/15 | 1.800 | 484 s | $0 |
| B | test | 1/5 | 1/5 | | | |
| C | dev | 6/15 | 8/15 | 1.800 (chung với B) | 2 s (dùng lại vector của B) | $0 |
| C | test | 1/5 | 1/5 | | | |

- **Tài nguyên:** tổng token (kể cả tiền tố) A 497.143, B/C 443.785; dung lượng vector A 5,2 MB, B/C 2,7 MB mỗi collection. Tải model ~31 s.
- **Độ trễ truy vấn** (tìm chính xác, dùng lại kết nối): trung vị A 38 ms, B 18 ms, C 17 ms ở lần chạy ghi trong `traces.jsonl`; lần đo trước đó là 23 / 12 / 11 ms. Con số dao động theo tải máy, nhưng thứ tự không đổi: A quét gấp đôi số dòng nên chậm hơn B/C.
- **Nạp lại cùng phiên bản:** 0 chunk embed lại, 0 xóa; trong DB số dòng bằng số ID phân biệt ở cả ba collection.
- **Cập nhật khi tài liệu đổi:** khi đổi ingestion v2 → v3 (trên Chroma), chỉ embed lại chunk có hash đổi (A 710, B 879) và xóa 31 chunk lỗi thời ([results/index_stats.json](../../results/index_stats.json), [results/history/](../../results/history/)).

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,0 (10) | 15/15 | test 0/2 · dev 0/3 (không áp filter) | 0 / 3 / 2 → 1,4 |
| B | 1,9 (10) | 15/15 | test 0/2 · dev 1/3 (không áp filter) | 3 / 1 / 1 → 0,6 |
| C | 1,9 (10) | 15/15 | **test 2/2 · dev 3/3** | 2 / 2 / 1 → 0,8 |

**Người chấm và phương pháp ([audit_summary.json](../../results/audit_summary.json)):**
- **Coherence (30 nhãn):**
  - v1: Claude chấm.
  - v2: học viên gửi bản chỉnh: hạ 3 chunk A xuống 0, hạ P06-B/C xuống 1, thêm ghi chú đại từ.
  - v3: áp một quy tắc quyết định chung cho mọi dòng. Giữ P06-B/C = 1; trả 3 chunk A về 1 cho nhất quán với 5 chunk A cùng loại lỗi; sửa một lý do sai sự thật.
  - Học viên duyệt v3 và đồng ý toàn bộ (`student (reviewed claude-review-v3)`).
- **Grounding (15 nhãn):** Claude đọc toàn văn top-3 theo thang 0–2 (hai lượt, có lý do cho từng nhãn); học viên duyệt và đồng ý toàn bộ (`student (reviewed claude-llm-judge)`).
- **Kết quả duyệt:** 45/45 nhãn đã được học viên duyệt. Bất đồng trong quá trình duyệt: 5 nhãn coherence ở v2, được giải quyết bằng quy tắc v3.
  - Nguy cơ thiên lệch: người chấm cũng là bên viết pipeline và benchmark, chỉ một người chấm, chưa đo độ đồng thuận.
- **Metadata:** lần 1 do pipeline kiểm tra tự động (45/45, `errors: []`). Lần 2 dùng `scripts/verify_metadata_raw.py` đọc lại PDF gốc bằng `pypdf.extract_text()` và outline, không qua cache của pipeline: 45/45 xác nhận. Script đã được thử với ca sai cố ý và bắt được lỗi.

**Trace, nhãn và cách chọn mẫu:** trace top-3 có đoạn trích ≤160 ký tự ở [results/traces.jsonl](../../results/traces.jsonl); trace full text ở `results/private/traces_full.jsonl` (gitignored). Bảng nhãn: [coherence](../../results/audit/coherence_labels.csv), [grounding](../../results/audit/grounding_labels.csv), [metadata](../../results/audit/metadata_check.csv); full text để chấm nằm ở `results/private/`.
- **Coherence:** 10 vị trí chọn theo quy tắc trước khi xem điểm: 10 trang cách đều trong 914 trang đã sắp xếp (tr. 12, 113, 215, 323, 425, 526, 635, 736, 838, 939), lấy điểm giữa văn bản trang; mỗi chiến lược chấm chunk chứa điểm đó.
- **Grounding:** 5 câu test × top-3 × 3 chiến lược.
- **Metadata:** 5 câu test × top-3 × 3 chiến lược = 45 bản ghi. Tự động đối chiếu `source`/`document_id`, việc text chunk bắt đầu ở `page` và kết thúc ở `page_end`, và `book_no`/`chapter_no` khớp outline. Ở lần đầu, checker báo sai 1 bản ghi A (8 từ đầu chunk vắt qua ranh giới tr. 777/778), đã sửa checker; metadata thật vẫn đúng. Cột `manual_ok` chờ học viên kiểm tra mẫu.

## Phân tích và kết luận

- **A–B (đổi chunking):** trên dev, B tăng Hit@3 từ 6 lên 8/15 và Hit@1 từ 3 lên 6/15. Coherence tăng từ 1,0 lên 1,9: cả 10 chunk A đều cắt giữa câu ở đầu và/hoặc cuối (mức 1, ý chính vẫn đọc được); 9/10 chunk B bắt đầu và kết thúc ở ranh giới đoạn, ý trọn vẹn. Chunk B còn lại (P06) bắt đầu ở ranh giới đoạn nhưng câu mở đầu "That's right, Gilderoy" đáp lại lời ở chunk trước nên được 1. Quy tắc chấm và lịch sử v1→v3: [results/audit/README.md](../../results/audit/README.md). B cũng dùng ít chunk hơn (1.800 so với 3.476) và ít token hơn. **Nhưng trên test, A tốt hơn** (Hit@3 2/5 so với 1/5; grounding 1,4 so với 0,6). Kiểu lỗi khác nhau: A thường có evidence bị cửa sổ cố định cắt đôi (`evidence_split_across_chunks` 4/20 câu); B thường lấy đúng cảnh nhưng trượt sang chunk kề (`right_page_but_evidence_missing` 5/20). Chunk ~900 ký tự làm câu then chốt chiếm tỷ trọng nhỏ trong vector.
- **B–C (thêm filter):** với câu không có filter, hai cấu hình giống hệt nhau theo thiết kế. Với câu có filter, tuân thủ phạm vi tăng từ 1/3 lên 3/3 (dev) và 0/2 lên 2/2 (test), nhưng Hit@1/Hit@3 không đổi. Filter đảm bảo **đúng phạm vi** chứ không sửa được lỗi ranh giới chunk.
- **Tính hữu dụng của metadata:**
  - *Truy vết:* `page`/`page_end` cho phép mở đúng trang PDF kể cả khi chunk vắt trang; 950/3.476 chunk A và 780/1.800 chunk B vắt qua 2 trang, chỉ có `page` thì 1/4–2/5 số chunk sẽ trỏ thiếu trang.
  - *Lọc:* `book_no` loại các đáp án đúng chủ đề nhưng sai cuốn (q13, q16).
  - *Hạn chế:* lọc theo cả cuốn (~280–370 trang) quá thô để cứu recall: q13 lọc đúng sách 1 nhưng vẫn trượt. `book_no` chỉ hữu ích khi người dùng cho biết cuốn sách. `chapter_no` có cột lọc nhưng benchmark chưa dùng.
- **Ví dụ lỗi 1, q18 (test, B/C, tr. 600):** chunk `B-b3-c03-0004` (tr. 599–600) dừng ở *"…began to speak loudly to the night."*; lời chào *"Welcome to the Knight Bus, emergency transport…"* nằm ở chunk kế tiếp `…-0005` và không được truy xuất. A lấy được `A-b3-c03-0008` nhưng cửa sổ bị cắt ở *"stranded witch or"*, thiếu phần cách gọi xe. Cả hai đều là lỗi ranh giới.
- **Ví dụ lỗi 2, q13 (dev, filter `book_no=1`, gold tr. 121):** không lọc, A trả cảnh mật khẩu ở sách 3 (Sir Cadogan, tr. 798) và sách 2 (tr. 350): đúng chủ đề nhưng sai cuốn. Có lọc, C ở đúng sách 1 nhưng top-3 không liên quan (điểm ~0,826), vì model ngữ nghĩa nhỏ không bắt được cảnh Percy đọc *"Caput Draconis"*. Tương tự q16: B trả quà của Hagrid ở sách 1–2 (bánh, kẹo), C lọc về sách 3 và lấy được thiệp của Hagrid (grounding 0 → 1).
- **Các lần chạy:**
  - Lần 1 (Chroma, lỗi tách đoạn): B/C dev Hit@3 10/15.
  - Lần 2 (Chroma, đã sửa): B/C dev Hit@3 8/15; q08, q11 chuyển thành trượt sang chunk kề; A giữ nguyên 6/15.
  - Lần 3 (pgvector, báo cáo chính): kết quả giống hệt lần 2.

  Kết quả sau sửa được giữ vì xử lý dữ liệu đúng, không phải vì điểm. Sự dao động giữa lần 1 và 2 cho thấy kết quả rất nhạy với ranh giới chunk khi mẫu nhỏ.
- **Chiến lược chọn: C.** Theo tiêu chí đã chốt, B = C = 8/15 > A = 6/15 về Hit@3 dev; Hit@1 dev hòa (6 = 6) và cùng chunk nên tiêu chí không phân định được B với C. Chọn C vì giống hệt B ở câu không có filter và tốt hơn hẳn về tuân thủ phạm vi (dev 3/3 so với 1/3). **Minh bạch:** bước phân định cuối này không được viết sẵn trước. Ngoài ra, stage `eval` tính dev và test trong cùng một lượt nên số test đã hiện ra lúc chọn, dù lựa chọn chỉ dựa vào dev; lần chạy lại sau khi sửa lỗi tách đoạn cũng diễn ra sau khi đã thấy test của lần 1. Theo [RULES.md](../../RULES.md), vì vậy kết quả test **không được coi là kiểm tra độc lập hoàn toàn**. Tham số A/B/C và bộ câu hỏi không đổi sau khi thấy test (hash benchmark `15c9394a9ad2` giống nhau ở cả 3 lần chạy). Nếu cần một holdout sạch, phải soạn thêm bộ test mới từ các chương chưa dùng và chạy đúng một lần với cấu hình đã chốt. Trên test, A tốt hơn C; với 5 câu, khác biệt 1 câu chưa đủ để kết luận. Không suy rộng ngoài corpus này.
- **Điều kiện áp dụng C:** khi ngữ cảnh người dùng cho biết chắc chắn cuốn sách. Nếu không có ngữ cảnh đó, C hoạt động như B.
- **Hạn chế:**
  - Corpus có bản quyền: được giảng viên chấp nhận cho lab nhưng không thể chia sẻ text/trace đầy đủ, người chấm phải tự tái tạo bằng PDF của mình.
  - Test chỉ có 5 câu, chỉ có tiếng Anh.
  - Câu hỏi soạn khi nhìn vào text (dễ trùng từ vựng) và có AI hỗ trợ.
  - Nhãn coherence/grounding do LLM soạn trước rồi học viên duyệt, nên có nguy cơ thiên lệch neo theo nhãn có sẵn (anchoring). Không có người chấm thứ hai độc lập, chưa đo độ đồng thuận.
  - Thời gian đo trên một máy CPU, một lần chạy, không lặp lại để lấy trung bình.
  - Tìm kiếm chính xác chỉ phù hợp ở quy mô nhỏ; mở rộng lên 7 cuốn có thể cần HNSW kèm `hnsw.iterative_scan` để không mất kết quả khi lọc.
  - Điểm cosine của e5 dồn trong khoảng hẹp (~0,82–0,89) nên khó đặt ngưỡng.
  - Chạy lại lần 2 diễn ra sau khi số test của lần 1 đã hiện ra (lý do sửa là lỗi xử lý dữ liệu, tham số chiến lược giữ nguyên).
- **Nếu làm lại/mở rộng:**
  1. Trả thêm chunk kề (±1) hoặc overlap 1 đoạn cho B để xử lý lỗi trượt sang chunk kề.
  2. Thử B với tối đa ~600 ký tự.
  3. Hybrid BM25 cho tên riêng và cụm hiếm ("Caput Draconis", "Nimbus Two Thousand").
  4. Thêm cross-encoder reranker.
  5. Sửa lề dự phòng cho 4 trang còn lỗi.
  6. Thêm cờ `--split dev` để chạy dev trước, test sau khi đã chốt.
  7. Mở rộng sang Books 4–7, nhờ người thứ hai chấm nhãn độc lập.

**Nguồn và giấy phép bên ngoài:**
- Model `intfloat/multilingual-e5-small`: MIT, theo model card trong cache Hugging Face.
- Thư viện (theo metadata gói): pypdf 6.21.4 BSD-3-Clause, sentence-transformers 6.3.0 Apache-2.0, transformers 5.23.0 Apache-2.0, torch 2.15.0, chromadb 1.5.9 Apache-2.0, psycopg 3.3.8 LGPL-3.0, python-dotenv BSD-3-Clause.
- Hạ tầng: PostgreSQL + pgvector qua image `pgvector/pgvector:0.8.7-pg16` của starter.
- Không chép mã từ nguồn ngoài. Starter của lớp được giữ cấu trúc; các hàm TODO do bài làm hiện thực.

**Công cụ AI:** Claude (Claude Code) hỗ trợ viết code pipeline, soạn nháp benchmark và chấm nhãn audit (LLM judge). Cách kiểm tra: evidence được script đối chiếu với text trang; mỗi lỗi (lỗi tách đoạn, checker metadata) được truy đến tọa độ PDF và text gốc trước khi sửa.
