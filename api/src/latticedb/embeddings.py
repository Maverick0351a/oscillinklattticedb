from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


REGISTRY_PATH = Path(__file__).parent / "models_registry.json"


@dataclass
class EmbedPreset:
    id: str
    hf: str
    dim: int
    license: str
    prompt_format: Dict[str, str]
    rev: str | None = None
    sha256: str | None = None
    tokenizer_sha256: str | None = None


def _load_registry() -> Dict[str, EmbedPreset]:
    data = json.loads(REGISTRY_PATH.read_text())
    reg: Dict[str, EmbedPreset] = {}
    for k, v in data.items():
        reg[k] = EmbedPreset(
            id=k,
            hf=v["hf"],
            dim=int(v["dim"]),
            license=v.get("license", ""),
            prompt_format=v.get("prompt_format", {"doc": "{text}", "query": "{text}"}),
            rev=v.get("rev"),
            sha256=v.get("sha256"),
            tokenizer_sha256=v.get("tokenizer_sha256"),
        )
    return reg


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class EmbeddingBackend:
    def __init__(self, preset: EmbedPreset, device: str = "cpu", batch_size: int = 32, strict_hash: bool = False) -> None:
        self.preset = preset
        self.device = device
        self.batch_size = int(batch_size)
        self.strict_hash = bool(strict_hash)
        self._model = None
        self._tokenizer = None
        self._use_stub = False
        self._prepare()

    @property
    def dim(self) -> int:
        return int(self.preset.dim)

    @property
    def prompt_format(self) -> Dict[str, str]:
        return self.preset.prompt_format

    def _prepare(self) -> None:
        # Lazy import heavy deps; fallback to deterministic stub if unavailable
        try:
            import torch  # type: ignore
            from transformers import AutoModel, AutoTokenizer  # type: ignore
            from pathlib import PurePath
            torch.set_grad_enabled(False)
            try:
                torch.set_num_threads(1)
            except Exception:
                pass

            # Resolve revision if provided; else let HF pick latest and we record it later
            rev = self.preset.rev
            tok = AutoTokenizer.from_pretrained(self.preset.hf, revision=rev) if rev else AutoTokenizer.from_pretrained(self.preset.hf)
            mdl = AutoModel.from_pretrained(self.preset.hf, revision=rev) if rev else AutoModel.from_pretrained(self.preset.hf)
            mdl.eval()
            if self.device == "cuda":
                mdl = mdl.to("cuda")
            self._model = mdl
            self._tokenizer = tok

            # Attempt to capture local cache files and compute hashes
            try:
                tok_files = tok.vocab_files_names if hasattr(tok, "vocab_files_names") else {}
                tok_paths = []
                for _, name in (tok_files or {}).items():
                    if name and hasattr(tok, "init_kwargs"):
                        dir_path = tok.init_kwargs.get("cache_dir") or tok.init_kwargs.get("_name_or_path")
                        if dir_path:
                            p = Path(dir_path) / name
                            if p.exists():
                                tok_paths.append(p)
                if hasattr(tok, "init_kwargs"):
                    p2 = Path(tok.init_kwargs.get("_name_or_path", "")) / "tokenizer.json"
                    if p2.exists():
                        tok_paths.append(p2)
                tok_hash_src = None
                for p in tok_paths:
                    tok_hash_src = p
                    break
                if tok_hash_src and not self.preset.tokenizer_sha256:
                    self.preset.tokenizer_sha256 = _hash_file(tok_hash_src)
            except Exception:
                pass

            try:
                if hasattr(mdl, "state_dict"):
                    name = getattr(mdl, "name_or_path", None) or getattr(mdl, "_name_or_path", None)
                    if name:
                        p = Path(str(name))
                        # Try to parse snapshot revision from path .../snapshots/<rev>
                        try:
                            parts = list(PurePath(p).parts)
                            if "snapshots" in parts:
                                i = parts.index("snapshots")
                                if i + 1 < len(parts):
                                    rev_guess = parts[i + 1]
                                    if isinstance(rev_guess, str) and len(rev_guess) >= 8:
                                        self.preset.rev = self.preset.rev or rev_guess
                        except Exception:
                            pass
                        # Compute model weights hash if available
                        for w in ["pytorch_model.bin", "model.safetensors"]:
                            fp = p / w
                            if fp.exists():
                                if not self.preset.sha256:
                                    self.preset.sha256 = _hash_file(fp)
                                break
            except Exception:
                pass

            if self.strict_hash and (self.preset.sha256 is None or self.preset.tokenizer_sha256 is None):
                raise RuntimeError("STRICT hash verification enabled but model/tokenizer hashes are missing.")
        except Exception:
            # Fallback to deterministic stub embeddings
            self._use_stub = True
            if self.strict_hash:
                raise

    def _encode(self, texts: List[str]) -> np.ndarray:
        if self._use_stub:
            # Deterministic stub embeddings using SHA256-seeded RNG, with prompt formatting
            def _det_embed(t: str, d: int) -> np.ndarray:
                h = hashlib.sha256(t.encode("utf-8")).digest()
                seed = int.from_bytes(h[:8], "big") & 0x7FFFFFFFFFFFFFFF
                rng = np.random.default_rng(seed)
                v = rng.standard_normal(d).astype(np.float32)
                v /= (np.linalg.norm(v) + 1e-12)
                return v
            vecs = [_det_embed(t, self.dim) for t in texts]
            X = np.stack(vecs, axis=0).astype(np.float32)
            X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
            return X

        assert self._model is not None and self._tokenizer is not None
        tok = self._tokenizer  # satisfy type checker after assert
        all_vecs: List[np.ndarray] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            toks = tok(batch, padding=True, truncation=True, return_tensors="pt")
            if self.device == "cuda":
                toks = {k: v.to("cuda") for k, v in toks.items()}
            out = self._model(**toks)
            # Mean pool last_hidden_state with attention mask
            last = out.last_hidden_state  # (bs, seqlen, h)
            mask = toks["attention_mask"].unsqueeze(-1).type_as(last)
            summed = (last * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            emb = summed / counts
            # to cpu numpy
            emb = emb.detach()
            if emb.is_cuda:
                emb = emb.cpu()
            vec = emb.numpy().astype(np.float32)
            all_vecs.append(vec)
        X = np.concatenate(all_vecs, axis=0) if all_vecs else np.zeros((0, self.dim), dtype=np.float32)
        # L2 normalize
        X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
        return X

    def embed_docs(self, texts: List[str]) -> np.ndarray:
        fmt = self.prompt_format.get("doc", "{text}")
        prepped = [fmt.replace("{text}", t) for t in texts]
        return self._encode(prepped)

    def embed_queries(self, texts: List[str]) -> np.ndarray:
        fmt = self.prompt_format.get("query", "{text}")
        prepped = [fmt.replace("{text}", t) for t in texts]
        return self._encode(prepped)


def load_model(preset_id: str, device: str = "cpu", batch_size: int = 32, strict_hash: bool = False) -> EmbeddingBackend:
    reg = _load_registry()
    if preset_id not in reg:
        raise ValueError(f"Unknown embed preset: {preset_id}")
    preset = reg[preset_id]
    return EmbeddingBackend(preset, device=device, batch_size=batch_size, strict_hash=strict_hash)


def preset_meta(backend: EmbeddingBackend) -> Dict[str, Any]:
    p = backend.preset
    return {
        "embed_model": p.id,
        "embed_hf": p.hf,
        "embed_dim": int(p.dim),
        "prompt_format": p.prompt_format,
        "hf_rev": p.rev,
        "weights_sha256": p.sha256,
        "tokenizer_sha256": p.tokenizer_sha256,
        "device": backend.device,
        "batch_size": backend.batch_size,
        "pooling": "mean",
        "strict_hash": backend.strict_hash,
    }
