# ABSA — Motor de Análise de Sentimentos por Aspectos (Shein / Reclame Aqui)

Pipeline completo de **Aspect-Based Sentiment Analysis (ABSA)** para reviews da Shein coletadas no Reclame Aqui. O sistema cobre desde a raspagem dos textos até a geração de um JSON estruturado por aspecto, com sentimento, confiança do modelo e uma frase de resumo em português.

---

## Visão geral do fluxo

```
Reclame Aqui
    │  Playwright (headless browser)
    ▼
data/reviews/shein.json          ← reviews brutas agrupadas por pilar
    │  sample_reviews_per_pillar()
    ▼
texto PT-BR  ──► ChatGPT (gpt-4o-mini)  ──► texto EN
                                                │
                                           PyABSA ATEPC
                                    (multilingual DeBERTa)
                                                │
                          aspect[], sentiment[], confidence[]
                                                │
                                   ChatGPT (gpt-4o-mini)
                            (tradução PT + pilar + resumo)
                                                │
                                                ▼
                             data/processed/shein_absa.json
```

---

## Pré-requisitos

| Requisito | Versão mínima |
|-----------|--------------|
| Python | 3.12 |
| uv (gerenciador de pacotes) | qualquer recente |
| Chave OpenAI | `OPENAI_API_KEY` |
| Playwright (para scraping) | instalado via `uv` |

### Instalação

```bash
# Clonar e entrar no projeto
cd ipt

# Instalar dependências (cria .venv automaticamente)
uv sync

# Instalar browsers do Playwright (necessário apenas para scraping)
uv run playwright install chromium

# Copiar e preencher variáveis de ambiente
cp .env.example .env
# Editar .env e preencher OPENAI_API_KEY=sk-...
```

O arquivo `.env` deve conter:

```
OPENAI_API_KEY=sk-...
```

---

## Estrutura de pastas

```
ipt/
├── data/
│   ├── reviews/
│   │   └── shein.json              ← reviews coletadas pelo scraper
│   └── processed/
│       └── shein_absa.json         ← saída final do pipeline ABSA
├── checkpoints/
│   └── ATEPC_MULTILINGUAL_CHECKPOINT/  ← modelo PyABSA (DeBERTa multilingual)
├── scripts/
│   └── run_shein_absa.py           ← script CLI para processar N reviews
├── src/
│   ├── scraping/
│   │   ├── scraper.py              ← web scraping (Playwright + Reclame Aqui)
│   │   └── scraping_config.json    ← pilares e queries de busca
│   ├── processing/
│   │   ├── shein_absa_pipeline.py  ← pipeline único (tradução + PyABSA + GPT)
│   │   ├── pyabsa_multilingual.py  ← wrapper PyABSA (extração de aspectos)
│   │   └── openaigpt.py            ← tradução PT→EN e categorização GPT
│   └── utils/
│       ├── helpers.py              ← caminhos, load/save JSON, deduplicação
│       └── shein_reviews.py        ← leitura e amostragem das reviews
├── main.ipynb                      ← notebook de análise rápida (1 review)
└── pyproject.toml
```

---

## Etapa 1 — Scraping

### Como funciona

O scraper usa **Playwright** (navegador Chromium headless) para:

1. Acessar a URL de busca do Reclame Aqui:  
   `https://www.reclameaqui.com.br/empresa/shein/lista-reclamacoes/?busca={query}`
2. Extrair os links das reclamações listadas.
3. Entrar em cada reclamação e coletar o **título** e o **texto do consumidor** (a resposta da empresa é automaticamente removida).
4. Mesclar com o arquivo existente (`data/reviews/shein.json`), sem duplicar pelo título.

### Configuração (`src/config/scraping_config.json`)

Cada pilar tem uma lista de `queries` de busca no Reclame Aqui:

| Pilar | Exemplos de queries |
|-------|-------------------|
| `qualidade_produto` | "tecido ruim", "material ruim", "veio rasgado" |
| `ajuste_caimento` | "tamanho errado", "não serviu", "modelagem ruim" |
| `logistica_entrega` | "atraso entrega", "não chegou", "prazo não cumprido" |
| `atendimento_cliente` | "atendimento ruim", "estorno não feito", "troca problema" |
| `general_collection` | "shein", "pedido shein", "experiencia shein" |

### Executar o scraper

```bash
uv run python -m src.scraping.scraper
```

Saída gravada em `data/reviews/shein.json` com estrutura:

```json
{
  "pillars": {
    "qualidade_produto": {
      "pillar_label": "Qualidade do Produto",
      "reviews": [
        { "title": "...", "review": "..." }
      ]
    }
  }
}
```

