"""IA generativa: caminho com LLM (cliente simulado), fallback e guardrails."""

from types import SimpleNamespace

from ia.assistente_ia import AssistenteIA, ORIENTACAO_EMERGENCIA, detectar_emergencia

PET = {"id": "rex", "nome": "Rex", "especie": "cao", "raca": "Labrador", "idade": 5}
ALERTA = {"severidade": "critica", "risco": 100, "sinais": ["Temperatura 39.6°C acima do normal"],
          "detalhes": [{"tipo": "febre", "z_score": 7.8}], "recomendacao": "Procurar atendimento veterinário com urgência (hoje)."}


class ClienteFalso:
    """Imita anthropic.Anthropic().messages.create e registra o que foi pedido."""

    def __init__(self, resposta=None, erro=None):
        self.resposta, self.erro, self.chamadas = resposta, erro, []
        self.messages = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        if self.erro:
            raise self.erro
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.resposta)])


def assistente_com(cliente):
    a = AssistenteIA()
    a._cliente = cliente
    return a


def test_explicacao_via_llm_e_lida_do_json():
    falso = ClienteFalso('Aqui está: {"tutor": "Rex está com febre.", "clinica": "T 39,6 °C, z=+7,8."}')
    r = assistente_com(falso).explicar_alerta(PET, ALERTA, {})
    assert r == {"tutor": "Rex está com febre.", "clinica": "T 39,6 °C, z=+7,8.", "fonte": "llm"}
    pedido = falso.chamadas[0]
    assert "NUNCA de diagnostico" in pedido["system"] and "Labrador" in pedido["messages"][0]["content"]


def test_json_invalido_cai_no_modo_offline():
    r = assistente_com(ClienteFalso("sem json aqui")).explicar_alerta(PET, ALERTA, {})
    assert r["fonte"] == "offline" and "Rex" in r["tutor"]


def test_falha_de_rede_nao_derruba_a_aplicacao():
    r = assistente_com(ClienteFalso(erro=TimeoutError("timeout"))).responder(PET, {}, [], "Como ele está?")
    assert r["fonte"] == "offline" and r["texto"]


def test_sem_chave_o_modo_e_offline():
    assert AssistenteIA(api_key="").modo == "offline"


def test_emergencia_tem_orientacao_fixa_mesmo_com_llm():
    falso = ClienteFalso("Fique calmo e observe.")
    r = assistente_com(falso).responder(PET, {}, [], "Acho que ele comeu chocolate e está vomitando")
    assert r["emergencia"] and r["texto"].startswith(ORIENTACAO_EMERGENCIA)


def test_historico_do_chat_alterna_papeis_para_a_api():
    falso = ClienteFalso("ok")
    hist = [{"papel": "assistente", "texto": "Olá"}, {"papel": "tutor", "texto": "Oi"},
            {"papel": "tutor", "texto": "Tudo bem?"}, {"papel": "assistente", "texto": "Sim"}]
    assistente_com(falso).responder(PET, {}, hist, "E a temperatura?")
    papeis = [m["role"] for m in falso.chamadas[0]["messages"]]
    assert papeis[0] == "user" and all(a != b for a, b in zip(papeis, papeis[1:]))


def test_deteccao_de_emergencia_ignora_acentos():
    assert detectar_emergencia("CONVULSÃO agora") and not detectar_emergencia("ele brincou muito hoje")


# ---------------------------------------------------------------------------
# Provedores gratuitos (Gemini / Ollama): endpoint compativel com OpenAI
# ---------------------------------------------------------------------------
import json as _json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


@pytest.fixture()
def servidor_openai():
    """Servidor local que imita POST /chat/completions e guarda o ultimo pedido."""
    estado = {"pedidos": [], "status": 200,
              "resposta": {"choices": [{"message": {"role": "assistant", "content": "Olá do modelo!"}}]}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            corpo = self.rfile.read(int(self.headers["Content-Length"]))
            estado["pedidos"].append({"path": self.path, "auth": self.headers.get("Authorization"),
                                      "json": _json.loads(corpo)})
            dados = _json.dumps(estado["resposta"] if estado["status"] == 200
                                else {"error": {"message": "quota"}}).encode()
            self.send_response(estado["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    estado["url"] = f"http://127.0.0.1:{srv.server_address[1]}/v1beta/openai"
    yield estado
    srv.shutdown()


def test_gemini_envia_formato_openai_com_chave(servidor_openai):
    ia = AssistenteIA(api_key="chave-teste", modelo="gemini-flash-latest", provedor="gemini",
                      base_url=servidor_openai["url"])
    assert ia.modo == "llm"
    r = ia.responder(PET, {}, [], "Como ele está?")
    assert r == {"texto": "Olá do modelo!", "fonte": "llm", "emergencia": False}
    pedido = servidor_openai["pedidos"][0]
    assert pedido["path"] == "/v1beta/openai/chat/completions"
    assert pedido["auth"] == "Bearer chave-teste"
    assert pedido["json"]["model"] == "gemini-flash-latest"
    assert pedido["json"]["messages"][0]["role"] == "system"
    assert "NUNCA de diagnostico" in pedido["json"]["messages"][0]["content"]


def test_ollama_funciona_sem_chave(servidor_openai):
    ia = AssistenteIA(modelo="llama3.2", provedor="ollama", base_url=servidor_openai["url"])
    assert ia.modo == "llm"
    assert ia.resumo_diario(PET, {})["fonte"] == "llm"
    assert servidor_openai["pedidos"][0]["auth"] is None


def test_explicacao_de_alerta_via_gemini(servidor_openai):
    servidor_openai["resposta"] = {"choices": [{"message": {
        "content": '```json\n{"tutor": "Rex está com febre.", "clinica": "T 39,6 °C."}\n```'}}]}
    ia = AssistenteIA(api_key="k", modelo="m", provedor="gemini", base_url=servidor_openai["url"])
    assert ia.explicar_alerta(PET, ALERTA, {}) == {"tutor": "Rex está com febre.", "clinica": "T 39,6 °C.",
                                                   "fonte": "llm"}


def test_limite_gratuito_cai_no_offline_e_guarda_o_erro(servidor_openai):
    servidor_openai["status"] = 429
    ia = AssistenteIA(api_key="k", modelo="m", provedor="gemini", base_url=servidor_openai["url"])
    r = ia.explicar_alerta(PET, ALERTA, {})
    assert r["fonte"] == "offline" and "Rex" in r["tutor"]
    assert ia.ultimo_erro.startswith("HTTP 429")


def test_gemini_sem_chave_fica_offline():
    assert AssistenteIA(provedor="gemini", modelo="m", base_url="http://x").modo == "offline"


def test_config_escolhe_gemini_quando_ha_chave(monkeypatch):
    import importlib
    from api import config
    monkeypatch.setenv("PETLINK_LLM_PROVIDER", "auto")
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("PETLINK_LLM_MODEL", "")
    try:
        c = importlib.reload(config)
        assert (c.LLM_PROVEDOR, c.LLM_CHAVE, c.LLM_MODELO) == ("gemini", "abc", "gemini-flash-latest")
        assert c.LLM_BASE_URL == "https://generativelanguage.googleapis.com/v1beta/openai"
    finally:
        monkeypatch.setenv("PETLINK_LLM_PROVIDER", "offline")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        importlib.reload(config)
