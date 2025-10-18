# SPD Formulation (Micro and Composite)

This document summarizes the symmetric positive-definite (SPD) formulation used in the micro-lattice and composite settle.

## Graph and Laplacian
- Build a mutual-kNN graph over normalized embeddings (cosine similarity).
- Edge set E is undirected with unique (i<j) indexing for determinism.
- The unnormalized graph Laplacian L satisfies (L U)_i = ∑_{j:(i,j)∈E} (u_i - u_j).

## Energy and System Matrix
Given:
- X ∈ R^{n×d}: input embeddings (rows unit-normalized)
- U ∈ R^{n×d}: unknowns (solved positions)
- q ∈ R^{d}: pin target (micro: centroid of X; composite: either centroid or query vector)
- b ∈ {0,1}^n: pin mask (top-10% by cosine to q)
- λG, λC, λQ > 0 (defaults λG=1.0, λC=0.5, λQ=4.0)

Energy per dimension:
H(U) = 0.5 [ λG ||U−X||² + λC ∑_{(i,j)∈E} ||u_i−u_j||² + λQ ∑_i b_i ||u_i−q||² ]

Normal equations yield an SPD system:
M = λG I + λC L + λQ B,   where B = diag(b)

Right-hand side per coordinate j:
rhs_j = λG X[:,j] + λQ b q[j]

## Solver
- Conjugate Gradient with Jacobi preconditioner M_diag = diag(M).
- Warm start x0 = X[:,j].
- Solve for each coordinate (column) independently; assemble U.

## Invariants and Accounting
- ΔH_total = H(X) − H(U) ≥ 0 (clamped at 0 for numerical safety). Stored in receipts.
- cg_iters and final_residual stored for transparency.
- Edge hashes: sha256 of edges index buffer for micro and composite.

## Determinism
- Embeddings: deterministic stub via SHA256-seeded RNG and unit normalization.
- Mutual-kNN: stable sorting; mutual requirement reduces asymmetry.
- Canonical JSON for receipts; sha256 over receipt fields (excluding state_sig) materials the state signature.
- Config parameters written canonically into receipts/config.json and included in DB receipt Merkle root.
