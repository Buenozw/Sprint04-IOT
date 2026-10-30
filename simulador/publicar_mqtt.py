"""
Simula a coleira publicando telemetria no broker MQTT (substitui o ESP32/Wokwi na demo).

Uso:
  python -m simulador.publicar_mqtt --pet rex --cenario febre --intervalo 2
  python -m simulador.publicar_mqtt --pet luna --cenario normal

Publica em petlink/<pet>/telemetria o mesmo JSON que o firmware do ESP32 envia.
Rode junto com a ponte (AGREGACAO_S=0 para repassar cada mensagem).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta

from mqtt_bridge.ponte_mqtt import MQTT_HOST, MQTT_PASS, MQTT_PORT, MQTT_TLS, MQTT_USER
from simulador.modelo_fisiologico import CENARIOS, FUSO_BR, PETS, episodio, historico_normal


def main():
    import paho.mqtt.client as mqtt
    import ssl

    ap = argparse.ArgumentParser()
    ap.add_argument("--pet", choices=list(PETS), default="rex")
    ap.add_argument("--cenario", choices=["normal", *CENARIOS], default="normal")
    ap.add_argument("--intervalo", type=float, default=2.0, help="segundos entre mensagens")
    a = ap.parse_args()

    inicio = datetime.now(FUSO_BR).replace(minute=0, second=0, microsecond=0)
    linhas = (historico_normal(a.pet, 1, inicio + timedelta(hours=24))[:6] if a.cenario == "normal"
              else episodio(a.pet, a.cenario, inicio))

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USER:
        c.username_pw_set(MQTT_USER, MQTT_PASS)
    if MQTT_TLS:
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.connect(MQTT_HOST, MQTT_PORT)
    c.loop_start()
    topico = f"petlink/{a.pet}/telemetria"
    for l in linhas:
        msg = {"temperatura": l["temperatura"], "atividade": l["atividade"], "bpm": l["bpm"]}
        c.publish(topico, json.dumps(msg), qos=1).wait_for_publish()
        print(topico, msg)
        time.sleep(a.intervalo)
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    main()
