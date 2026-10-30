"""
Orquestracao da IA dentro da aplicacao.

Fluxo de cada leitura (vinda do app, do MQTT ou do simulador):

  validar  ->  persistir  ->  reconstruir baseline do pet a partir do banco
           ->  modelo preditivo (anomaly_detector)  ->  anti-spam (cooldown)
           ->  IA generativa explica o alerta (tutor + clinica)  ->  persistir
           ->  notificar inscritos (ex.: ponte MQTT publica em petlink/<pet>/alertas)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from statistics import mean
from typing import Callable, List, Optional

from api import config, database as db
from ia.anomaly_detector import (FUSO_BR, JANELA_CURTA, JANELA_LONGA, PetHealthMonitor,
                                 validar_leitura)
from ia.assistente_ia import AssistenteIA

SEVERIDADE_ORDEM = {"baixa": 1, "media": 2, "critica": 3}

assistente = AssistenteIA(config.ANTHROPIC_API_KEY, config.LLM_MODELO, config.LLM_TIMEOUT_S)
_inscritos_alerta: List[Callable[[dict], None]] = []
_cache_resumo: dict = {}


def inscrever_alertas(callback: Callable[[dict], None]):
    _inscritos_alerta.append(callback)


def agora() -> datetime:
    return datetime.now(FUSO_BR)


def _normalizar_ts(ts: Optional[datetime]) -> datetime:
    if ts is None:
        return agora().replace(microsecond=0)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=FUSO_BR)
    return ts.astimezone(FUSO_BR).replace(microsecond=0)


def montar_monitor(pet: dict) -> PetHealthMonitor:
    mon = PetHealthMonitor(pet_id=pet["id"], breed=pet["raca"], age_years=pet["idade"],
                           species=pet["especie"], pet_name=pet["nome"])
    for l in db.ultimas_leituras(pet["id"], JANELA_LONGA + 1):
        mon.add_reading(l["temperatura"], l["atividade"], datetime.fromisoformat(l["ts"]), l["bpm"])
    return mon


# ---------------------------------------------------------------------------
# Contexto do pet (alimenta a IA generativa e as telas)
# ---------------------------------------------------------------------------
def contexto_pet(pet: dict, mon: Optional[PetHealthMonitor] = None) -> dict:
    mon = mon or montar_monitor(pet)
    hist = list(mon.history)
    ultima = db.ultimas_leituras(pet["id"], 1, somente_validas=False)
    ultima = ultima[0] if ultima else None
    recentes = hist[-JANELA_CURTA:]
    ctx = {
        "baseline": mon.baseline(),
        "ultima_leitura": ({k: ultima[k] for k in ("ts", "temperatura", "atividade", "bpm", "status_sensor")}
                           if ultima else None),
        "leituras_24h": len(recentes),
    }
    if recentes:
        temps = [r.temperature for r in recentes]
        ctx["temperatura_24h"] = {"min": min(temps), "max": max(temps), "media": round(mean(temps), 2)}
        bpms = [r.heart_rate for r in recentes if r.heart_rate]
        if bpms:
            ctx["bpm_24h_medio"] = round(mean(bpms))
        antigas = hist[:-JANELA_CURTA] or hist
        razoes = []
        for r in recentes:
            esp, _ = mon._atividade_esperada(antigas, r.timestamp)
            if esp and esp > 1:
                razoes.append(r.activity_score / esp)
        ctx["atividade_vs_habitual"] = round(mean(razoes), 2) if razoes and len(antigas) >= 24 else None
    ref_ts = (datetime.fromisoformat(ultima["ts"]) if ultima else agora()) - timedelta(hours=24)
    alertas = [a for a in db.listar_alertas(pet["id"], 20) if a["ultima_ocorrencia"] >= ref_ts.isoformat()]
    ctx["alertas_24h"] = [{**{k: a[k] for k in ("ts", "severidade", "sinais", "recomendacao")},
                           "explicacao": a.get("explicacao_tutor")} for a in alertas]
    ctx["status"] = status_pet(pet["id"], ultima)
    return ctx


def status_pet(pet_id: str, ultima: Optional[dict] = None) -> str:
    """normal | baixa | media | critica | coleira_fora_do_pet | erro_sensor | sem_dados"""
    if ultima is None:
        u = db.ultimas_leituras(pet_id, 1, somente_validas=False)
        ultima = u[0] if u else None
    if not ultima:
        return "sem_dados"
    if ultima["status_sensor"] != "ok":
        return ultima["status_sensor"]
    a = db.ultimo_alerta(pet_id)
    if a:
        limite = datetime.fromisoformat(ultima["ts"]) - timedelta(hours=config.STATUS_JANELA_H)
        if datetime.fromisoformat(a["ultima_ocorrencia"]) >= limite:
            return a["severidade"]
    return "normal"


# ---------------------------------------------------------------------------
# Pipeline de ingestao
# ---------------------------------------------------------------------------
def ingerir_leitura(pet_id: str, temperatura: float, atividade: float, bpm: Optional[float] = None,
                    ts: Optional[datetime] = None, origem: str = "api", explicar: bool = True) -> dict:
    pet = db.obter_pet(pet_id)
    if not pet:
        raise KeyError(pet_id)
    ts = _normalizar_ts(ts)
    t0 = time.perf_counter()

    v = validar_leitura(temperatura, atividade, bpm)
    registro = {"pet_id": pet_id, "ts": ts.isoformat(), "temperatura": temperatura, "atividade": atividade,
                "bpm": v.heart_rate if v.valida else bpm, "valida": int(v.valida),
                "status_sensor": v.status_sensor, "origem": origem}
    registro["id"] = db.inserir_leitura(registro)
    resultado = {"leitura": registro, "valida": v.valida, "motivo": v.motivo, "alerta": None,
                 "alerta_suprimido": False, "status": None}
    if not v.valida:
        resultado["status"] = v.status_sensor
        resultado["latencia_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return resultado

    mon = montar_monitor(pet)
    alerta = mon.evaluate()
    if alerta:
        anterior = db.ultimo_alerta(pet_id)
        suprimir = False
        if anterior:
            dt = ts - datetime.fromisoformat(anterior["ultima_ocorrencia"])
            mesmo_ou_menor = SEVERIDADE_ORDEM[alerta.severity] <= SEVERIDADE_ORDEM[anterior["severidade"]]
            suprimir = timedelta(0) <= dt <= timedelta(hours=config.COOLDOWN_ALERTA_H) and mesmo_ou_menor
        if suprimir:
            db.registrar_reocorrencia(anterior["id"], ts.isoformat())
            resultado["alerta_suprimido"] = True
            resultado["alerta"] = db.obter_alerta(anterior["id"])
        else:
            dados = {"pet_id": pet_id, "ts": ts.isoformat(), "severidade": alerta.severity,
                     "risco": alerta.risk_score, "sinais": alerta.signals, "detalhes": alerta.details,
                     "mensagem": alerta.message, "recomendacao": alerta.recommendation}
            if explicar:
                exp = assistente.explicar_alerta(pet, dados, contexto_pet(pet, mon))
            else:
                exp = {**AssistenteIA._explicar_offline(pet, dados), "fonte": "offline"}
            dados.update(explicacao_tutor=exp["tutor"], resumo_clinico=exp["clinica"], fonte_ia=exp["fonte"],
                         sinais_json=json.dumps(alerta.signals, ensure_ascii=False),
                         detalhes_json=json.dumps(alerta.details, ensure_ascii=False))
            novo_id = db.inserir_alerta(dados)
            resultado["alerta"] = db.obter_alerta(novo_id)
            _cache_resumo.pop(pet_id, None)
            for cb in _inscritos_alerta:
                try:
                    cb(resultado["alerta"])
                except Exception:
                    pass
    resultado["status"] = status_pet(pet_id, registro)
    resultado["latencia_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return resultado


# ---------------------------------------------------------------------------
# Funcionalidades de IA generativa expostas na API
# ---------------------------------------------------------------------------
def resumo_diario(pet: dict) -> dict:
    ultima = db.ultimas_leituras(pet["id"], 1, somente_validas=False)
    chave = (ultima[0]["id"] if ultima else 0)
    cache = _cache_resumo.get(pet["id"])
    if cache and cache["chave"] == chave:
        return cache["resumo"]
    r = assistente.resumo_diario(pet, contexto_pet(pet))
    r["gerado_em"] = agora().isoformat()
    _cache_resumo[pet["id"]] = {"chave": chave, "resumo": r}
    return r


def conversar(pet: dict, pergunta: str) -> dict:
    historico = db.historico_chat(pet["id"])
    resp = assistente.responder(pet, contexto_pet(pet), historico, pergunta)
    ts = agora().isoformat()
    db.salvar_mensagem(pet["id"], ts, "tutor", pergunta)
    db.salvar_mensagem(pet["id"], ts, "assistente", resp["texto"], resp["fonte"])
    return resp


def triagem_clinica() -> List[dict]:
    """Fila de prioridade para a CLYVO VET: pets ordenados por risco atual."""
    fila = []
    for pet in db.listar_pets():
        ult = db.ultimas_leituras(pet["id"], 1, somente_validas=False)
        ult = ult[0] if ult else None
        status = status_pet(pet["id"], ult)
        alerta = db.ultimo_alerta(pet["id"])
        ativo = status in SEVERIDADE_ORDEM
        fila.append({
            "pet": pet, "status": status, "ultima_leitura": ult,
            "risco": alerta["risco"] if (alerta and ativo) else 0,
            "alerta": alerta if ativo else None,
        })
    fila.sort(key=lambda x: (-x["risco"], x["pet"]["nome"]))
    return fila
