from __future__ import annotations

import numpy as np
import pytest

from latticedb.embeddings import load_model


def test_embed_stub_is_deterministic_and_normalized():
    be = load_model("bge-small-en-v1.5", device="cpu", batch_size=8, strict_hash=False)
    v1 = be.embed_docs(["hello world"])[0]
    v2 = be.embed_docs(["hello world"])[0]
    # deterministic and unit-normalized
    assert np.allclose(v1, v2)
    nrm = np.linalg.norm(v1)
    assert np.isclose(nrm, 1.0, atol=1e-5)


def test_embed_prompt_formats_doc_vs_query_differs():
    be = load_model("bge-small-en-v1.5", device="cpu", batch_size=8, strict_hash=False)
    vd = be.embed_docs(["same text"])[0]
    vq = be.embed_queries(["same text"])[0]
    # prompt prefixes differ -> embeddings should differ with the deterministic stub
    assert not np.allclose(vd, vq)


def test_strict_hash_raises_when_backend_unavailable():
    # In environments without transformers/torch, strict_hash should surface an error
    with pytest.raises(Exception):
        load_model("bge-small-en-v1.5", device="cpu", batch_size=4, strict_hash=True)
