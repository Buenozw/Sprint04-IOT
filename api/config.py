"""Configuracao via variaveis de ambiente (arquivo .env opcional na raiz)."""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _carregar_env():
    """Leitor minimo de .env (evita dependencia extra)."""
    arq = RAIZ / ".env"
    if not arq.exists():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


_carregar_env()

DB_PATH = os.getenv("PETLINK_DB", str(RAIZ / "petlink.db"))
SEED_AUTOMATICO = os.getenv("PETLINK_SEED", "1") == "1"      # popula 7 dias de historico se o banco estiver vazio

# ---------------------------------------------------------------------------
# IA generativa (opcional). Sem provedor configurado, o assistente roda em modo
# offline (templates) e a aplicacao continua funcionando.
#
# PETLINK_LLM_PROVIDER:
#   auto (padrao)  -> gemini se houver GEMINI_API_KEY; senao anthropic se houver
#                     ANTHROPIC_API_KEY; senao offline
#   gemini         -> Google Gemini (chave gratuita no Google AI Studio)
#   ollama         -> modelo local no seu computador, sem chave e sem custo
#   anthropic      -> Claude (pago, credito pre-pago)
#   openai_compat  -> qualquer API compativel com OpenAI (PETLINK_LLM_BASE_URL)
#   offline        -> forca o modo offline
# ---------------------------------------------------------------------------
PROVEDORES = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "modelo": "gemini-flash-latest", "chave_env": "GEMINI_API_KEY", "timeout": 30},
    "ollama": {"base_url": "http://localhost:11434/v1",
               "modelo": "llama3.2", "chave_env": None, "timeout": 120},
    "anthropic": {"base_url": "", "modelo": "claude-haiku-5-5", "chave_env": "ANTHROPIC_API_KEY", "timeout": 20},
    "openai_compat": {"base_url": "", "modelo": "", "chave_env": "PETLINK_LLM_API_KEY", "timeout": 30},
}


def _resolver_provedor() -> str:
    escolhido = os.getenv("PETLINK_LLM_PROVIDER", "auto").strip().lower() or "auto"
    if escolhido != "auto":
        return escolhido if escolhido in PROVEDORES or escolhido == "offline" else "offline"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "offline"


LLM_PROVEDOR = _resolver_provedor()
_preset = PROVEDORES.get(LLM_PROVEDOR, {"base_url": "", "modelo": "", "chave_env": None, "timeout": 20})
LLM_CHAVE = os.getenv(_preset["chave_env"], "") if _preset["chave_env"] else ""
LLM_MODELO = os.getenv("PETLINK_LLM_MODEL", "").strip() or _preset["modelo"]
LLM_BASE_URL = os.getenv("PETLINK_LLM_BASE_URL", "").strip() or _preset["base_url"]
LLM_TIMEOUT_S = float(os.getenv("PETLINK_LLM_TIMEOUT", "") or _preset["timeout"])
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")   # mantido por compatibilidade

# Alertas
COOLDOWN_ALERTA_H = 3        # novo alerta do mesmo pet so se piorar ou apos 3h
STATUS_JANELA_H = 6          # alerta nas ultimas 6h define o status atual do pet