---

## Etapa 2 — Pipeline ABSA

Para cada review, o pipeline executa **três chamadas a modelos de IA**:

### Passo 2.1 — Tradução PT-BR → EN (ChatGPT)

O texto da review (título + corpo) é enviado ao `gpt-4o-mini` para tradução.  
PyABSA foi treinado predominantemente em inglês; a tradução melhora significativamente a detecção de aspectos.

```
"Lençóis de má qualidade e tamanho inadequado..."
      ↓ gpt-4o-mini
"Poor quality and inappropriate size sheets..."
```

### Passo 2.2 — Extração de aspectos (PyABSA ATEPC)

O texto em inglês é processado pelo modelo **`fast_lcf_atepc`** (`DeBERTa multilingual`), armazenado localmente em `checkpoints/ATEPC_MULTILINGUAL_CHECKPOINT/`.

O modelo detecta, para cada aspecto mencionado:
- O **termo do aspecto** (em inglês, ex.: `"quality"`, `"size"`, `"material"`)
- O **sentimento** (`Positive`, `Negative`, `Neutral`)
- A **confiança** (`0.0` – `1.0`)

O texto é segmentado por sentença antes da inferência (máximo 80 sentenças, 3 000 caracteres).

### Passo 2.3 — Categorização + resumo (ChatGPT)

Os aspectos extraídos são enviados ao `gpt-4o-mini` numa única chamada. O modelo:
1. **Traduz** cada termo para PT-BR natural (`"quality"` → `"qualidade"`)
2. **Classifica** o sentimento como `positivo`, `negativo` ou `neutro`
3. **Mapeia ao pilar** correspondente (usando o texto original como contexto)
4. **Gera um `resumo_aspecto`** — uma frase curta em PT-BR que descreve o que o consumidor expressou sobre aquele aspecto, fundamentada no texto real da review

---

## Execução em lote

```bash
# 3 reviews por pilar (default), seed 42
uv run python scripts/run_shein_absa.py

# 5 reviews por pilar, outra seed
uv run python scripts/run_shein_absa.py -n 5 --seed 7

# 1 review por pilar (mínimo para teste)
uv run python scripts/run_shein_absa.py -n 1
```

Cada execução:
- Carrega a lista existente em `data/processed/shein_absa.json`
- **Deduplicação**: se a mesma review já existe (pelo texto normalizado), substitui o registro em vez de duplicar
- Imprime no terminal `added` (nova) ou `replaced` (atualizada) e o total acumulado
- Grava o arquivo atualizado após cada review processada (progresso não se perde em caso de erro)

---

## Análise rápida (notebook)

Para inspecionar uma única review de um pilar específico:

```bash
uv run jupyter lab main.ipynb
```

No topo da célula principal, altere as variáveis de configuração:

```python
# Pilares: qualidade_produto | ajuste_caimento | logistica_entrega | atendimento_cliente | general_collection
PILAR = "qualidade_produto"
SEED  = 42
```

O notebook exibe:
- Texto original em PT-BR
- Tradução em inglês (ChatGPT)
- JSON completo do resultado
- Tabela de aspectos (pandas DataFrame)

---

## Saída — `data/processed/shein_absa.json`

O arquivo é uma **lista JSON** (array na raiz). Cada elemento representa uma review processada.

### Estrutura de um elemento

```json
{
  "texto_original": "<título>. <corpo da review em PT-BR>",
  "aspectos": [ ... ]
}
```

### Chaves do nível da review

| Chave | Tipo | Descrição |
|-------|------|-----------|
| `texto_original` | `string` | Texto completo em PT-BR enviado ao pipeline (título + ". " + corpo). Resposta da empresa é removida antes deste ponto. |
| `aspectos` | `array` | Lista de aspectos detectados, um objeto por aspecto. |

### Chaves de cada aspecto

| Chave | Tipo | Origem | Descrição |
|-------|------|--------|-----------|
| `aspecto_detectado` | `string` | GPT | Nome do aspecto em PT-BR natural (ex.: `"qualidade"`, `"tamanho"`, `"entrega"`). |
| `sentimento` | `string` | GPT | Polaridade: `"positivo"`, `"negativo"` ou `"neutro"`. |
| `confiança_modelo` | `float` | PyABSA | Score de confiança do modelo ATEPC (`0.0` – `1.0`). Valores acima de `0.95` indicam alta certeza. |
| `pilar` | `string` | GPT | ID do pilar temático ao qual o aspecto pertence (ver tabela de pilares abaixo). |
| `resumo_aspecto` | `string` | GPT | Frase curta em PT-BR que resume o que o consumidor expressou sobre este aspecto, inferida do texto original e consistente com o sentimento. |

