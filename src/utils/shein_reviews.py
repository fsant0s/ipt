from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from src.utils.helpers import DEFAULT_PILLAR_ORDER, load_json, shein_json_path

_COMPANY_REPLY_MARKER = "[Resposta da empresa]"


def strip_company_reply(text: str) -> str:
    """
    Remove o trecho da resposta da empresa (Reclame Aqui), a partir do marcador
    `[Resposta da empresa]`, mantendo apenas o texto do consumidor.
    """
    if not text:
        return ""
    s = str(text)
    if _COMPANY_REPLY_MARKER in s:
        s = s.split(_COMPANY_REPLY_MARKER, 1)[0]
    return s.rstrip()


def default_shein_json_path() -> Path:
    return shein_json_path()


def load_shein_raw(path: str | Path | None = None) -> dict[str, Any]:
    """Carrega o JSON bruto (`pillars` → reviews com title/review)."""
    p = Path(path) if path is not None else default_shein_json_path()
    return load_json(p)


def reviews_by_pillar(
    data: dict[str, Any] | None = None, *, path: str | Path | None = None
) -> dict[str, list[dict[str, str]]]:
    """
    Lista todas as reviews por id do pilar, cada item com:
    pillar, pillar_label, title, review (texto do consumidor apenas —
    resposta da empresa removida via strip_company_reply).
    """
    raw = data if data is not None else load_shein_raw(path)
    pillars = raw.get("pillars") or {}
    if not isinstance(pillars, dict):
        return {}

    out: dict[str, list[dict[str, str]]] = {}
    for pillar_id, block in pillars.items():
        if not isinstance(block, dict):
            continue
        label = str(block.get("pillar_label") or pillar_id)
        rows: list[dict[str, str]] = []
        for r in block.get("reviews") or []:
            if not isinstance(r, dict):
                continue
            rows.append(
                {
                    "pillar": str(pillar_id),
                    "pillar_label": label,
                    "title": str(r.get("title", "")),
                    "review": strip_company_reply(str(r.get("review", ""))),
                }
            )
        out[str(pillar_id)] = rows
    return out


def sample_reviews_per_pillar(
    n: int,
    *,
    path: str | Path | None = None,
    data: dict[str, Any] | None = None,
    seed: int | None = None,
) -> dict[str, list[dict[str, str]]]:
    """
    Para cada pilar, sorteia até `n` comentários aleatórios (sem reposição).
    Se `n` for maior que o disponível, retorna todos daquele pilar.
    Com `n <= 0`, retorna listas vazias para cada pilar existente.
    """
    by_pillar = reviews_by_pillar(data, path=path)
    rng = random.Random(seed) if seed is not None else random

    result: dict[str, list[dict[str, str]]] = {}
    for pillar_id, items in by_pillar.items():
        if n <= 0:
            result[pillar_id] = []
            continue
        k = min(n, len(items))
        result[pillar_id] = rng.sample(items, k) if k else []
    return result
