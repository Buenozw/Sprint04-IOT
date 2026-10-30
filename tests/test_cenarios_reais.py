"""Cenarios reais de uso, de ponta a ponta pela API:
leitura -> validacao -> banco -> modelo preditivo -> IA generativa -> app/clinica."""

import pytest


def injetar(cliente, pet_id, cenario):
    r = cliente.post("/api/demo/cenario", json={"pet_id": pet_id, "cenario": cenario, "ao_vivo": False})
    assert r.status_code == 200
    return r.json()["alertas"]


@pytest.mark.parametrize("pet_id,cenario,sinal_esperado,severidades", [
    ("rex", "febre", "febre", {"media", "critica"}),
    ("rex", "letargia", "letargia", {"baixa", "media", "critica"}),
    ("luna", "taquicardia", "taquicardia", {"baixa", "media", "critica"}),
    ("bolinha", "hipotermia", "hipotermia", {"critica"}),
])
def test_cenario_clinico_gera_alerta_explicado(cliente, pet_id, cenario, sinal_esperado, severidades):
    alertas = injetar(cliente, pet_id, cenario)
    assert alertas, f"{cenario} deveria gerar alerta"
    tipos = {d["tipo"] for a in alertas for d in a["detalhes"]}
    assert sinal_esperado in tipos
    assert {a["severidade"] for a in alertas} & severidades
    for a in alertas:                       # IA generativa preencheu os dois publicos
        assert a["explicacao_tutor"] and a["resumo_clinico"]


def test_rotina_normal_nao_gera_alerta(cliente):
    assert injetar(cliente, "luna", "normal") == []
    assert cliente.get("/api/pets/luna").json()["status"] == "normal"


def test_coleira_fora_do_pet_nao_vira_alerta_de_hipotermia(cliente):
    alertas = injetar(cliente, "rex", "coleira_fora")
    assert alertas == []
    assert cliente.get("/api/pets/rex").json()["status"] == "coleira_fora_do_pet"


def test_declinio_gradual_e_percebido_antes_do_fim(cliente):
    alertas = injetar(cliente, "bolinha", "declinio_gradual")
    assert alertas
    leituras = cliente.get("/api/pets/bolinha/leituras?horas=72").json()
    fim_episodio = leituras[-1]["ts"]
    assert min(a["ts"] for a in alertas) < fim_episodio


def test_alertas_repetidos_nao_viram_spam(cliente):
    injetar(cliente, "rex", "febre")
    alertas = cliente.get("/api/pets/rex/alertas").json()
    assert len(alertas) <= 3                    # 10 horas de febre, poucas notificacoes
    assert sum(a["ocorrencias"] for a in alertas) > len(alertas)


def test_triagem_da_clinica_prioriza_o_pet_mais_grave(cliente):
    injetar(cliente, "bolinha", "letargia")
    injetar(cliente, "rex", "hipotermia")
    fila = cliente.get("/api/clinica/triagem").json()
    assert fila[0]["pet"]["id"] == "rex" and fila[0]["status"] == "critica"
    assert fila[-1]["risco"] <= fila[0]["risco"]


def test_assistente_explica_o_alerta_com_dados_do_pet(cliente):
    injetar(cliente, "rex", "febre")
    r = cliente.post("/api/pets/rex/chat", json={"mensagem": "Por que recebi esse alerta?"}).json()
    assert "Rex" in r["texto"] or "temperatura" in r["texto"].lower()
    resumo = cliente.get("/api/pets/rex/resumo").json()["texto"]
    assert "alerta" in resumo.lower()
