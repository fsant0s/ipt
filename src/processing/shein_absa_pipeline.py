"""Pipeline partilhado: uma review (dict do shein.json) → PT→EN → PyABSA → GPT.

Usado por ``main.ipynb`` e ``scripts/run_shein_absa.py`` para manter o mesmo formato de saída.
"""

from __future__ import annotations

from typing import Any

from src.processing.openaigpt import gpt_categorize_aspects, gpt_translate_pt_to_en
from src.processing.pyabsa_multilingual import pyabsa_multilingual_predict_raw

__all__ = ("run_shein_absa_for_row",)


def run_shein_absa_for_row(r: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Executa tradução, PyABSA e categorização GPT.

    Retorna ``(texto_en, resultado)`` onde ``resultado`` é
    ``{"texto_original", "aspectos": [{ "aspecto_detectado", "sentimento", "confiança_modelo", "pilar", "resumo_aspecto" }, ...]}``.
    """
    t = (r.get("title") or "").strip()
    body = (r.get("review") or "").strip()
    combined_pt = f"{t}. {body}".strip() if t else body

    texto_en = gpt_translate_pt_to_en(combined_pt)
    raw = pyabsa_multilingual_predict_raw(texto_en)
    aspects = raw.get("aspect", [])
    sentiments = raw.get("sentiment", [])
    confidences = raw.get("confidence") or []

    result = gpt_categorize_aspects(
        texto_original=combined_pt,
        review_en=texto_en,
        pilar_id=r.get("pillar", ""),
        pilar_label=r.get("pillar_label", ""),
        aspects=aspects,
        sentiments=sentiments,
        confidences=confidences,
    )
    return texto_en, result
