"""Testes unitarios do modelo preditivo (ia/anomaly_detector.py)."""

import random
from datetime import datetime, timedelta

import pytest

from ia.anomaly_detector import (FUSO_BR, JANELA_LONGA, PetHealthMonitor, validar_leitura)
from simulador.modelo_fisiologico import PETS, episodio, historico_normal

INICIO = datetime(2026, 10, 1, tzinfo=FUSO_BR)


def monitor_com_historico(pet_id="rex", dias=7, seed=7):
    p = PETS[pet_id]
    mon = PetHealthMonitor(pet_id, p.raca, p.idade, p.especie, p.nome)
    fim = INICIO + timedelta(days=dias)
    for l in historico_normal(pet_id, dias, fim, seed=seed):
        mon.add_reading(l["temperatura"], l["atividade"], datetime.fromisoformat(l["timestamp"]), l["bpm"])
    return mon, fim


def alimentar(mon, linhas):
    alertas = []
    for l in linhas:
        mon.add_reading(l["temperatura"], l["atividade"], datetime.fromisoformat(l["timestamp"]), l["bpm"])
        alertas.append(mon.evaluate())
    return alertas


@pytest.mark.parametrize("pet_id", list(PETS))
def test_sem_falsos_alarmes_em_duas_semanas_normais(pet_id):
    p = PETS[pet_id]
    mon = PetHealthMonitor(pet_id, p.raca, p.idade, p.especie, p.nome)
    linhas = historico_normal(pet_id, 14, INICIO + timedelta(days=14), seed=11)
    alertas = [a for a in alimentar(mon, linhas)[24 * 2:] if a]   # ignora 2 dias de cold start
    assert len(alertas) <= 1


def test_leitura_atual_nao_entra_no_proprio_baseline():
    """Regressao da Sprint 3: a leitura avaliada diluia o proprio z-score."""
    mon, _ = monitor_com_historico()
    assert mon.baseline()["leituras_usadas"] == len(mon.history) - 1


def test_febre_e_detectada_e_classificada():
    mon, fim = monitor_com_historico()
    alertas = alimentar(mon, episodio("rex", "febre", fim))
    graves = [a for a in alertas if a and a.severity in ("media", "critica")]
    assert graves, "febre com prostracao deveria gerar alerta moderado ou critico"
    assert any("febre" in [d["tipo"] for d in a.details] for a in graves)


def test_febre_discreta_abaixo_do_limiar_fixo_e_detectada_no_rex():
    """O normal do Rex e 38,1 C: +0,7 C ainda fica abaixo de 39,2 C, mas e anomalo PARA ELE."""
    mon, fim = monitor_com_historico()
    linhas = episodio("rex", "febre_leve", fim)
    assert max(l["temperatura"] for l in linhas) < 39.2
    assert any(alimentar(mon, linhas))


def test_hipotermia_e_regra_clinica_critica():
    mon, fim = monitor_com_historico()
    alerta = alimentar(mon, episodio("rex", "hipotermia", fim))[0]
    assert alerta and alerta.severity == "critica"
    assert alerta.details[0]["tipo"] == "hipotermia"


def test_baseline_circadiano_sono_de_madrugada_nao_e_letargia():
    mon, fim = monitor_com_historico()
    madrugada = fim.replace(hour=3)
    if madrugada <= mon.history[-1].timestamp:
        madrugada += timedelta(days=1)
    mon.add_reading(38.1, 12, madrugada, 72)
    a = mon.evaluate()
    assert not a or "letargia" not in [d["tipo"] for d in a.details]


def test_mesma_atividade_a_tarde_e_letargia():
    mon, fim = monitor_com_historico()
    tarde = fim.replace(hour=15) + timedelta(days=1)
    mon.add_reading(38.1, 8, tarde - timedelta(hours=1), 72)
    mon.add_reading(38.1, 8, tarde, 72)
    a = mon.evaluate()
    assert a and "letargia" in [d["tipo"] for d in a.details]


def test_bpm_alto_durante_atividade_nao_alarma_mas_em_repouso_sim():
    mon, fim = monitor_com_historico()
    ts = fim.replace(hour=15) + timedelta(days=1)
    # Rex correndo (atividade 95): ~66 + 0,5*95 = 113 bpm esperados
    mon.add_reading(38.2, 95, ts, 116)
    a = mon.evaluate()
    assert not a or "taquicardia" not in [d["tipo"] for d in a.details]
    # Mesmo bpm com o pet em repouso
    mon.add_reading(38.2, 70, ts + timedelta(hours=1), 150)
    a = mon.evaluate()
    assert a and "taquicardia" in [d["tipo"] for d in a.details]


def test_persistencia_pico_fraco_isolado_nao_alerta():
    mon, fim = monitor_com_historico()
    base = mon.baseline()["temperatura"]
    leve = round(base["mediana"] + 3.3 * base["sigma"], 2)       # z ~ 3.3 (fraco)
    ts = fim + timedelta(hours=1)
    mon.add_reading(leve, 60, ts.replace(hour=15), 95)
    a = mon.evaluate()
    assert not a or "febre" not in [d["tipo"] for d in a.details]
    mon.add_reading(leve, 60, ts.replace(hour=16), 95)              # repetiu -> agora alerta
    a = mon.evaluate()
    assert a and "febre" in [d["tipo"] for d in a.details]


def test_tendencia_detecta_declinio_gradual():
    mon, fim = monitor_com_historico(dias=8)
    alertas = alimentar(mon, episodio("rex", "declinio_gradual", fim))
    tipos = {d["tipo"] for a in alertas if a for d in a.details}
    assert tipos & {"tendencia_queda_atividade", "tendencia_elevacao_temperatura", "letargia", "febre"}


def test_cold_start_usa_faixa_da_especie():
    mon = PetHealthMonitor("novo", "SRD", 2, "gato", "Mingau")
    mon.add_reading(39.8, 40, INICIO, 180)
    a = mon.evaluate()
    assert a and a.details[0]["tipo"] == "temperatura_fora_da_faixa"


@pytest.mark.parametrize("temp,atv,bpm,valida,status", [
    (38.5, 50, 90, True, "ok"),
    (85.0, 50, 90, False, "erro_sensor"),       # DS18B20 com defeito
    (38.5, 140, 90, False, "erro_sensor"),      # atividade fora de 0-100
    (26.0, 0, None, False, "coleira_fora_do_pet"),
])
def test_validacao_de_leituras(temp, atv, bpm, valida, status):
    v = validar_leitura(temp, atv, bpm)
    assert v.valida is valida and v.status_sensor == status


def test_bpm_impossivel_e_ignorado_sem_descartar_a_leitura():
    v = validar_leitura(38.4, 50, 999)
    assert v.valida and v.heart_rate is None


def test_alerta_serializa_em_json():
    mon, fim = monitor_com_historico()
    a = [x for x in alimentar(mon, episodio("rex", "febre", fim)) if x][0]
    d = a.to_dict()
    assert set(d) >= {"pet_id", "severity", "signals", "recommendation", "risk_score", "details"}
    assert 0 < d["risk_score"] <= 100
