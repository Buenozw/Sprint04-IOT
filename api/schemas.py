"""Modelos de entrada da API (validacao de dados com Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field


class LeituraEntrada(BaseModel):
    """Aceita nomes em portugues ou ingles (compativel com o payload do ESP32)."""
    pet_id: str = Field(validation_alias=AliasChoices("pet_id", "petId", "pet"))
    temperatura: float = Field(validation_alias=AliasChoices("temperatura", "temperature", "temp"))
    atividade: float = Field(validation_alias=AliasChoices("atividade", "activity", "activity_score"))
    bpm: Optional[float] = Field(default=None, validation_alias=AliasChoices("bpm", "heart_rate", "heartRate"))
    timestamp: Optional[datetime] = Field(default=None, validation_alias=AliasChoices("timestamp", "ts"))
    origem: Literal["api", "mqtt", "app", "demo"] = "api"


class PetEntrada(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_\-]{2,32}$")
    nome: str = Field(min_length=1, max_length=40)
    especie: Literal["cao", "gato"]
    raca: str = Field(min_length=1, max_length=40)
    idade: float = Field(ge=0, le=30)
    peso_kg: Optional[float] = Field(default=None, gt=0, le=120)
    tutor: Optional[str] = None


class PerguntaChat(BaseModel):
    mensagem: str = Field(min_length=1, max_length=600)


class CenarioDemo(BaseModel):
    pet_id: str
    cenario: Literal["normal", "febre", "febre_leve", "letargia", "taquicardia",
                     "declinio_gradual", "hipotermia", "coleira_fora"]
    ao_vivo: bool = True              # True: 1 leitura a cada `intervalo_s` (bom para gravar o video)
    intervalo_s: float = Field(default=2.0, ge=0.2, le=30)
