# Architecture

User → UI (React) → FastAPI
                  ├─ /v1/latticedb/ingest   (build micro-lattices with SPD, write receipts, update manifest)
                  ├─ /v1/latticedb/route    (route queries via centroid cosine similarity)
                  ├─ /v1/latticedb/compose  (SPD settle over selected centroids, optional gating)
                  ├─ /v1/latticedb/verify   (Merkle verification of receipts/config)
                  └─ /health, /readyz, /metrics

Store layout (append-only):
```
latticedb/
  manifest.parquet             # groups, lattice ids, meta (edge_hash, deltaH_total, source_file, etc.)
  groups/
    G-000001/
      L-000001/
        chunks.parquet
        embeds.f32
        edges.bin
        ustar.f32
        receipt.json
  router/
    centroids.f32
    meta.parquet
  receipts/
    config.json                # normalized build parameters
    db_receipt.json            # Merkle root over lattice state_sigs + config
```

SPD formulation:
- Mutual-kNN graph over embeddings (cosine), Laplacian L.
- System M = λG I + λC L + λQ B (pinning to centroid/query), solved with CG + Jacobi preconditioner.
- Energy H(U) tracked; receipts store ΔH_total, cg_iters, residual, and edge hashes.

Determinism:
- Deterministic embeddings (stub), mutual-kNN with stable sorts, normalized vectors, canonical JSON, sha256 over receipts & config.