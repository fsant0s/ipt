import json
import urllib.parse
from pathlib import Path

from loguru import logger
from playwright.sync_api import sync_playwright

from src.utils.helpers import project_root, reviews_data_dir, shein_json_path


CONFIG_PATH = project_root() / "src" / "config" / "scraping_config.json"
REVIEWS_DIR = reviews_data_dir()
SHEIN_JSON_PATH = shein_json_path()
_LEGACY_REVIEWS_DIR = project_root() / "reviews"

# Rótulos legíveis para o JSON (chave do config -> nome do pilar)
PILLAR_LABELS: dict[str, str] = {
    "qualidade_produto": "Qualidade do Produto",
    "ajuste_caimento": "Ajuste e Caimento",
    "logistica_entrega": "Logística de Entrega",
    "atendimento_cliente": "Atendimento ao Cliente",
    "general_collection": "Coleta Geral",
}

def _normalize_title(title: str) -> str:
    return " ".join((title or "").split()).strip().lower()


def _ensure_entry(item: dict) -> dict:
    pl = str(item.get("pillar", ""))
    return {
        "pillar": pl,
        "pillar_label": str(item.get("pillar_label", "") or PILLAR_LABELS.get(pl, pl)),
        "query": str(item.get("query", "")),
        "title": str(item.get("title", "")),
        "review": str(item.get("review", "")),
    }


def _legacy_shein_json_files() -> list[Path]:
    """Arquivos `shein_*.json` (exceto `shein.json`) em `data/reviews/` e, se existir, `reviews/` legada."""
    out: list[Path] = []
    seen: set[str] = set()
    for base in (REVIEWS_DIR, _LEGACY_REVIEWS_DIR):
        if not base.is_dir():
            continue
        for p in sorted(base.glob("shein_*.json")):
            if p.name == "shein.json":
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def _bootstrap_from_legacy_glob() -> tuple[list[dict], set[str]]:
    """
    Se `shein.json` ainda não existe, importa entradas de `shein_*.json` antigos
    (um arquivo por query) para não perder dados.
    Procura em ``data/reviews/`` e, se ainda existir, na pasta legada ``reviews/``.
    """
    entries: list[dict] = []
    titles: set[str] = set()
    for legacy_path in _legacy_shein_json_files():
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("reviews"), list):
            continue
        pl = str(data.get("pillar", ""))
        pll = str(data.get("pillar_label", "") or PILLAR_LABELS.get(pl, pl))
        q = str(data.get("query", ""))
        for r in data["reviews"]:
            if not isinstance(r, dict):
                continue
            title = str(r.get("title", ""))
            review = str(r.get("review", ""))
            key = _normalize_title(title)
            if not key or key in titles:
                continue
            titles.add(key)
            entries.append(
                _ensure_entry(
                    {
                        "pillar": pl,
                        "pillar_label": pll,
                        "query": q,
                        "title": title,
                        "review": review,
                    }
                )
            )
    return entries, titles


def _flatten_pillars_block(data: dict) -> tuple[list[dict], set[str]]:
    """Lê formato { pillars: { nome_pilar: { reviews: [{title, review}] } } }."""
    entries: list[dict] = []
    titles: set[str] = set()
    pillars_block = data.get("pillars")
    if not isinstance(pillars_block, dict):
        return entries, titles
    for pk, block in pillars_block.items():
        if not isinstance(block, dict):
            continue
        pll = str(block.get("pillar_label", "") or PILLAR_LABELS.get(str(pk), str(pk)))
        for r in block.get("reviews") or []:
            if not isinstance(r, dict):
                continue
            title = str(r.get("title", ""))
            review = str(r.get("review", ""))
            key = _normalize_title(title)
            if not key or key in titles:
                continue
            titles.add(key)
            entries.append(
                _ensure_entry(
                    {
                        "pillar": str(pk),
                        "pillar_label": pll,
                        "query": "",
                        "title": title,
                        "review": review,
                    }
                )
            )
    return entries, titles


