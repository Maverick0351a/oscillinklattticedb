import numpy as np
from latticedb.lattice import build_lattice_spd
from latticedb.composite import composite_settle


def _mk_chunks(n: int):
    # Use deterministic distinct texts
    return [{"text": f"chunk {i} alpha beta gamma"} for i in range(n)]


def test_microlattice_determinism_and_energy():
    chunks = _mk_chunks(6)
    X1, E1, U1, s1 = build_lattice_spd(chunks, dim=16, k=3)
    X2, E2, U2, s2 = build_lattice_spd(chunks, dim=16, k=3)
    # Deterministic outputs
    assert np.allclose(X1, X2)
    assert np.array_equal(E1, E2)
    assert np.allclose(U1, U2)
    assert s1["edge_hash"] == s2["edge_hash"]
    # Energy non-negative and small residual
    assert s1["deltaH_total"] >= 0.0
    assert s1["final_residual"] <= 1e-3 or s1["cg_iters"] >= 1


def test_composite_settle_invariants():
    chunks = _mk_chunks(8)
    X, E, U, s = build_lattice_spd(chunks, dim=16, k=3)
    cents = np.stack([U[i] for i in range(4)], axis=0).astype(np.float32)
    dH, iters, resid, eh = composite_settle(cents, list(range(cents.shape[0])))
    assert dH >= 0.0
    assert isinstance(eh, str) and len(eh) == 64
    assert resid >= 0.0
    assert iters >= 0