### Pilares

| ID | Descrição | Exemplos de aspectos típicos |
|----|-----------|------------------------------|
| `qualidade_produto` | Material, durabilidade, acabamento | material, tecido, acabamento, defeito |
| `ajuste_caimento` | Tamanho, modelagem, tabela de medidas | tamanho, modelagem, caimento |
| `logistica_entrega` | Prazo, transportadora, rastreio | entrega, prazo, transportadora |
| `atendimento_cliente` | Suporte, devolução, estorno | atendimento, estorno, devolução |
| `general_collection` | Tudo que não se encaixa nos outros | preço, credibilidade, experiência geral |

### Exemplo real de saída

```json
[
  {
    "texto_original": "Lençóis de má qualidade e tamanho inadequado da Shein. Bom dia, sou compradora assidua da shein, e fiquei bastante decepcionada com minhas últimas compras. Comprei alguns lençóis de casal com elástico e qndo chegou fiquei chocada com a qualidade do material, o acabamento então horrível sem falar que nenhum deu na minha cama que é de casal normal sendo que um rasgou!!!",
    "aspectos": [
      {
        "aspecto_detectado": "qualidade",
        "sentimento": "negativo",
        "confiança_modelo": 0.995,
        "pilar": "qualidade_produto",
        "resumo_aspecto": "O consumidor ficou chocado com a má qualidade dos lençóis."
      },
      {
        "aspecto_detectado": "tamanho",
        "sentimento": "negativo",
        "confiança_modelo": 0.9949,
        "pilar": "ajuste_caimento",
        "resumo_aspecto": "Os lençóis não serviram na cama do consumidor, que é de casal normal."
      },
      {
        "aspecto_detectado": "material",
        "sentimento": "negativo",
        "confiança_modelo": 0.9902,
        "pilar": "qualidade_produto",
        "resumo_aspecto": "O material dos lençóis foi considerado de baixa qualidade."
      },
      {
        "aspecto_detectado": "acabamento",
        "sentimento": "negativo",
        "confiança_modelo": 0.9807,
        "pilar": "qualidade_produto",
        "resumo_aspecto": "O acabamento dos lençóis foi descrito como horrível."
      }
    ]
  },
  {
    "texto_original": "Reembolso negado para roupa de academia com material diferente do anunciado e tamanho inadequado. ...",
    "aspectos": [
      {
        "aspecto_detectado": "material",
        "sentimento": "negativo",
        "confiança_modelo": 0.994,
        "pilar": "qualidade_produto",
        "resumo_aspecto": "O material da roupa não corresponde ao que foi anunciado e é de qualidade ruim."
      },
      {
        "aspecto_detectado": "estorno",
        "sentimento": "negativo",
        "confiança_modelo": 0.9896,
        "pilar": "atendimento_cliente",
        "resumo_aspecto": "O reembolso foi negado sem justificativa clara, contrariando meus direitos."
      }
    ]
  }
]
```

---

## Deduplicação

O sistema evita processar a mesma review duas vezes. A chave de deduplicação é o `texto_original` **normalizado** (espaços compactados, caixa baixa). Se a mesma review for reencontrada:

- O registro antigo é **substituído** pelo novo resultado (atualiza ABSA sem duplicar).
- O terminal imprime `replaced` em vez de `added`.

---

## Modelos utilizados

| Modelo | Uso | Hospedagem |
|--------|-----|-----------|
| `gpt-4o-mini` (OpenAI) | Tradução PT→EN, categorização de aspectos, geração de resumos | API OpenAI (remota) |
| `fast_lcf_atepc` (PyABSA / DeBERTa multilingual) | Extração de aspectos e sentimento bruto | Local (`checkpoints/`) |

O modelo PyABSA roda **100% local** (CPU ou GPU), sem chamadas externas. O `checkpoints/ATEPC_MULTILINGUAL_CHECKPOINT/` contém os arquivos de peso (`.state_dict`), tokenizer (`.tokenizer`) e configuração (`.config`).

---

## Dependências principais

| Pacote | Função |
|--------|--------|
| `openai` | Cliente OpenAI (tradução + categorização) |
| `pyabsa` | Extração de aspectos ATEPC |
| `torch` | Backend do PyABSA |
| `transformers` | Tokenizer DeBERTa (< 5.0) |
| `playwright` | Scraping headless (Chromium) |
| `loguru` | Logs do scraper |
| `python-dotenv` | Carrega `OPENAI_API_KEY` do `.env` |
| `pandas` | Exibição tabular no notebook |
