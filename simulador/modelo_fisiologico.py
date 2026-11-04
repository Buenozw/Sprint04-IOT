"""
Modelo fisiologico simulado dos pets do PetLink.

Gera leituras horarias realistas (temperatura, atividade com ritmo circadiano,
frequencia cardiaca correlacionada com a atividade) e injeta EPISODIOS clinicos
rotulados. E usado por:
  - seed do banco (historico inicial de 7 dias)
  - cenarios de demonstracao do painel / video
  - geracao do dataset rotulado de avaliacao (avaliacao/avaliar_modelo.py)

Os parametros sao plausiveis, mas SINTETICOS - nao sao dados clinicos reais.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

FUSO_BR = timezone(timedelta(hours=-3))


@dataclass
class PerfilPet:
    id: str
    nome: str
    especie: str          # cao | gato
    raca: str
    idade: float
    peso_kg: float
    tutor: str
    temp_media: float     # temperatura "normal" individual
    temp_sd: float
    act_base: float       # atividade media diaria (0-100)
    act_amp: float        # amplitude do ritmo circadiano
    act_pico: int         # hora do pico de atividade
    act_sd: float
    bpm_repouso: float
    bpm_k: float          # bpm adicionais por ponto de atividade
    bpm_sd: float


# Os tres pets acompanhados desde a Sprint 2. Note que o "normal" de cada um
# e diferente - e exatamente isso que um limiar fixo nao captura.
PETS: Dict[str, PerfilPet] = {
    "rex": PerfilPet("rex", "Rex", "cao", "Labrador", 5, 31, "Ana Souza",
                     38.1, 0.14, 46, 30, 15, 7, 66, 0.50, 5),
    "luna": PerfilPet("luna", "Luna", "gato", "Siamês", 3, 4.2, "Bruno Lima",
                      38.7, 0.14, 30, 20, 21, 6, 150, 0.40, 7),
    "bolinha": PerfilPet("bolinha", "Bolinha", "cao", "Poodle", 9, 6.5, "Carla Mendes",
                         38.95, 0.15, 34, 22, 11, 6, 92, 0.45, 6),
}


@dataclass
class Efeito:
    temp_delta: float = 0.0
    act_fator: float = 1.0
    bpm_delta: float = 0.0
    temp_absoluta: Optional[float] = None   # ex.: coleira fora do pet (temperatura ambiente)
    act_absoluta: Optional[float] = None


# --------------------------------------------------------------------------
# Cenarios clinicos (cada um devolve o efeito na hora h do episodio)
# --------------------------------------------------------------------------
def _rampa(h: int, horas: int = 2) -> float:
    return min(1.0, (h + 1) / horas)


CENARIOS = {
    "febre": dict(
        duracao=10, descricao="Quadro febril com prostração (ex.: infecção)",
        efeito=lambda h: Efeito(temp_delta=1.15 * _rampa(h), act_fator=1 - 0.45 * _rampa(h), bpm_delta=18 * _rampa(h))),
    "febre_leve": dict(
        duracao=8, descricao="Febre discreta (+0,7 °C) sem outros sinais",
        efeito=lambda h: Efeito(temp_delta=0.7 * _rampa(h))),
    "letargia": dict(
        duracao=12, descricao="Prostração/dor sem febre (ex.: pós-vacina, dor articular)",
        efeito=lambda h: Efeito(act_fator=0.35)),
    "taquicardia": dict(
        duracao=6, descricao="Frequência cardíaca elevada em repouso (ex.: dor, ansiedade, cardiopatia)",
        efeito=lambda h: Efeito(bpm_delta=38)),
    "declinio_gradual": dict(
        duracao=72, descricao="Piora lenta ao longo de 3 dias (ex.: doença crônica em início)",
        efeito=lambda h: Efeito(temp_delta=0.55 * h / 72, act_fator=1 - 0.55 * h / 72)),
    "hipotermia": dict(
        duracao=4, descricao="Hipotermia (temperatura < 36,5 °C), sinal de alerta clínico",
        efeito=lambda h: Efeito(temp_absoluta=36.1, act_fator=0.3, bpm_delta=-15)),
    "coleira_fora": dict(
        duracao=3, descricao="Coleira retirada ou solta: o sensor lê a temperatura ambiente",
        efeito=lambda h: Efeito(temp_absoluta=26.5, act_absoluta=0.0)),
}


def leitura(p: PerfilPet, ts: datetime, rng: random.Random, ef: Optional[Efeito] = None) -> dict:
    ef = ef or Efeito()
    hora = ts.astimezone(FUSO_BR).hour + ts.astimezone(FUSO_BR).minute / 60
    circ = math.cos((hora - p.act_pico) / 24 * 2 * math.pi)
    act = (p.act_base + p.act_amp * circ + rng.gauss(0, p.act_sd)) * ef.act_fator
    act = ef.act_absoluta if ef.act_absoluta is not None else act
    act = round(min(100.0, max(0.0, act)), 1)
    temp = p.temp_media + 0.12 * circ + rng.gauss(0, p.temp_sd) + ef.temp_delta
    temp = ef.temp_absoluta + rng.gauss(0, 0.1) if ef.temp_absoluta is not None else temp
    bpm = p.bpm_repouso + p.bpm_k * act + rng.gauss(0, p.bpm_sd) + ef.bpm_delta
    return {"timestamp": ts.isoformat(), "temperatura": round(temp, 2),
            "atividade": act, "bpm": round(bpm)}


def historico_normal(pet_id: str, dias: int, fim: datetime, seed: int = 7) -> List[dict]:
    p, rng = PETS[pet_id], random.Random(f"{pet_id}-{seed}")
    inicio = fim - timedelta(hours=24 * dias)
    return [leitura(p, inicio + timedelta(hours=i), rng) for i in range(24 * dias)]


def episodio(pet_id: str, cenario: str, inicio: datetime, seed: int = 99,
             horas: Optional[int] = None) -> List[dict]:
    p, rng, c = PETS[pet_id], random.Random(f"{pet_id}-{cenario}-{seed}"), CENARIOS[cenario]
    n = horas or c["duracao"]
    return [leitura(p, inicio + timedelta(hours=h), rng, c["efeito"](h)) for h in range(n)]


def serie_rotulada(pet_id: str, dias: int, seed: int, inicio: datetime) -> List[dict]:
    """Serie de `dias` dias com episodios clinicos aleatorios apos a 1a semana.

    Cada leitura recebe `episodio` (nome ou "") e `id_episodio` - o rotulo
    usado para medir recall, latencia e falsos alarmes.
    """
    p, rng = PETS[pet_id], random.Random(f"serie-{pet_id}-{seed}")
    clinicos = ["febre", "febre_leve", "letargia", "taquicardia", "declinio_gradual", "hipotermia"]
    total = 24 * dias
    eventos = {}            # hora_inicio -> cenario
    h = 24 * 8 + rng.randint(0, 48)
    while True:
        cen = rng.choice(clinicos)
        dur = CENARIOS[cen]["duracao"]
        if h + dur >= total - 24:
            break
        eventos[h] = cen
        h += dur + rng.randint(24 * 4, 24 * 8)   # 4-8 dias de "vida normal" entre episodios

    linhas, ativo, h_ep, id_ep = [], None, 0, 0
    for i in range(total):
        if i in eventos:
            ativo, h_ep, id_ep = eventos[i], 0, id_ep + 1
        ef = CENARIOS[ativo]["efeito"](h_ep) if ativo else None
        lin = leitura(p, inicio + timedelta(hours=i), rng, ef)
        lin.update(pet_id=pet_id, episodio=ativo or "", id_episodio=f"{pet_id}-{id_ep}" if ativo else "")
        linhas.append(lin)
        if ativo:
            h_ep += 1
            if h_ep >= CENARIOS[ativo]["duracao"]:
                ativo = None
    return linhas
