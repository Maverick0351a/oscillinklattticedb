import hashlib
from typing import List

def merkle_root(leaves: List[str]) -> str:
    # Compute binary Merkle root over hex leaves (sha256 hex strings).
    if not leaves:
        return hashlib.sha256(b"").hexdigest()
    layer = [bytes.fromhex(x) for x in sorted(leaves)]
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer), 2):
            a = layer[i]
            b = layer[i+1] if i+1 < len(layer) else a
            nxt.append(hashlib.sha256(a + b).digest())
        layer = nxt
    return layer[0].hex()