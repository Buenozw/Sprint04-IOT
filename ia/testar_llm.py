"""
Testa a conexao com o provedor de IA generativa configurado no .env.

Uso:  python -m ia.testar_llm

Mostra qual provedor/modelo foi lido e faz UMA chamada curta. Se falhar,
explica o motivo mais provavel. Rode antes de gravar o video.
"""

from __future__ import annotations

import sys

from api import config
from ia.assistente_ia import AssistenteIA

DICAS = {
    "HTTP 400": "Pedido recusado. Confira o nome do modelo em PETLINK_LLM_MODEL (ou deixe vazio para usar o padrao).",
    "HTTP 401": "Chave invalida. Gere outra e confira se foi copiada inteira, sem espacos.",
    "HTTP 403": "Chave sem permissao para esse modelo ou API desativada no projeto.",
    "HTTP 404": "Modelo nao encontrado. Troque PETLINK_LLM_MODEL (ex.: gemini-flash-latest).",
    "HTTP 429": "Limite gratuito atingido. Espere 1 minuto (ou ate o dia seguinte) ou use outro modelo, "
           "ex.: PETLINK_LLM_MODEL=gemini-3.5-flash-lite",
    "Connection refused": "Nada respondendo nesse endereco. No Ollama, abra o aplicativo ou rode `ollama serve`.",
    "timed out": "Demorou demais. No Ollama, a primeira resposta e lenta; aumente PETLINK_LLM_TIMEOUT.",
}


def main() -> int:
    print(f"Provedor : {config.LLM_PROVEDOR}")
    print(f"Modelo   : {config.LLM_MODELO or '-'}")
    print(f"Endereco : {config.LLM_BASE_URL or '-'}")
    print(f"Chave    : {'configurada' if config.LLM_CHAVE else 'nao configurada'}")

    ia = AssistenteIA(api_key=config.LLM_CHAVE, modelo=config.LLM_MODELO, timeout=config.LLM_TIMEOUT_S,
                      provedor=config.LLM_PROVEDOR, base_url=config.LLM_BASE_URL)
    if ia.modo != "llm":
        print("\nModo OFFLINE: nenhum provedor configurado. Veja o passo a passo no README "
              "(secao 'IA generativa gratuita').")
        return 1

    texto = ia._gerar("Responda em portugues do Brasil, em uma frase curta.",
                      [{"role": "user", "content": "Diga ola para o tutor do PetLink."}], max_tokens=60)
    if texto:
        print(f"\nOK! Resposta do modelo:\n  {texto}")
        return 0

    erro = ia.ultimo_erro or "sem resposta"
    print(f"\nFALHOU: {erro}")
    for trecho, dica in DICAS.items():
        if trecho in erro:
            print(f"Dica: {dica}")
            break
    return 2


if __name__ == "__main__":
    sys.exit(main())
