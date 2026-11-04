"""
COPIA CONGELADA do modelo da Sprint 3 - usada apenas como comparacao na avaliacao.

PetLink - Modulo de IA (Modelo Preditivo)

Deteccao de anomalias e tendencias de saude a partir de series temporais
de sensores (temperatura corporal e nivel de atividade) coletados pelo
collar ESP32-S3 e pelo modulo de visao computacional.

Abordagem: baseline estatistico individual (media movel + z-score) por pet,
com classificacao de severidade combinando multiplos sinais.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import deque
from statistics import mean, pstdev
from typing import Optional, Deque, List
import json

WINDOW_SHORT = 24      # leituras equivalentes a ~24h (curto prazo)
WINDOW_LONG = 24 * 7   # leituras equivalentes a ~7 dias (linha de base)
MIN_READINGS_FOR_BASELINE = 20   # minimo de leituras antes de confiar no baseline
Z_SCORE_THRESHOLD = 2.0          # limiar de desvio considerado anomalo

# Faixas fisiologicas de referencia (fallback ate haver baseline suficiente)
DEFAULT_TEMP_RANGE = (37.5, 39.2)   # graus Celsius, media para caes/gatos adultos


@dataclass
class SensorReading:
    timestamp: datetime
    temperature: float          # graus Celsius (DS18B20)
    activity_score: float       # indice normalizado 0-100 (modulo CV)


@dataclass
class Alert:
    pet_id: str
    timestamp: str
    severity: str                # "baixa" | "media" | "critica"
    signals: List[str]
    message: str
    recommendation: str

    def to_dict(self):
        return {
            "pet_id": self.pet_id,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "signals": self.signals,
            "message": self.message,
            "recommendation": self.recommendation,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class PetHealthMonitor:
    """Mantem o historico e o baseline individual de um pet, e avalia novas leituras em busca de anomalias."""

    pet_id: str
    breed: str = "SRD"
    age_years: float = 3.0
    history: Deque[SensorReading] = field(default_factory=lambda: deque(maxlen=WINDOW_LONG))

    # --- ingestao ---
    def add_reading(self, temperature: float, activity_score: float,
                     timestamp: Optional[datetime] = None) -> None:
        ts = timestamp or datetime.now(timezone.utc)
        self.history.append(SensorReading(ts, temperature, activity_score))

    # --- baseline ---
    def _baseline(self, attr: str, window: int):
        readings = [getattr(r, attr) for r in list(self.history)[-window:]]
        if len(readings) < MIN_READINGS_FOR_BASELINE:
            return None, None
        return mean(readings), pstdev(readings) or 0.01  # evita divisao por zero

    def _z_score(self, value: float, mu: float, sigma: float) -> float:
        return (value - mu) / sigma

    # --- avaliacao ---
    def evaluate(self) -> Optional[Alert]:
        if not self.history:
            return None

        latest = self.history[-1]
        signals: List[str] = []
        severity_score = 0

        temp_mu, temp_sigma = self._baseline("temperature", WINDOW_LONG)
        act_mu, act_sigma = self._baseline("activity_score", WINDOW_LONG)

        # --- Sinal 1: temperatura ---
        if temp_mu is not None:
            z_temp = self._z_score(latest.temperature, temp_mu, temp_sigma)
            if z_temp > Z_SCORE_THRESHOLD:
                signals.append(
                    f"Temperatura {latest.temperature:.1f}°C acima da linha de base "
                    f"({temp_mu:.1f}°C ± {temp_sigma:.2f})"
                )
                severity_score += 2 if z_temp > Z_SCORE_THRESHOLD * 1.5 else 1
        else:
            low, high = DEFAULT_TEMP_RANGE
            if not (low <= latest.temperature <= high):
                signals.append(
                    f"Temperatura {latest.temperature:.1f}°C fora da faixa de "
                    f"referencia padrao ({low}-{high}°C) — baseline individual "
                    f"ainda em formacao"
                )
                severity_score += 1

        # --- Sinal 2: atividade ---
        if act_mu is not None:
            z_act = self._z_score(latest.activity_score, act_mu, act_sigma)
            if z_act < -Z_SCORE_THRESHOLD:
                signals.append(
                    f"Nivel de atividade {latest.activity_score:.0f} muito abaixo "
                    f"da linha de base (possivel sedentarismo/mal-estar)"
                )
                severity_score += 2 if z_act < -Z_SCORE_THRESHOLD * 1.5 else 1

        if not signals:
            return None  # sem anomalia

        # --- Classificacao de severidade combinada ----
        if severity_score >= 3:
            severity = "critica"
            recommendation = "Agendar consulta veterinaria com urgencia (mesmo dia)."
        elif severity_score == 2:
            severity = "media"
            recommendation = "Observar o pet nas proximas horas e considerar agendar consulta."
        else:
            severity = "baixa"
            recommendation = "Monitorar continuamente; nenhuma acao imediata necessaria."

        return Alert(
            pet_id=self.pet_id,
            timestamp=latest.timestamp.isoformat(),
            severity=severity,
            signals=signals,
            message=f"Anomalia detectada para o pet '{self.pet_id}' ({self.breed}, {self.age_years} anos).",
            recommendation=recommendation,
        )

