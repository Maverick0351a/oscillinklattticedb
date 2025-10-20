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
- model_sha256, state_sig (computed as above)
 - retrieval_backend (optional): backend id like "faiss:flat", "hnswlib", "bm25:tantivy", or "hybrid"
 - retrieval_params (optional): params used (e.g., weights for hybrid)

## Verification flow
1. Recompute sha256 over CompositeReceipt normalized JSON → compare to state_sig.
2. Recompute Merkle root over referenced LatticeReceipt.state_sig values + config_hash → compare to DB root in `db_receipt.json`.
3. Return verified true/false with reason.