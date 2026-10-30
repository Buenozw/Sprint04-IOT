"""Contrato da API: validacao de entrada, integracao com dispositivos e guardrails do assistente."""


def test_saude_informa_modo_da_ia(cliente):
    r = cliente.get("/api/saude").json()
    assert r["status"] == "ok" and r["ia_generativa"] in ("llm", "offline") and r["pets"] == 3


def test_leitura_com_payload_do_esp32_em_ingles(cliente):
    r = cliente.post("/api/leituras", json={"pet_id": "rex", "temperature": 38.2, "activity": 55, "heart_rate": 92})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["valida"] and corpo["leitura"]["temperatura"] == 38.2 and corpo["leitura"]["bpm"] == 92


def test_leitura_mal_formada_e_rejeitada(cliente):
    assert cliente.post("/api/leituras", json={"pet_id": "rex", "temperatura": "quente", "atividade": 5}).status_code == 422
    assert cliente.post("/api/leituras", json={"pet_id": "rex"}).status_code == 422


def test_pet_inexistente(cliente):
    assert cliente.post("/api/leituras", json={"pet_id": "fantasma", "temperatura": 38, "atividade": 5}).status_code == 404
    assert cliente.get("/api/pets/fantasma").status_code == 404


def test_erro_de_sensor_e_registrado_mas_nao_analisado(cliente):
    r = cliente.post("/api/leituras", json={"pet_id": "luna", "temperatura": 85, "atividade": 30}).json()
    assert r["valida"] is False and r["alerta"] is None and r["status"] == "erro_sensor"


def test_cadastro_de_pet_novo_entra_em_cold_start(cliente):
    novo = {"id": "mingau", "nome": "Mingau", "especie": "gato", "raca": "SRD", "idade": 1, "peso_kg": 3.5}
    assert cliente.post("/api/pets", json=novo).status_code == 201
    r = cliente.post("/api/leituras", json={"pet_id": "mingau", "temperatura": 40.0, "atividade": 20}).json()
    assert r["alerta"]["detalhes"][0]["tipo"] == "temperatura_fora_da_faixa"
    assert cliente.get("/api/pets/mingau").json()["baseline"] is None


def test_cadastro_invalido(cliente):
    r = cliente.post("/api/pets", json={"id": "X Y", "nome": "", "especie": "peixe", "raca": "?", "idade": -1})
    assert r.status_code == 422


def test_marcar_alerta_como_lido(cliente):
    cliente.post("/api/demo/cenario", json={"pet_id": "rex", "cenario": "febre", "ao_vivo": False})
    alerta = cliente.get("/api/pets/rex/alertas").json()[0]
    assert cliente.patch(f"/api/alertas/{alerta['id']}/lido").json()["lido"] is True
    assert cliente.patch("/api/alertas/99999/lido").status_code == 404


def test_chat_detecta_emergencia(cliente):
    r = cliente.post("/api/pets/rex/chat", json={"mensagem": "Ele está tendo uma convulsão!"}).json()
    assert r["emergencia"] is True and "emergência" in r["texto"]


def test_chat_nao_prescreve_medicamento(cliente):
    r = cliente.post("/api/pets/rex/chat", json={"mensagem": "Posso dar dipirona pra baixar a febre?"}).json()
    assert "Não posso indicar medicamentos" in r["texto"]


def test_chat_guarda_historico(cliente):
    cliente.post("/api/pets/luna/chat", json={"mensagem": "Como está a temperatura?"})
    hist = cliente.get("/api/pets/luna/chat").json()
    assert [m["papel"] for m in hist[-2:]] == ["tutor", "assistente"]


def test_painel_web_e_servido(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "PetLink" in r.text
    assert cliente.get("/static/app.jsx").status_code == 200
