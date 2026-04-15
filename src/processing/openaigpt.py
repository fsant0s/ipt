"""ChatGPT: tradução PT→EN e categorização de aspectos ABSA por pilar."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

__all__ = ("gpt_translate_pt_to_en", "gpt_categorize_aspects")


@lru_cache(maxsize=1)
def _client() -> Any:
    from openai import OpenAI  # noqa: PLC0415
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _chat(prompt: str, *, model: str = "gpt-4o-mini") -> str:
    resp = _client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


def gpt_translate_pt_to_en(text: str, *, max_chars: int = 6000) -> str:
    """PT-BR → inglês via ChatGPT. A saída alimenta `pyabsa_multilingual_predict_raw`."""
    body = (text or "").strip()[:max_chars]
    prompt = (
        "Translate the following from Brazilian Portuguese to English.\n"
        "Output ONLY the English translation — no labels, no preamble, no notes.\n"
        "Keep numbers, brand names and all facts accurate; natural English.\n\n"
        f"Text:\n{body}"
    )
    return _chat(prompt)


def gpt_categorize_aspects(
    *,
    texto_original: str,
    review_en: str,
    pilar_id: str,
    pilar_label: str,
    aspects: list[str],
    sentiments: list[str],
    confidences: list[float] | None = None,
) -> dict[str, Any]:
    """
    Dado o texto em PT e os aspectos/sentimentos (e confianças) do PyABSA,
    pede ao GPT para rotular cada aspecto em PT-BR e mapear ao pilar.

    Retorno: ``texto_original`` e ``aspectos`` com
    ``aspecto_detectado``, ``sentimento``, ``confiança_modelo`` (PyABSA), ``pilar`` e
    ``resumo_aspecto`` (frase curta em PT-BR inferida do texto + sentimento, via GPT).
    """
    texto_orig = (texto_original or "").strip()
    conf_list = list(confidences or [])

    if not aspects:
        return {"texto_original": texto_orig, "aspectos": []}

    items = [
        {"aspecto_en": a, "sentimento_en": s}
        for a, s in zip(aspects, sentiments)
    ]

    prompt = (
        "You are an expert in aspect-based sentiment analysis for e-commerce reviews.\n"
        "Given a review and a list of aspect terms (extracted by a model) with their sentiments, "
        "translate each aspect term to natural Brazilian Portuguese and map it to the correct pillar.\n\n"
        "Pillars:\n"
        "- qualidade_produto: material, defeito, acabamento, transparência, durabilidade\n"
        "- ajuste_caimento: tamanho, modelagem, não serviu, tabela de medidas\n"
        "- logistica_entrega: prazo, entrega, transportadora, rastreio, pacote\n"
        "- atendimento_cliente: suporte, estorno, devolução, chat, política\n"
        "- general_collection: assuntos gerais que não se encaixam nos outros\n\n"
        f"Review (PT-BR):\n{texto_orig[:1500]}\n\n"
        f"Review (EN):\n{review_en[:1500]}\n\n"
        f"Origin pillar hint (not mandatory): {pilar_label} [{pilar_id}]\n\n"
        "Aspect terms extracted:\n"
        f"{json.dumps(items, ensure_ascii=False)}\n\n"
        "Output ONLY a JSON array (no markdown, no extra text). Same length and order as the input list. "
        "Each element must be an object with:\n"
        '- "aspecto_pt": natural Brazilian Portuguese label for the aspect term\n'
        '- "sentimento": "positivo" | "negativo" | "neutro"\n'
        '- "pilar": one of the pillar ids listed above\n'
        '- "resumo_aspecto": one short sentence in Brazilian Portuguese summarizing what the consumer '
        "expressed about THIS aspect only, grounded in the review text (PT-BR) and consistent with the sentiment; "
        "not a generic template.\n"
    )

    raw = _chat(prompt)

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed: list[dict[str, Any]] = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [
            {
                "aspecto_pt": a,
                "sentimento": str(s).lower(),
                "pilar": pilar_id,
                "resumo_aspecto": "",
            }
            for a, s in zip(aspects, sentiments)
        ]

    linhas: list[dict[str, Any]] = []
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        try:
            conf = float(conf_list[i]) if i < len(conf_list) else 0.0
        except (TypeError, ValueError):
            conf = 0.0
        resumo = str(
            item.get("resumo_aspecto", item.get("resumo_pt", "")) or ""
        ).strip()
        linhas.append(
            {
                "aspecto_detectado": str(item.get("aspecto_pt") or "").strip(),
                "sentimento": str(item.get("sentimento") or "").strip().lower(),
                "confiança_modelo": conf,
                "pilar": str(item.get("pilar") or pilar_id).strip(),
                "resumo_aspecto": resumo,
            }
        )

    return {"texto_original": texto_orig, "aspectos": linhas}
