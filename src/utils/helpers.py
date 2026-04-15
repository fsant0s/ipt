from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_PILLAR_ORDER: tuple[str, ...] = (
    "qualidade_produto",
    "ajuste_caimento",
    "logistica_entrega",
    "atendimento_cliente",
    "general_collection",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def checkpoints_dir() -> Path:
    """Pasta única na raiz do projeto: `checkpoints/` (PyABSA + `checkpoints.json`)."""
    return project_root() / "checkpoints"


def reviews_data_dir() -> Path:
    """Dados de reviews raspados / consolidados: `data/reviews/` (ex.: `shein.json`)."""
    return project_root() / "data" / "reviews"


def processed_data_dir() -> Path:
    """Saídas derivadas (scrape consolidado opcional, ABSA): `data/processed/`."""
    return project_root() / "data" / "processed"


def shein_json_path() -> Path:
    """Arquivo único com reviews Shein agrupadas por pilar."""
    return reviews_data_dir() / "shein.json"


def shein_absa_list_json_path() -> Path:
    """
    Lista na raiz: cada item tem ``texto_original`` e ``aspectos`` com
    ``aspecto_detectado``, ``sentimento``, ``confiança_modelo``, ``pilar``, ``resumo_aspecto``.
    """
    return project_root() / "data" / "processed" / "shein_absa.json"


def texto_original_from_entry(entry: dict[str, Any]) -> str:
    """Compatível com entradas antigas ``titulo`` + ``review`` ou só ``texto_original``."""
    if entry.get("texto_original"):
        return str(entry["texto_original"]).strip()
    tit = str(entry.get("titulo") or "").strip()
    rev = str(entry.get("review") or "").strip()
    return (f"{tit}. {rev}".strip() if tit else rev).strip()


def review_dedupe_key(item: dict[str, Any]) -> str:
    """Uma string normalizada por review (evita duplicados)."""
    return " ".join(texto_original_from_entry(item).split()).strip().lower()


def normalize_shein_absa_aspect_row(row: dict[str, Any]) -> dict[str, Any]:
    conf = row.get("confiança_modelo", row.get("confianca_modelo", 0.0))
    try:
        conf_f = float(conf) if conf is not None else 0.0
    except (TypeError, ValueError):
        conf_f = 0.0
    return {
        "aspecto_detectado": str(
            row.get("aspecto_detectado", row.get("aspecto", "")) or ""
        ).strip(),
        "sentimento": str(row.get("sentimento", "") or "").strip().lower(),
        "confiança_modelo": conf_f,
        "pilar": str(row.get("pilar", "") or "").strip(),
        "resumo_aspecto": str(row.get("resumo_aspecto", "") or "").strip(),
    }


def normalize_shein_absa_entry(entry: dict[str, Any]) -> dict[str, Any]:
    rows = entry.get("aspectos") or []
    aspectos = [
        normalize_shein_absa_aspect_row(x)
        for x in rows
        if isinstance(x, dict)
    ]
    return {"texto_original": texto_original_from_entry(entry), "aspectos": aspectos}


def load_shein_absa_list(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Lê ``shein_absa.json`` e normaliza formato (incl. legado titulo/review e ``aspecto``)."""
    p = Path(path) if path is not None else shein_absa_list_json_path()
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [normalize_shein_absa_entry(x) for x in data if isinstance(x, dict)]


def upsert_shein_absa_item(
    existing: list[dict[str, Any]],
    item: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """
    Insere ou substitui pela chave ``review_dedupe_key`` (``texto_original``).
    Retorno: ``(nova_lista, "added"|"replaced")``.
    """
    item_n = normalize_shein_absa_entry(item)
    k_new = review_dedupe_key(item_n)
    out: list[dict[str, Any]] = []
    replaced = False
    for x in existing:
        x_n = normalize_shein_absa_entry(x)
        if review_dedupe_key(x_n) == k_new:
            out.append(dict(item_n))
            replaced = True
        else:
            out.append(x_n)
    if not replaced:
        out.append(item_n)
        return out, "added"
    return out, "replaced"


def load_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Grava JSON UTF-8 com indentação (padrão para inspeção humana e diff no git)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)

