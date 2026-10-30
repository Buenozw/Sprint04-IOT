"""Ponte MQTT: interpretacao do payload do ESP32 e agregacao por janela."""

from mqtt_bridge.ponte_mqtt import Agregador, interpretar


def test_interpreta_payload_em_portugues():
    l = interpretar("petlink/rex/telemetria", b'{"temperatura": 38.4, "atividade": 55, "bpm": 92}')
    assert l == {"pet_id": "rex", "temperatura": 38.4, "atividade": 55, "bpm": 92}


def test_interpreta_payload_em_ingles_sem_bpm():
    l = interpretar("petlink/luna/telemetria", b'{"temperature": 38.7, "activity": 20}')
    assert l["pet_id"] == "luna" and l["temperatura"] == 38.7 and l["bpm"] is None


def test_payload_invalido_e_ignorado():
    assert interpretar("petlink/rex/telemetria", b"nao-e-json") is None
    assert interpretar("petlink/rex/telemetria", b'{"bpm": 90}') is None


def test_agregador_envia_media_quando_a_janela_fecha():
    ag = Agregador(60)
    base = {"pet_id": "rex", "bpm": None}
    assert ag.adicionar({**base, "temperatura": 38.0, "atividade": 40}, agora=0) is None
    assert ag.adicionar({**base, "temperatura": 38.4, "atividade": 60}, agora=30) is None
    m = ag.adicionar({**base, "temperatura": 38.2, "atividade": 50}, agora=61)
    assert m == {"pet_id": "rex", "temperatura": 38.2, "atividade": 50.0, "bpm": None}


def test_agregacao_desligada_repassa_cada_mensagem():
    l = {"pet_id": "rex", "temperatura": 38.0, "atividade": 40, "bpm": 80}
    assert Agregador(0).adicionar(l) == l
