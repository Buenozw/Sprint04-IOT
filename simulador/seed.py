"""Popula o banco com os 3 pets e 7 dias de historico normal (baseline pronto para a demo).

Uso:  python -m simulador.seed        (recria o banco do zero)
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta

from api import database as db
from simulador.modelo_fisiologico import FUSO_BR, PETS, historico_normal

DIAS_HISTORICO = 7


def popular(limpar: bool = True, fim: datetime | None = None):
    db.inicializar()
    if limpar:
        db.limpar_tudo()
    fim = fim or datetime.now(FUSO_BR).replace(minute=0, second=0, microsecond=0)
    for p in PETS.values():
        db.salvar_pet({k: asdict(p)[k] for k in ("id", "nome", "especie", "raca", "idade", "peso_kg", "tutor")})
        linhas = historico_normal(p.id, DIAS_HISTORICO, fim + timedelta(hours=1), seed=7)
        db.inserir_leituras({"pet_id": p.id, "ts": l["timestamp"], "temperatura": l["temperatura"],
                             "atividade": l["atividade"], "bpm": l["bpm"], "valida": 1,
                             "status_sensor": "ok", "origem": "seed"} for l in linhas)
    return len(PETS) * DIAS_HISTORICO * 24


if __name__ == "__main__":
    n = popular()
    print(f"Banco populado: {len(PETS)} pets, {n} leituras de historico.")
