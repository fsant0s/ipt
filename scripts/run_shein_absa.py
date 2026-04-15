#!/usr/bin/env python3
"""Amostra N reviews por pilar e corre o mesmo pipeline que ``main.ipynb`` (``run_shein_absa_for_row``) → ``data/processed/shein_absa.json``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_project_root() -> Path:
    root = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists())
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Traduz reviews, extrai aspectos (PyABSA) e categoriza (GPT); grava lista em shein_absa.json.",
    )
    parser.add_argument(
        "-n",
        "--per-pillar",
        type=int,
        default=3,
        metavar="N",
        help="quantidade de reviews amostradas por pilar (default: 3)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="seed da amostragem (default: 42)",
    )
    args = parser.parse_args()

    _ensure_project_root()

    from src.processing.shein_absa_pipeline import run_shein_absa_for_row
    from src.utils.helpers import (
        DEFAULT_PILLAR_ORDER,
        load_shein_absa_list,
        save_json,
        shein_absa_list_json_path,
        upsert_shein_absa_item,
    )
    from src.utils.shein_reviews import sample_reviews_per_pillar

    n = max(0, args.per_pillar)
    by_pillar = sample_reviews_per_pillar(n, seed=args.seed)
    rows: list[dict] = []
    for pillar_id in DEFAULT_PILLAR_ORDER:
        rows.extend(by_pillar.get(pillar_id, []))
    for pid in by_pillar:
        if pid not in DEFAULT_PILLAR_ORDER:
            rows.extend(by_pillar[pid])

    shein_absa_list = load_shein_absa_list()
    out_path = shein_absa_list_json_path()

    for r in rows:
        t = (r.get("title") or "").strip()
        body = (r.get("review") or "").strip()

        print("=== PT-BR ===")
        print(t)
        print(body)

        texto_en, result = run_shein_absa_for_row(r)
        print("\n=== EN (ChatGPT) ===")
        print(texto_en)

        shein_absa_list, how = upsert_shein_absa_item(shein_absa_list, result)
        save_json(out_path, shein_absa_list)

        print("\n=== Resultado (esta review) ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\nLista salva ({how}): {out_path} ({len(shein_absa_list)} itens)")


if __name__ == "__main__":
    main()
