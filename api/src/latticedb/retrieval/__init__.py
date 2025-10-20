"""Retrieval adapters (optional).
SPDX-License-Identifier: BUSL-1.1

Backends:
- faiss_backend: exact flat search with numpy fallback
- hnswlib_backend: ANN via hnswlib (optional dependency)
- bm25_tantivy_backend: lexical BM25 via tantivy (optional dependency)
- hybrid: deterministic blend of vector and lexical scores
"""

__all__: list[str] = []
