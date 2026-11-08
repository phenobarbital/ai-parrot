"""G1 check list in specification order (FEAT-824 section 2)."""

from __future__ import annotations

from checks.concurrency import check_g1_09_writers, check_g1_13_info
from checks.connection import check_g1_01_connect
from checks.graph import check_g1_11_traversal, check_g1_12_document_store
from checks.live import check_g1_07_live
from checks.schema import check_g1_02_schema
from checks.search import check_g1_03_bm25, check_g1_04_hnsw, check_g1_05_containsany, check_g1_06_rrf
from checks.transactions import check_g1_08_transaction, check_g1_10_failure_injection

ALL_CHECKS = [
    check_g1_01_connect,
    check_g1_02_schema,
    check_g1_03_bm25,
    check_g1_04_hnsw,
    check_g1_05_containsany,
    check_g1_06_rrf,
    check_g1_07_live,
    check_g1_08_transaction,
    check_g1_09_writers,
    check_g1_10_failure_injection,
    check_g1_11_traversal,
    check_g1_12_document_store,
    check_g1_13_info,
]
