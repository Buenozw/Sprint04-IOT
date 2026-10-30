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

# IA generativa (opcional). Sem chave, o assistente roda em modo offline (templates).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODELO = os.getenv("PETLINK_LLM_MODEL", "claude-haiku-5-5")
LLM_TIMEOUT_S = float(os.getenv("PETLINK_LLM_TIMEOUT", "20"))

# Alertas
COOLDOWN_ALERTA_H = 3        # novo alerta do mesmo pet so se piorar ou apos 3h
STATUS_JANELA_H = 6          # alerta nas ultimas 6h define o status atual do pet
