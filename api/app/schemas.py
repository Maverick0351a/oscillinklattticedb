"""Pydantic request/response schemas.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

from pydantic import BaseModel


class IngestReq(BaseModel):
    input_dir: str
    out_dir: str = "latticedb"
    # Optional overrides
    dim: int | None = None
    k: int | None = None
    lambda_G: float | None = None
    lambda_C: float | None = None
    lambda_Q: float | None = None
    tol: float | None = None
    max_iter: int | None = None
    # Embedding options
    embed_model: str | None = None
    embed_device: str | None = None
    embed_batch_size: int | None = None
    embed_strict_hash: bool | None = None


class RouteReq(BaseModel):
    db_path: str | None = None
    q: str
    k_lattices: int = 8
    embed_model: str | None = None
    embed_device: str | None = None
    embed_batch_size: int | None = None
    embed_strict_hash: bool | None = None


class ComposeReq(BaseModel):
    db_path: str | None = None
    q: str
    lattice_ids: list[str]
    epsilon: float = 1e-3
    tau: float = 0.30
    # Optional overrides for composite settle
    k: int | None = None
    lambda_G: float | None = None
    lambda_C: float | None = None
    lambda_Q: float | None = None
    tol: float | None = None
    max_iter: int | None = None


class VerifyReq(BaseModel):
    db_path: str | None = None
    composite: dict
    lattice_receipts: dict


class ChatReq(BaseModel):
    db_path: str | None = None
    q: str
    k_lattices: int = 8
    select: int = 6
    # LLM overrides (optional)
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None


class LatticeMetadataReq(BaseModel):
    db_path: str | None = None
    display_name: str


class ScanReq(BaseModel):
    input_dir: str
    out_dir: str | None = None
    embed_model: str | None = None
    embed_device: str | None = None
    embed_batch_size: int | None = None
    embed_strict_hash: bool | None = None
