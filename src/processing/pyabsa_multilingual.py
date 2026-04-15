"""Única API pública: `pyabsa_multilingual_predict_raw`. O resto são detalhes de implementação."""

from __future__ import annotations

import re
import sys
import types
from functools import lru_cache
from typing import Any

from src.utils.helpers import checkpoints_dir


def _disable_dataloader_pin_memory_on_mps() -> None:
    """PyABSA usa DataLoader(..., pin_memory=True); no MPS o PyTorch avisa e ignora pin mesmo assim."""
    import torch
    from torch.utils.data import DataLoader

    _orig = DataLoader.__init__

    def _init(self, *args, pin_memory: bool = False, **kwargs) -> None:
        if pin_memory:
            mps = getattr(torch.backends, "mps", None)
            if mps is not None and mps.is_available():
                pin_memory = False
        _orig(self, *args, pin_memory=pin_memory, **kwargs)

    DataLoader.__init__ = _init  # type: ignore[method-assign]


_disable_dataloader_pin_memory_on_mps()

__all__ = ("pyabsa_multilingual_predict_raw",)

# Limite de caracteres na entrada (demo HF Gradio ~3000).
_INFER_MAX_CHARS = 3000
# Limite de frases após segmentação (textos longos sem isso tendem a [] no ATEPC).
_MAX_SENTS = 80
_TOKENIZER_SHIM = "transformers.models.deberta_v2.tokenization_deberta_v2_fast"


def _empty_result(sentence: str = "") -> dict[str, Any]:
    return {"aspect": [], "sentiment": [], "confidence": [], "sentence": sentence}


def _deberta_tokenizer_shim() -> None:
    """Tokenizer esperado pelo unpickle do checkpoint (transformers 5.x mudou o layout)."""
    if _TOKENIZER_SHIM in sys.modules:
        return
    try:
        import importlib

        sys.modules[_TOKENIZER_SHIM] = importlib.import_module(_TOKENIZER_SHIM)
        return
    except ImportError:
        pass
    from transformers.models.deberta_v2 import (  # noqa: PLC0415
        tokenization_deberta_v2 as deberta_v2_tok,
    )

    mod = types.ModuleType("tokenization_deberta_v2_fast")
    mod.DebertaV2TokenizerFast = deberta_v2_tok.DebertaV2Tokenizer
    sys.modules[_TOKENIZER_SHIM] = mod


def _resolve_atepc_checkpoint(checkpoint: str) -> str:
    """
    Usa `checkpoints/ATEPC_MULTILINGUAL_CHECKPOINT` na raiz do projeto (caminho absoluto),
    para não depender do cwd.
    """
    if checkpoint != "multilingual":
        return checkpoint
    local = checkpoints_dir() / "ATEPC_MULTILINGUAL_CHECKPOINT"
    if not local.is_dir():
        return checkpoint
    if not any(local.glob("*.config")):
        return checkpoint
    return str(local.resolve())


@lru_cache(maxsize=1)
def _extractor(checkpoint: str) -> Any:
    _deberta_tokenizer_shim()
    from pyabsa import AspectTermExtraction as atepc  # noqa: PLC0415

    resolved = _resolve_atepc_checkpoint(checkpoint)
    return atepc.AspectExtractor(checkpoint=resolved)


@lru_cache(maxsize=1)
def _nlp_en() -> Any:
    import spacy  # noqa: PLC0415

    return spacy.load("en_core_web_sm")


def _sentences(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    try:
        nlp = _nlp_en()
        doc = nlp(t)
        out = [s.text.strip() for s in doc.sents if s.text.strip()]
    except Exception:  # noqa: BLE001
        out = [p.strip() for p in re.split(r"(?<=[.!?])\s+", t) if p.strip()]
    if len(out) > _MAX_SENTS:
        out = out[:_MAX_SENTS]
    return out


def _merge_blocks(blocks: list[dict[str, Any]], *, full_text: str) -> dict[str, Any]:
    aspects: list[str] = []
    sentiments: list[str] = []
    confidences: list[float] = []
    seen: set[tuple[str, str]] = set()

    for block in blocks:
        if not isinstance(block, dict):
            continue
        terms = list(block.get("aspect") or [])
        pols = list(block.get("sentiment") or [])
        confs = list(block.get("confidence") or [])
        for i, term in enumerate(terms):
            term_s = str(term).strip()
            if not term_s:
                continue
            pol_s = str(pols[i]).strip() if i < len(pols) else "Neutral"
            key = (term_s.lower(), pol_s.lower())
            if key in seen:
                continue
            seen.add(key)
            aspects.append(term_s)
            sentiments.append(pol_s)
            try:
                confidences.append(float(confs[i]) if i < len(confs) else 0.0)
            except (TypeError, ValueError):
                confidences.append(0.0)

    return {
        "aspect": aspects,
        "sentiment": sentiments,
        "confidence": confidences,
        "sentence": full_text,
    }


def _predict_batch(extractor: Any, sents: list[str]) -> list[dict[str, Any]]:
    if len(sents) == 1:
        out = extractor.predict(
            sents[0],
            save_result=False,
            print_result=False,
            pred_sentiment=True,
        )
        return [out] if isinstance(out, dict) else list(out)
    batch = extractor.predict(
        sents,
        save_result=False,
        print_result=False,
        pred_sentiment=True,
    )
    return batch if isinstance(batch, list) else [batch]


def _predict_atepc(text_en: str, *, checkpoint: str) -> dict[str, Any]:
    ext = _extractor(checkpoint)
    text_en = (text_en or "").strip()
    if not text_en:
        return _empty_result()

    sents = _sentences(text_en)
    if not sents:
        return _empty_result(text_en)

    blocks = _predict_batch(ext, sents)
    merged = _merge_blocks(blocks, full_text=text_en)
    if merged["aspect"]:
        return merged

    fb = ext.predict(
        text_en,
        save_result=False,
        print_result=False,
        pred_sentiment=True,
    )
    if isinstance(fb, dict) and (fb.get("aspect") or []):
        return {
            "aspect": list(fb.get("aspect") or []),
            "sentiment": list(fb.get("sentiment") or []),
            "confidence": list(fb.get("confidence") or []),
            "sentence": str(fb.get("sentence") or text_en),
        }
    return merged


def pyabsa_multilingual_predict_raw(
    text_en: str,
    *,
    checkpoint: str = "multilingual",
) -> dict[str, Any]:
    """
    ATEPC `multilingual` (PyABSA). Entrada: inglês.
    Retorno: `aspect`, `sentiment`, `confidence`, `sentence`.
    """
    clipped = (text_en or "").strip()[:_INFER_MAX_CHARS]
    return _predict_atepc(clipped, checkpoint=checkpoint)
