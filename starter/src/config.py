"""Central configuration: paths, corpus scope, model and the three strategies.

Every strategy uses the same corpus, embedding model, vector store and metric.
Only chunking (A vs B) or metadata filtering (B vs C) changes.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

STARTER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STARTER_DIR.parent
load_dotenv(STARTER_DIR / ".env")

# ---- Corpus -----------------------------------------------------------------
# The PDF is copyrighted and is NOT committed (see .gitignore and data/manifest.json).
# Default location: starter/data/raw/harrypotter.pdf. CORPUS_PDF in .env overrides it.
# Older locations are still accepted so an existing checkout keeps working.
CORPUS_CANDIDATES = [
    STARTER_DIR / "data" / "raw" / "harrypotter.pdf",
    STARTER_DIR / "data" / "harrypotter.pdf",
    REPO_ROOT / "data" / "raw" / "harrypotter.pdf",
    REPO_ROOT / "harrypotter.pdf",
]
_env_pdf = os.getenv("CORPUS_PDF")
CORPUS_PDF = Path(_env_pdf) if _env_pdf else next((p for p in CORPUS_CANDIDATES if p.exists()),
                                                  CORPUS_CANDIDATES[0])
if not CORPUS_PDF.is_absolute():
    CORPUS_PDF = (STARTER_DIR / CORPUS_PDF).resolve()  # relative CORPUS_PDF = relative to starter/
SOURCE_ID = "hp-complete-collection-pottermore"
SOURCE_NAME = "harrypotter.pdf"
# Books included (1 = Sorcerer's Stone ... 7). Books 1-3 keep CPU embedding time small
# while giving >900 content pages and three distinct values for the `book_no` filter.
BOOKS = [int(b) for b in (os.getenv("BOOKS") or "1,2,3").split(",")]

# ---- Paths ------------------------------------------------------------------
DATA_DIR = REPO_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"          # gitignored: contains book text
INDEX_DIR = DATA_DIR / "index" / "chroma"       # gitignored: contains book text
MANIFEST_FILE = DATA_DIR / "manifest.json"      # committed: no book text
BENCHMARK_FILE = REPO_ROOT / "benchmark" / "questions.json"
RESULTS_DIR = REPO_ROOT / "results"
PRIVATE_RESULTS_DIR = RESULTS_DIR / "private"   # gitignored: full chunk text for audit
EXPERIMENT_LOG = REPO_ROOT / "artifacts" / "experiment_log.csv"

# Committed traces keep only a short snippet of each chunk (copyright).
TRACE_SNIPPET_CHARS = 160

# ---- Embedding model (local, no API key, no data leaves the machine) ---------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "intfloat/multilingual-e5-small"
EMBED_BATCH_SIZE = 32
# E5 models expect these prefixes (see the model card).
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

# ---- Vector store ---------------------------------------------------------------
# "pgvector" (default, starter docker compose) or "chroma" (local folder data/index/chroma).
VECTOR_STORE = (os.getenv("VECTOR_STORE") or "pgvector").lower()
DATABASE_URL = os.getenv("DATABASE_URL")

# ---- Retrieval ----------------------------------------------------------------
TOP_K = 3
FILTER_FIELDS = {"book_no"}  # metadata fields a question may filter on

# Every chunk carries these fields (GUIDE: record type, value source and reason).
METADATA_SCHEMA = [
    {"field": "document_id", "type": "text", "value_source": f"constant '{SOURCE_ID}' (one PDF)",
     "purpose": "trace back to the source document"},
    {"field": "source", "type": "text", "value_source": "PDF file name",
     "purpose": "trace back to the file"},
    {"field": "page", "type": "int", "value_source": "physical PDF page (1-based) where the chunk starts",
     "purpose": "trace + gold-page matching"},
    {"field": "page_end", "type": "int", "value_source": "physical PDF page where the chunk ends",
     "purpose": "chunks may cross a page break; gold page may be either page"},
    {"field": "book_no", "type": "int (1-3)",
     "value_source": "PDF outline: order of top-level 'Harry Potter and ...' bookmarks",
     "purpose": "FILTER: many answers differ per book and readers know which book they are reading"},
    {"field": "book_title", "type": "text", "value_source": "PDF outline bookmark title", "purpose": "display"},
    {"field": "chapter_no", "type": "int", "value_source": "PDF outline 'Chapter N - Title'",
     "purpose": "trace; indexed column, not used as a benchmark filter"},
    {"field": "chapter_title", "type": "text", "value_source": "PDF outline", "purpose": "trace / display"},
    {"field": "text_sha1, char_count, chunk_index, stream_start, stream_end", "type": "text / int",
     "value_source": "computed by the chunker", "purpose": "idempotent re-ingest, audit sampling"},
]

STRATEGIES = {
    "A": {"chunking": "fixed", "size": 500, "overlap": 50, "use_filter": False,
          "collection": "hp_A_fixed500",
          "hypothesis": "Baseline: fixed windows cut sentences/dialogue; expect lower coherence."},
    "B": {"chunking": "paragraph", "max_size": 1000, "use_filter": False,
          "collection": "hp_B_para1000",
          "hypothesis": "Paragraph packing keeps whole ideas; expect better coherence and Hit@3 than A."},
    "C": {"chunking": "paragraph", "max_size": 1000, "use_filter": True,
          "collection": "hp_C_para1000_filter",
          "hypothesis": "Same chunks as B + book_no filter when the question supplies it; "
                        "expect gains on questions whose answer differs per book."},
}

SEED = 6
