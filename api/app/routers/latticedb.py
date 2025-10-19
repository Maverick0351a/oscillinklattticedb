"""LatticeDB core endpoints: ingest, route, compose, verify, chat, scan.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

from ..core.config import settings
from ..auth.jwt import auth_guard
from ..schemas import IngestReq, RouteReq, ComposeReq, VerifyReq, ChatReq, ScanReq
from ..core.metrics import SPD_DELTAH_LAST, SPD_RESIDUAL_LAST
from latticedb.ingest import ingest_dir
from latticedb.router import Router
from latticedb.receipts import CompositeReceipt
from latticedb.verify import verify_composite
from latticedb.watcher import single_scan as watcher_single_scan


router = APIRouter(tags=["latticedb"])


@router.post("/v1/latticedb/ingest", summary="Ingest documents into lattice store")
def api_ingest(req: IngestReq, _auth=auth_guard()):
    dim = req.dim or settings.spd_dim
    k = req.k or settings.spd_k_neighbors
    lamG = req.lambda_G or settings.spd_lambda_G
    lamC = req.lambda_C or settings.spd_lambda_C
    lamQ = req.lambda_Q or settings.spd_lambda_Q
    tol = req.tol or settings.spd_tol
    max_iter = req.max_iter or settings.spd_max_iter
    em = req.embed_model or settings.embed_model
    edev = req.embed_device or settings.embed_device
    ebsz = int(req.embed_batch_size or settings.embed_batch_size)
    estrict = bool(req.embed_strict_hash if req.embed_strict_hash is not None else settings.embed_strict_hash)
    receipts = ingest_dir(
        Path(req.input_dir),
        Path(req.out_dir),
        group_by="doc.section",
        dim=dim,
        k=k,
        lambda_G=lamG,
        lambda_C=lamC,
        lambda_Q=lamQ,
        tol=tol,
        max_iter=max_iter,
        embed_model=em,
        embed_device=edev,
        embed_batch_size=ebsz,
        embed_strict_hash=estrict,
    )
    if receipts:
        try:
            SPD_DELTAH_LAST.set(float(receipts[-1].deltaH_total))
            SPD_RESIDUAL_LAST.set(float(receipts[-1].final_residual))
        except Exception:
            pass
    from latticedb.merkle import merkle_root
    leaves = [r.state_sig for r in receipts]
    cfg_path = Path(req.out_dir)/"receipts"/"config.json"
    if cfg_path.exists():
        config_hash = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    else:
        config_hash = hashlib.sha256(b"stub-config").hexdigest()
    root = merkle_root(leaves + [config_hash])
    (Path(req.out_dir)/"receipts").mkdir(parents=True, exist_ok=True)
    (Path(req.out_dir)/"receipts/db_receipt.json").write_text(json.dumps({"version":"1","db_root":root,"config_hash":config_hash}, indent=2))
    return {"count": len(receipts), "db_root": root}


@router.post("/v1/latticedb/route", summary="Route query to candidate lattices")
def api_route(req: RouteReq):
    from latticedb.embeddings import load_model
    model_id = req.embed_model or settings.embed_model
    device = req.embed_device or settings.embed_device
    bsz = int(req.embed_batch_size or settings.embed_batch_size)
    strict = bool(req.embed_strict_hash if req.embed_strict_hash is not None else settings.embed_strict_hash)
    try:
        root = Path(req.db_path) if req.db_path else Path(settings.db_root)
        cfgp = root/"receipts"/"config.json"
        if cfgp.exists():
            cfg = json.loads(cfgp.read_text())
            model_id = str(cfg.get("embed_model", model_id))
    except Exception:
        pass
    be = load_model(model_id, device=device, batch_size=bsz, strict_hash=strict)
    v = be.embed_queries([req.q])[0]
    r = Router(root)
    cand = r.route(v, k=req.k_lattices)
    return {"candidates": [{"lattice_id": lid, "score": s} for lid,s in cand]}


@router.post("/v1/latticedb/compose", summary="Compose selected lattices into a context pack")
def api_compose(req: ComposeReq, _auth=auth_guard()):
    from latticedb.router import Router
    from latticedb.composite import composite_settle
    from latticedb.embeddings import load_model, preset_meta
    root = Path(req.db_path) if req.db_path else Path(settings.db_root)
    cents, ids = Router(root).load_centroids()
    id_to_idx = {lid:i for i,lid in enumerate(ids)}
    sel_idx = [id_to_idx[i] for i in req.lattice_ids if i in id_to_idx]
    k = req.k or settings.spd_k_neighbors
    lamG = req.lambda_G or settings.spd_lambda_G
    lamC = req.lambda_C or settings.spd_lambda_C
    lamQ = req.lambda_Q or settings.spd_lambda_Q
    tol = req.tol or settings.spd_tol
    max_iter = req.max_iter or settings.spd_max_iter
    dH, iters, resid, ehash = composite_settle(cents, sel_idx, k=k, lambda_G=lamG, lambda_C=lamC, lambda_Q=lamQ, tol=tol, max_iter=max_iter)

    try:
        cfgp = root/"receipts"/"config.json"
        q_meta = {}
        if cfgp.exists():
            cfg = json.loads(cfgp.read_text())
            model_id = str(cfg.get("embed_model", settings.embed_model))
            be = load_model(model_id, device=settings.embed_device, batch_size=int(settings.embed_batch_size), strict_hash=bool(settings.embed_strict_hash))
            q_meta = preset_meta(be)
    except Exception:
        q_meta = {}

    comp = CompositeReceipt.build(
        db_root=json.loads((root/'receipts/db_receipt.json').read_text())["db_root"],
        lattice_ids=[ids[i] for i in sel_idx],
        edge_hash_composite=ehash,
        deltaH_total=dH,
        cg_iters=iters,
        final_residual=resid,
        epsilon=req.epsilon,
        tau=req.tau,
        filters={},
        model_sha256=(q_meta.get("weights_sha256") or "stub-model-sha256"),
        embed_model=q_meta.get("embed_model"),
        embed_dim=q_meta.get("embed_dim"),
        prompt_format=q_meta.get("prompt_format"),
        hf_rev=q_meta.get("hf_rev"),
        tokenizer_sha256=q_meta.get("tokenizer_sha256"),
        device=q_meta.get("device"),
        batch_size=q_meta.get("batch_size"),
        pooling=q_meta.get("pooling"),
        strict_hash=q_meta.get("strict_hash"),
    )
    if not (resid <= req.epsilon and dH >= req.tau):
        return {"context_pack": {"question": req.q, "working_set": [], "receipts": {"composite": comp.model_dump()} }}

    citations = []
    for lid in comp.lattice_ids:
        group_dir = next((p for p in (root/"groups").glob("**/"+lid) if p.is_dir()), None)
        if not group_dir:
            continue
        import pandas as pd
        df = pd.read_parquet(group_dir/"chunks.parquet")
        if len(df)>0:
            citations.append({"lattice": lid, "text": str(df.iloc[0]["text"])[:200], "score": 0.8})
    return {"context_pack": {"question": req.q, "working_set": citations, "receipts": {"composite": comp.model_dump()} } }


@router.post("/v1/latticedb/verify", summary="Verify CompositeReceipt and lattice receipts")
def api_verify(req: VerifyReq):
    root = Path(req.db_path) if req.db_path else Path(settings.db_root)
    res = verify_composite(root/"receipts/db_receipt.json", req.composite, req.lattice_receipts)
    return res


def _build_prompt(question: str, citations: list[dict]) -> tuple[str, str]:
    parts = [
        "You are a careful assistant. Answer only from the provided context.",
        "If the answer is not in the context, say you don't have enough information.",
        "Context:",
    ]
    for i, c in enumerate(citations, start=1):
        snippet = str(c.get("text", ""))
        lid = c.get("lattice")
        parts.append(f"[{i}] (lattice:{lid}) {snippet}")
    parts.append("")
    parts.append(f"Question: {question}")
    parts.append("Answer:")
    prompt = "\n".join(parts)
    ph = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return prompt, ph


def _ollama_generate(endpoint: str, model: str, prompt: str, *, temperature: float, top_p: float, max_tokens: int, seed: int, timeout: float = 60.0):
    import json as _json
    from urllib import request as _req
    from urllib.error import URLError as _URLError, HTTPError as _HTTPError

    url = endpoint.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": max(0.0, float(temperature)),
            "top_p": max(0.0, float(top_p)),
            "num_predict": int(max(1, int(max_tokens))),
            "seed": int(seed),
        },
    }
    data = _json.dumps(payload).encode("utf-8")
    req = _req.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _req.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            obj = _json.loads(body)
            return {
                "ok": True,
                "answer": obj.get("response", ""),
                "tokens": {
                    "prompt": obj.get("prompt_eval_count"),
                    "completion": obj.get("eval_count"),
                },
                "raw": obj,
            }
    except (_HTTPError, _URLError) as e:
        return {"ok": False, "error": f"ollama_error: {type(e).__name__}: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"ollama_exception: {type(e).__name__}: {e}"}


@router.post("/v1/latticedb/chat", summary="Compose context and generate answer via local LLM (optional)")
def api_chat(req: ChatReq):
    if not settings.llm_enabled:
        raise HTTPException(status_code=400, detail="llm disabled; set LATTICEDB_LLM_ENABLED=1 to enable")

    r = api_route(RouteReq(db_path=req.db_path, q=req.q, k_lattices=req.k_lattices))
    cands = r.get("candidates", [])
    sel_ids: list[str] = [
        str(c["lattice_id"]) for c in cands[: max(0, int(req.select))]
        if isinstance(c.get("lattice_id"), str)
    ]
    comp = api_compose(ComposeReq(db_path=req.db_path, q=req.q, lattice_ids=sel_ids))
    pack = comp.get("context_pack", {})
    citations = pack.get("working_set", [])
    receipts = pack.get("receipts", {})

    prompt, prompt_sha256 = _build_prompt(req.q, citations)
    model = req.model or settings.llm_model
    temperature = settings.llm_temperature if req.temperature is None else req.temperature
    top_p = settings.llm_top_p if req.top_p is None else req.top_p
    max_tokens = settings.llm_max_tokens if req.max_tokens is None else req.max_tokens
    seed = settings.llm_seed if req.seed is None else req.seed

    if settings.llm_backend == "ollama":
        result = _ollama_generate(settings.llm_endpoint, model, prompt, temperature=temperature, top_p=top_p, max_tokens=max_tokens, seed=int(seed))
    else:
        raise HTTPException(status_code=400, detail=f"llm backend not supported in scaffold: {settings.llm_backend}")

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=str(result.get("error")))

    llm_prov = {
        "backend": settings.llm_backend,
        "endpoint": settings.llm_endpoint,
        "model": model,
        "temperature": float(temperature),
        "top_p": float(top_p),
        "max_tokens": int(max_tokens),
        "seed": int(seed),
        "prompt_sha256": prompt_sha256,
        "token_counts": result.get("tokens"),
    }

    return {
        "chat": {
            "question": req.q,
            "answer": result.get("answer", ""),
            "context_pack": {"question": pack.get("question", req.q), "working_set": citations, "receipts": receipts},
            "llm": llm_prov,
        }
    }


@router.post("/v1/db/scan", summary="Run a single watcher scan")
def api_db_scan(req: ScanReq, _auth=auth_guard()):
    root = Path(req.out_dir) if req.out_dir else Path(settings.db_root)
    res = watcher_single_scan(
        Path(req.input_dir),
        root,
        embed_model=req.embed_model or settings.embed_model,
        embed_device=req.embed_device or settings.embed_device,
        embed_batch_size=int(req.embed_batch_size or settings.embed_batch_size),
        embed_strict_hash=bool(req.embed_strict_hash if req.embed_strict_hash is not None else settings.embed_strict_hash),
    )
    return res
