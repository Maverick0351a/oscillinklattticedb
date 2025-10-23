# Receipts & Verification

This project issues cryptographically verifiable receipts for both micro-lattice builds and query-time composite settles.

## LatticeReceipt (per micro-lattice)

Fields (subset):
- version: "1"
- lattice_id, group_id
- dim, lambda_G, lambda_C, lambda_Q
- edge_hash: sha256 of the packed edge index array (mutual-kNN)
- deltaH_total: total energy reduction after SPD solve (≥ 0)
- cg_iters, final_residual: CG solver stats
- file_sha256: source file hash (if present)
- model_sha256: embedder/model hash (stubbed here)
- state_sig: sha256 over canonical JSON of the receipt fields (excluding state_sig)

Energy formulation (with U the solved positions, X the embeddings, q the pin target, b the pin mask):

H(U) = 0.5 [ λG ||U−X||² + λC ∑(i,j)∈E ||u_i−u_j||² + λQ ∑_i b_i ||u_i − q||² ]

deltaH_total = H(X) − H(U) and is clamped at ≥ 0 for numerical safety.

## DBReceipt (database-level)

Stored at `latticedb/receipts/db_receipt.json` and contains:
- db_root: Merkle root over all LatticeReceipt.state_sig values and the normalized `config.json`
- config_hash: sha256 of `receipts/config.json`

## CompositeReceipt (query-time settle)

Fields (subset):
- db_root, lattice_ids
- edge_hash_composite: sha256 over composite graph edges
- deltaH_total, cg_iters, final_residual
- epsilon, tau (gating thresholds)
- filters: optional selection filters applied
	- with ACL enabled, this captures `tenant` and comma-joined `roles` used to filter candidates (for audit).
- model_sha256, state_sig (computed as above)
 - retrieval_backend (optional): backend id like "faiss:flat", "hnswlib", "bm25:tantivy", or "hybrid"
 - retrieval_params (optional): params used (e.g., weights for hybrid)

## IndexReceipt (per shard index)

Stored at `indexes/<shard_id>/sealed/index_receipt.json` and emitted by each retrieval adapter when an index is sealed. Minimal fields:

- version: 1
- backend_id: adapter id (e.g., "faiss_flat_l2", "hnswlib", "bm25:tantivy")
- backend_version: adapter/lib version (if available)
- params: dict of index parameters (e.g., `{type: flat_l2, dim: 32}` or `{M: 32, efConstruction: 200}`)
- index_hash: sha256 over the sealed index directory contents (paths sorted)
- training_hash: optional sha256 of training data (None for flat indexes)
- shard_id: the shard the index belongs to (when emitted by the watcher)

Operational API:
- GET `/v1/index/receipt/{shard_id}` → returns the receipt JSON for auditing.

## Verification flow
1. Recompute sha256 over CompositeReceipt normalized JSON → compare to state_sig.
2. Recompute Merkle root over referenced LatticeReceipt.state_sig values + config_hash → compare to DB root in `db_receipt.json`.
3. Return verified true/false with reason.