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
