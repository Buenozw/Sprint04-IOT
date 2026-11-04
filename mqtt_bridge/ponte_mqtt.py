"""
Ponte MQTT <-> API do PetLink.

  ESP32 (Wokwi/coleira)  --MQTT-->  HiveMQ Cloud  --MQTT-->  esta ponte  --HTTP-->  POST /api/leituras
                                                                    |
                    app / dashboard da clinica  <--MQTT-- petlink/<pet>/alertas  <--+  (se houver alerta)

Topico de entrada (padrao): petlink/<pet_id>/telemetria
Payload aceito (pt ou en):  {"temperatura": 38.4, "atividade": 55, "bpm": 92}
                            {"temperature": 38.4, "activity": 55, "heart_rate": 92}

Agregacao: o modelo trabalha com 1 leitura por janela (padrao 60 min). Se o ESP32
publica a cada poucos segundos, a ponte acumula e envia a MEDIA da janela.
Use AGREGACAO_S=0 para repassar cada mensagem (util na demonstracao).

Uso:  python -m mqtt_bridge.ponte_mqtt
Variaveis: MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TLS, MQTT_TOPICO, API_URL, AGREGACAO_S
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.request
from collections import defaultdict
from statistics import mean
from typing import Optional

from api import config  # noqa: F401  (carrega o .env)

log = logging.getLogger("petlink.mqtt")

MQTT_HOST = os.getenv("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")
MQTT_TLS = os.getenv("MQTT_TLS", "0") == "1"          # HiveMQ Cloud: porta 8883 + TLS=1
MQTT_TOPICO = os.getenv("MQTT_TOPICO", "petlink/+/telemetria")
API_URL = os.getenv("API_URL", "http://localhost:8000")
AGREGACAO_S = int(os.getenv("AGREGACAO_S", "3600"))

CAMPOS = {
    "temperatura": ("temperatura", "temperature", "temp"),
    "atividade": ("atividade", "activity", "activity_score"),
    "bpm": ("bpm", "heart_rate", "heartRate"),
}


def interpretar(topico: str, payload: bytes) -> Optional[dict]:
    """Extrai pet_id do topico (petlink/<pet>/telemetria) e normaliza os campos do JSON."""
    try:
        dados = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("Payload invalido em %s", topico)
        return None
    partes = topico.split("/")
    pet_id = dados.get("pet_id") or (partes[1] if len(partes) >= 3 else None)
    saida = {"pet_id": pet_id}
    for destino, nomes in CAMPOS.items():
        saida[destino] = next((dados[n] for n in nomes if n in dados), None)
    if not pet_id or saida["temperatura"] is None or saida["atividade"] is None:
        log.warning("Mensagem incompleta em %s: %s", topico, dados)
        return None
    return saida


class Agregador:
    """Acumula leituras por pet e libera a media quando a janela fecha."""

    def __init__(self, janela_s: int):
        self.janela_s = janela_s
        self.buffer = defaultdict(list)
        self.inicio = {}

    def adicionar(self, leitura: dict, agora: Optional[float] = None) -> Optional[dict]:
        if self.janela_s <= 0:
            return leitura
        agora = time.time() if agora is None else agora
        pid = leitura["pet_id"]
        self.inicio.setdefault(pid, agora)
        self.buffer[pid].append(leitura)
        if agora - self.inicio[pid] < self.janela_s:
            return None
        itens = self.buffer.pop(pid)
        self.inicio.pop(pid)
        bpms = [i["bpm"] for i in itens if i.get("bpm") is not None]
        return {"pet_id": pid,
                "temperatura": round(mean(i["temperatura"] for i in itens), 2),
                "atividade": round(mean(i["atividade"] for i in itens), 1),
                "bpm": round(mean(bpms)) if bpms else None}


def enviar_para_api(leitura: dict) -> dict:
    corpo = json.dumps({**leitura, "origem": "mqtt"}).encode()
    req = urllib.request.Request(f"{API_URL}/api/leituras", data=corpo,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    import paho.mqtt.client as mqtt

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    agregador = Agregador(AGREGACAO_S)
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"petlink-ponte-{os.getpid()}")
    if MQTT_USER:
        cliente.username_pw_set(MQTT_USER, MQTT_PASS)
    if MQTT_TLS:
        cliente.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    def ao_conectar(c, _u, _f, codigo, _p):
        log.info("Conectado ao broker %s:%s (codigo %s); assinando %s", MQTT_HOST, MQTT_PORT, codigo, MQTT_TOPICO)
        c.subscribe(MQTT_TOPICO, qos=1)

    def ao_receber(c, _u, msg):
        leitura = interpretar(msg.topic, msg.payload)
        if not leitura:
            return
        pronta = agregador.adicionar(leitura)
        if not pronta:
            return
        try:
            r = enviar_para_api(pronta)
        except Exception as e:
            log.error("Falha ao enviar para a API: %s", e)
            return
        a = r.get("alerta")
        if a and not r.get("alerta_suprimido"):
            c.publish(f"petlink/{pronta['pet_id']}/alertas", json.dumps(a, ensure_ascii=False), qos=1)
            log.warning("ALERTA %s para %s publicado", a["severidade"], pronta["pet_id"])
        else:
            log.info("%s: leitura processada (status=%s)", pronta["pet_id"], r.get("status"))

    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber
    cliente.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    cliente.loop_forever()


if __name__ == "__main__":
    main()
