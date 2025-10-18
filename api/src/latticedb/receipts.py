from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from .utils import state_sig

class LatticeReceipt(BaseModel):
    model_config = {"protected_namespaces": ()}
    version: str = "1"
    lattice_id: str
    group_id: str
    file_sha256: Optional[str] = None
    # Embedding provenance
    embed_model: Optional[str] = None
    embed_dim: Optional[int] = None
    prompt_format: Optional[dict] = None
    hf_rev: Optional[str] = None
    model_sha256: str = "stub-model-sha256"
    tokenizer_sha256: Optional[str] = None
    device: Optional[str] = None
    batch_size: Optional[int] = None
    pooling: Optional[str] = None
    strict_hash: Optional[bool] = None
    dim: int = 32
    lambda_G: float = 1.0
    lambda_C: float = 0.5
    lambda_Q: float = 4.0
    edge_hash: str
    deltaH_total: float
    cg_iters: int
    final_residual: float
    ocr_avg_confidence: Optional[float] = None
    ocr_low_confidence: Optional[bool] = None
    state_sig: str

    @staticmethod
    def from_core(**kwargs) -> "LatticeReceipt":
        tmp = LatticeReceipt(**kwargs, state_sig="")
        sig = state_sig(tmp.model_dump(exclude={"state_sig"}))
        tmp.state_sig = sig
        return tmp

class DBReceipt(BaseModel):
    model_config = {"protected_namespaces": ()}
    version: str = "1"
    db_root: str
    config_hash: str
    # Optional: merkle leaves included for verification convenience
    leaves: Optional[List[str]] = None

class CompositeReceipt(BaseModel):
    model_config = {"protected_namespaces": ()}
    version: str = "1"
    db_root: str
    lattice_ids: List[str]
    edge_hash_composite: str
    deltaH_total: float
    cg_iters: int
    final_residual: float
    epsilon: float
    tau: float
    filters: Dict[str, str] = Field(default_factory=dict)
    # Embedding provenance for query side
    embed_model: Optional[str] = None
    embed_dim: Optional[int] = None
    prompt_format: Optional[dict] = None
    hf_rev: Optional[str] = None
    model_sha256: str = "stub-model-sha256"
    tokenizer_sha256: Optional[str] = None
    device: Optional[str] = None
    batch_size: Optional[int] = None
    pooling: Optional[str] = None
    strict_hash: Optional[bool] = None
    state_sig: str

    @staticmethod
    def build(**kwargs) -> "CompositeReceipt":
        tmp = CompositeReceipt(**kwargs, state_sig="")
        tmp.state_sig = state_sig(tmp.model_dump(exclude={"state_sig"}))
        return tmp


class ShardReceipt(BaseModel):
    model_config = {"protected_namespaces": ()}
    version: str = "1"
    shard_id: str
    path: str
    size_bytes: int
    file_count: int
    active_backend: str = "jsonl"
    centroid_hash: Optional[str] = None
    sealed: bool | None = None
    index_meta: Optional[Dict[str, Any]] = None
    index_sha256: Optional[str] = None
    state_sig: str

    @staticmethod
    def build(**kwargs) -> "ShardReceipt":
        tmp = ShardReceipt(**kwargs, state_sig="")
        tmp.state_sig = state_sig(tmp.model_dump(exclude={"state_sig"}))
        return tmp