def load_shein_entries() -> tuple[list[dict], set[str]]:
    """Carrega todas as entradas de `shein.json` (ou bootstrap de arquivos legados)."""
    if SHEIN_JSON_PATH.exists():
        try:
            with open(SHEIN_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return [], set()

        entries: list[dict] = []
        titles: set[str] = set()

        if isinstance(data, dict) and isinstance(data.get("pillars"), dict):
            entries, titles = _flatten_pillars_block(data)
        elif isinstance(data, dict) and isinstance(data.get("reviews"), list):
            for item in data["reviews"]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", ""))
                key = _normalize_title(title)
                if not key or key in titles:
                    continue
                titles.add(key)
                entries.append(_ensure_entry(item))

        if not entries:
            leg, leg_titles = _bootstrap_from_legacy_glob()
            return leg, leg_titles
        return entries, titles

    return _bootstrap_from_legacy_glob()


def merge_shein_entries(
    existing: list[dict],
    existing_titles: set[str],
    new_items: list[dict],
) -> tuple[list[dict], int]:
    merged = list(existing)
    added = 0
    for item in new_items:
        item = _ensure_entry(item)
        key = _normalize_title(item.get("title", ""))
        if not key:
            continue
        if key in existing_titles:
            continue
        existing_titles.add(key)
        merged.append(item)
        added += 1
    return merged, added


def save_shein_json(entries: list[dict]) -> None:
    """
    Salva agrupado por pilar:

    {
      "pillars": {
        "qualidade_produto": {
          "pillar_label": "Qualidade do Produto",
          "reviews": [ { "title": "...", "review": "..." }, ... ]
        },
        ...
      }
    }
    """
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    by_pillar: dict[str, dict] = {}
    for e in entries:
        e = _ensure_entry(e)
        pk = e["pillar"]
        if pk not in by_pillar:
            by_pillar[pk] = {
                "pillar_label": e.get("pillar_label") or PILLAR_LABELS.get(pk, pk),
                "reviews": [],
            }
        by_pillar[pk]["reviews"].append(
            {
                "title": e["title"],
                "review": e["review"],
            }
        )

    ordered: dict[str, dict] = {}
    for key in PILLAR_LABELS:
        if key in by_pillar:
            ordered[key] = by_pillar[key]
    for key in sorted(k for k in by_pillar if k not in ordered):
        ordered[key] = by_pillar[key]

    payload = {"pillars": ordered}
    with open(SHEIN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_url(base_url: str, query: str):
    encoded_query = urllib.parse.quote_plus(query)
    return base_url.replace("{query}", encoded_query)


def prepare_page(page):
    # cookie banner (best-effort)
    try:
        page.locator("button:has-text('Aceitar')").click(timeout=3000)
    except Exception:
        pass

    try:
        page.wait_for_timeout(2000)
    except Exception:
        return


def safe_goto(browser, page, url):
    """
    Navega para a URL e, se a página/contexto fechar (TargetClosed),
    recria uma nova aba e tenta novamente.
    Retorna o page ativo (possivelmente novo).
    """
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        return page
    except Exception as e:
        msg = str(e)
        logger.warning(f"Erro no goto: {e}")
        if "Target page, context or browser has been closed" in msg:
            try:
                page = browser.new_page()
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                return page
            except Exception as e2:
                logger.warning(f"Falha ao recriar page e navegar: {e2}")
                return page

        try:
            page.wait_for_timeout(2000)
        except Exception:
            pass
        return page


def looks_like_security_verification(page) -> bool:
    """
    Heurística conservadora: checa texto *visível* típico do challenge.
    Evita falso-positivo por scripts/strings presentes no HTML.
    """
    try:
        title = (page.title() or "").lower()
        if "security verification" in title:
            return True
    except Exception:
        pass

    needles = [
        "performing security verification",
        "this website uses a security service",
        "verify you are not a bot",
        "ray id",
        "cloudflare",
    ]
    for n in needles:
        try:
            if page.get_by_text(n, exact=False).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def list_complaint_items(page):
    """
    Extrai itens (texto do link + URL) da listagem.

    Pelo HTML que você mostrou:
    <a href="/shein/...." data-testid="complaint-listagem-v2-title-link">...</a>
    """
    anchors = page.locator("a[data-testid='complaint-listagem-v2-title-link']").all()

    # fallback tolerante (caso o atributo mude)
    if not anchors:
        anchors = page.locator("a[href^='/shein/']").all()

    items: list[dict[str, str]] = []
    seen = set()
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
            if not href.startswith("/"):
                continue
            url = f"https://www.reclameaqui.com.br{href}"
            if url in seen:
                continue
            seen.add(url)
            title = (a.get_attribute("title") or a.inner_text() or "").strip()
            items.append({"title": title, "url": url})
        except Exception:
            continue

    return items


def extract_detail(page) -> dict[str, str]:
    """
    Extrai título e conteúdo principal ("conversa") da página da reclamação.

    Pelo HTML enviado:
    - Título: h1[data-testid="complaint-title"]
    - Texto do consumidor: p[data-testid="complaint-description"]
    - Resposta da empresa: seção com h2 "Resposta da empresa" e um <p> com o texto.
    """
    if page.is_closed():
        return {"title": "", "conversation": ""}

    try:
        page.wait_for_selector("h1[data-testid='complaint-title']", timeout=30000)
    except Exception:
        pass

    title = ""
    try:
        title = page.locator("h1[data-testid='complaint-title']").first.inner_text().strip()
    except Exception:
        try:
            title = page.locator("h1#complaint-title").first.inner_text().strip()
        except Exception:
            title = ""

    consumer_text = ""
    try:
        consumer_text = page.locator("p[data-testid='complaint-description']").first.inner_text().strip()
    except Exception:
        try:
            consumer_text = page.locator("#complaint-description").first.inner_text().strip()
        except Exception:
            consumer_text = ""

    company_reply = ""
    try:
        # Seção "Resposta da empresa" costuma ter um <h2> com esse texto
        section = page.locator("section", has=page.get_by_role("heading", name="Resposta da empresa")).first
        company_reply = section.locator("p").last.inner_text().strip()
    except Exception:
        company_reply = ""

    conversation_parts = []
    if consumer_text:
        conversation_parts.append(consumer_text)
    if company_reply:
        conversation_parts.append(f"[Resposta da empresa]\n{company_reply}")

    conversation = "\n\n".join(conversation_parts).strip()

    return {"title": title, "conversation": conversation}


def pillar_queries_list(pdata: dict) -> list[str]:
    """
    Lista de termos de busca do pilar.
    Preferência: `queries` como array. Aceita dict legado com chaves negativo/positivo.
    """
    raw = pdata.get("queries")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, dict):
        merged: list[str] = []
        for bucket in ("negativo", "positivo"):
            merged.extend(str(x).strip() for x in (raw.get(bucket) or []) if str(x).strip())
        return merged
    return []


def iter_scrape_jobs(config: dict):
    """
    Gera (pillar, query, list_url) para cada combinação.
    - mode=test: limita pilar e quantidade de queries (scrape_run.test).
    - mode=full: todos os pilares com enabled=true e todas as queries.
    """
    base_url = config["base_url"]
    run = config.get("scrape_run") or {}
    mode = (run.get("mode") or "test").lower()
    test = run.get("test") or {}
    pillars_cfg = config.get("pillars") or {}

    if mode == "test":
        only_pillar = test.get("only_pillar", "qualidade_produto")
        max_queries = int(test.get("max_queries", 1))
        pdata = pillars_cfg.get(only_pillar) or {}
        if not pdata.get("enabled", True):
            return
        qs = pillar_queries_list(pdata)[:max_queries]
        for q in qs:
            yield only_pillar, q, build_url(base_url, q)
        return

    for pname, pdata in pillars_cfg.items():
        if not pdata.get("enabled", False):
            continue
        for q in pillar_queries_list(pdata):
            yield pname, q, build_url(base_url, q)


def scrape_one_query(
    *,
    pillar: str,
    query: str,
    list_url: str,
    max_links: int,
) -> None:
    """Uma busca: lista links, extrai detalhes, merge e salva JSON."""
    new_entries: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()

        logger.info(f"Scrape: {pillar} / {query!r}")
        print(f"\n{'='*60}")
        print(f"Pilar: {pillar} ({PILLAR_LABELS.get(pillar, pillar)})")
        print(f"Query: {query}")
        print(f"Entrada: {list_url}\n")

        page = safe_goto(browser, page, list_url)
        prepare_page(page)

        try:
            page.wait_for_selector("a[data-testid='complaint-listagem-v2-title-link']", timeout=120000)
        except Exception:
            if looks_like_security_verification(page):
                print("Timeout: continuou em verificação de segurança (Cloudflare).")
            else:
                print("Timeout: não encontrei links de reclamação na página.")
            browser.close()
            return

        items = list_complaint_items(page)[:max_links]
        print(f"Encontrados: {len(items)} itens (limit={max_links})\n")
        for idx, it in enumerate(items, start=1):
            print(f"[{idx}] {it['title']}".strip())
            print(f"URL: {it['url']}")

        browser.close()

        print("\n--- Extraindo detalhes (título + conversa) ---\n")
        for idx, it in enumerate(items, start=1):
            url = it["url"]
            browser = pw.chromium.launch(headless=False)
            page = browser.new_page()
            page = safe_goto(browser, page, url)
            prepare_page(page)

            detail = extract_detail(page)
            print(f"\n===== ITEM {idx} =====")
            print(f"URL: {url}")
            print(f"Título: {detail['title']}\n")
            print(detail["conversation"])

            new_entries.append(
                _ensure_entry(
                    {
                        "pillar": pillar,
                        "pillar_label": PILLAR_LABELS.get(pillar, pillar),
                        "query": query,
                        "title": detail["title"],
                        "review": detail["conversation"],
                    }
                )
            )
            browser.close()

    existing, title_keys = load_shein_entries()
    merged, n_added = merge_shein_entries(existing, title_keys, new_entries)
    save_shein_json(merged)
    print(
        f"\nSalvo: {SHEIN_JSON_PATH} ({len(merged)} reviews no total, {n_added} novos nesta rodada)"
    )


def scrape():
    config = load_config()
    run = config.get("scrape_run") or {}
    mode = (run.get("mode") or "test").lower()
    test = run.get("test") or {}
    full = run.get("full") or {}
    if mode == "test":
        max_links = int(test.get("max_links_per_query", 5))
    else:
        max_links = int(full.get("max_links_per_query", test.get("max_links_per_query", 5)))

    jobs = list(iter_scrape_jobs(config))
    if not jobs:
        logger.warning("Nenhum job de scraping (pillars desabilitados ou lista vazia).")
        return

    for pillar, query, list_url in jobs:
        scrape_one_query(
            pillar=pillar,
            query=query,
            list_url=list_url,
            max_links=max_links,
        )


if __name__ == "__main__":
    scrape()

