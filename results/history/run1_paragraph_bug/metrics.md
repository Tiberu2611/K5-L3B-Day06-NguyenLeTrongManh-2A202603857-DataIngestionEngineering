# Retrieval metrics (auto-generated)

Run: 2026-11-14T03:41:20+00:00 · model `intfloat/multilingual-e5-small` · top-3 · benchmark sha256 `15c9394a9ad2`

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | MRR@3 | Filter compliant | Chunks | Embed+write (s) | Cost |
|---|---|---|---|---|---|---|---|---|
| A | all | 3/20 | 8/20 | 0.267 | 0/5 | 3476 | 495.3 | $0 |
| A | dev | 3/15 | 6/15 | 0.289 | 0/3 | 3476 | 495.3 | $0 |
| A | test | 0/5 | 2/5 | 0.2 | 0/2 | 3476 | 495.3 | $0 |
| B | all | 5/20 | 11/20 | 0.392 | 0/5 | 1831 | 451.3 | $0 |
| B | dev | 4/15 | 10/15 | 0.456 | 0/3 | 1831 | 451.3 | $0 |
| B | test | 1/5 | 1/5 | 0.2 | 0/2 | 1831 | 451.3 | $0 |
| C | all | 6/20 | 11/20 | 0.417 | 5/5 | 1831 | 4.6 | $0 |
| C | dev | 5/15 | 10/15 | 0.489 | 3/3 | 1831 | 4.6 | $0 |
| C | test | 1/5 | 1/5 | 0.2 | 2/2 | 1831 | 4.6 | $0 |

## Per-question Hit@3 (1 = evidence hit in top-3)

| ID | Split | Type | Filter | A | B | C |
|---|---|---|---|---|---|---|
| q01 | dev | truc_tiep |  | 1 (r1) | 1 (r1) | 1 (r1) |
| q02 | dev | dien_dat_lai |  | 0 · right_page_but_evidence_missing | 0 · right_page_but_evidence_missing | 0 · right_page_but_evidence_missing |
| q03 | dev | truc_tiep |  | 0 · wrong_location | 1 (r2) | 1 (r2) |
| q04 | dev | dien_dat_lai |  | 1 (r1) | 0 · right_page_but_evidence_missing | 0 · right_page_but_evidence_missing |
| q05 | dev | truc_tiep |  | 1 (r2) | 1 (r2) | 1 (r2) |
| q06 | dev | dien_dat_lai |  | 0 · evidence_split_across_chunks | 0 · wrong_location | 0 · wrong_location |
| q07 | dev | dieu_kien |  | 0 · wrong_location | 0 · right_page_but_evidence_missing | 0 · right_page_but_evidence_missing |
| q08 | dev | dien_dat_lai |  | 1 (r3) | 1 (r2) | 1 (r2) |
| q09 | dev | dien_dat_lai |  | 1 (r2) | 1 (r1) | 1 (r1) |
| q10 | dev | truc_tiep |  | 0 · right_page_but_evidence_missing | 1 (r1) | 1 (r1) |
| q11 | dev | dien_dat_lai |  | 0 · right_page_but_evidence_missing | 1 (r2) | 1 (r2) |
| q12 | dev | truc_tiep |  | 0 · wrong_location | 1 (r3) | 1 (r3) |
| q13 | dev | metadata_filter | {'book_no': 1} | 0 · wrong_location | 0 · wrong_location | 0 · wrong_location |
| q14 | dev | metadata_filter | {'book_no': 1} | 0 · evidence_split_across_chunks | 1 (r1) | 1 (r1) |
| q15 | dev | metadata_filter | {'book_no': 3} | 1 (r1) | 1 (r2) | 1 (r1) |
| q16 | test | metadata_filter | {'book_no': 3} | 0 · evidence_split_across_chunks | 0 · wrong_location | 0 · right_page_but_evidence_missing |
| q17 | test | metadata_filter | {'book_no': 1} | 0 · right_page_but_evidence_missing | 0 · wrong_location | 0 · right_page_but_evidence_missing |
| q18 | test | dien_dat_lai |  | 0 · evidence_split_across_chunks | 0 · right_page_but_evidence_missing | 0 · right_page_but_evidence_missing |
| q19 | test | dieu_kien |  | 1 (r2) | 1 (r1) | 1 (r1) |
| q20 | test | dieu_kien |  | 1 (r2) | 0 · wrong_location | 0 · wrong_location |
