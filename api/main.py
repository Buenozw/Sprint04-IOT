"""
PetLink API (FastAPI) - integra o modelo de IA com app, banco e dispositivos IoT.

Rodar:  uvicorn api.main:app --reload
Docs interativas: http://localhost:8000/docs     Painel: http://localhost:8000/
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import config, database as db, servico
from api.schemas import CenarioDemo, LeituraEntrada, PerguntaChat, PetEntrada
from simulador import seed
from simulador.modelo_fisiologico import CENARIOS, FUSO_BR, PETS, episodio, historico_normal

@asynccontextmanager
async def _ciclo_de_vida(_app):
    db.inicializar()
    if config.SEED_AUTOMATICO and not db.listar_pets():
        seed.popular(limpar=False)
    yield
    for t in _demos.values():
        t.cancel()


app = FastAPI(
    lifespan=_ciclo_de_vida,
    title="PetLink API — IA integrada",
    version="4.0.0",
    description="Coleira inteligente PetLink (CLYVO VET): ingestão IoT, modelo preditivo de anomalias "
                "e assistente de IA generativa para tutores e clínica.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

WEB = config.RAIZ / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")

_demos: Dict[str, asyncio.Task] = {}


def _pet_ou_404(pet_id: str) -> dict:
    pet = db.obter_pet(pet_id)
    if not pet:
        raise HTTPException(404, f"Pet '{pet_id}' nao encontrado")
    return pet


# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def painel():
    return FileResponse(WEB / "index.html")


@app.get("/api/saude", tags=["sistema"])
def saude():
    return {"status": "ok", "ia_generativa": servico.assistente.modo, "modelo_llm": config.LLM_MODELO,
            "pets": len(db.listar_pets())}


# ----------------------------- pets ----------------------------------------
@app.get("/api/pets", tags=["pets"])
def listar_pets():
    saida = []
    for p in db.listar_pets():
        ult = db.ultimas_leituras(p["id"], 1, somente_validas=False)
        saida.append({**p, "status": servico.status_pet(p["id"]), "ultima_leitura": ult[0] if ult else None})
    return saida


@app.post("/api/pets", status_code=201, tags=["pets"])
def cadastrar_pet(pet: PetEntrada):
    db.salvar_pet(pet.model_dump())
    return db.obter_pet(pet.id)


@app.get("/api/pets/{pet_id}", tags=["pets"])
def detalhe_pet(pet_id: str):
    pet = _pet_ou_404(pet_id)
    return {**pet, **servico.contexto_pet(pet)}


@app.get("/api/pets/{pet_id}/leituras", tags=["pets"])
def leituras(pet_id: str, horas: int = Query(48, ge=1, le=24 * 30)):
    _pet_ou_404(pet_id)
    ult = db.ultimas_leituras(pet_id, 1, somente_validas=False)
    if not ult:
        return []
    inicio = datetime.fromisoformat(ult[0]["ts"]) - timedelta(hours=horas)
    return db.leituras_desde(pet_id, inicio.isoformat())


@app.get("/api/pets/{pet_id}/alertas", tags=["alertas"])
def alertas_pet(pet_id: str, limite: int = Query(20, ge=1, le=200)):
    _pet_ou_404(pet_id)
    return db.listar_alertas(pet_id, limite)


@app.get("/api/alertas", tags=["alertas"])
def todos_alertas(limite: int = Query(50, ge=1, le=500)):
    return db.listar_alertas(None, limite)


@app.patch("/api/alertas/{alerta_id}/lido", tags=["alertas"])
def marcar_lido(alerta_id: int):
    if not db.marcar_lido(alerta_id):
        raise HTTPException(404, "Alerta nao encontrado")
    return db.obter_alerta(alerta_id)


# ----------------------------- ingestao IoT --------------------------------
@app.post("/api/leituras", tags=["iot"])
def receber_leitura(l: LeituraEntrada):
    """Ponto de entrada das leituras (ESP32 via HTTP, ponte MQTT, app ou simulador)."""
    _pet_ou_404(l.pet_id)
    return servico.ingerir_leitura(l.pet_id, l.temperatura, l.atividade, l.bpm, l.timestamp, l.origem)


# ----------------------------- IA generativa -------------------------------
@app.get("/api/pets/{pet_id}/resumo", tags=["ia"])
def resumo(pet_id: str):
    """Boletim diario personalizado (IA generativa)."""
    return servico.resumo_diario(_pet_ou_404(pet_id))


@app.post("/api/pets/{pet_id}/chat", tags=["ia"])
def chat(pet_id: str, p: PerguntaChat):
    """Assistente conversacional do tutor, com respostas baseadas nos dados reais do pet."""
    return servico.conversar(_pet_ou_404(pet_id), p.mensagem)


@app.get("/api/pets/{pet_id}/chat", tags=["ia"])
def historico_chat(pet_id: str):
    _pet_ou_404(pet_id)
    return db.historico_chat(pet_id, 40)


@app.get("/api/clinica/triagem", tags=["clinica"])
def triagem():
    """Fila de prioridade da CLYVO VET: pets ordenados pelo risco calculado pela IA."""
    return servico.triagem_clinica()


# ----------------------------- demonstracao --------------------------------
def _gerar_cenario(pet_id: str, cenario: str):
    ult = db.ultimas_leituras(pet_id, 1, somente_validas=False)
    inicio = (datetime.fromisoformat(ult[0]["ts"]) if ult else datetime.now(FUSO_BR)) + timedelta(hours=1)
    seed_var = int(inicio.timestamp()) % 10_000
    if cenario == "normal":
        return historico_normal(pet_id, 1, inicio + timedelta(hours=24), seed=seed_var)[:6]
    return episodio(pet_id, cenario, inicio, seed=seed_var)


async def _rodar_cenario(pet_id: str, linhas, intervalo: float):
    for l in linhas:
        await asyncio.to_thread(servico.ingerir_leitura, pet_id, l["temperatura"], l["atividade"], l["bpm"],
                                datetime.fromisoformat(l["timestamp"]), "demo")
        await asyncio.sleep(intervalo)


@app.post("/api/demo/cenario", tags=["demonstracao"])
async def demo_cenario(c: CenarioDemo):
    """Injeta um cenario clinico simulado (1 leitura = 1 hora simulada)."""
    _pet_ou_404(c.pet_id)
    if c.pet_id not in PETS:
        raise HTTPException(400, "Cenarios de demonstracao existem apenas para os pets simulados")
    linhas = _gerar_cenario(c.pet_id, c.cenario)
    anterior = _demos.pop(c.pet_id, None)
    if anterior and not anterior.done():
        anterior.cancel()
    if c.ao_vivo:
        _demos[c.pet_id] = asyncio.create_task(_rodar_cenario(c.pet_id, linhas, c.intervalo_s))
        return {"iniciado": True, "leituras": len(linhas), "duracao_estimada_s": len(linhas) * c.intervalo_s}
    resultados = [await asyncio.to_thread(servico.ingerir_leitura, c.pet_id, l["temperatura"], l["atividade"],
                                          l["bpm"], datetime.fromisoformat(l["timestamp"]), "demo")
                  for l in linhas]
    return {"iniciado": True, "leituras": len(linhas),
            "alertas": [r["alerta"] for r in resultados if r["alerta"] and not r["alerta_suprimido"]]}


@app.get("/api/demo/cenarios", tags=["demonstracao"])
def demo_cenarios():
    return {"normal": "6 horas de comportamento normal",
            **{k: v["descricao"] for k, v in CENARIOS.items()}}


@app.get("/api/demo/estado", tags=["demonstracao"])
def demo_estado():
    return {pid: not t.done() for pid, t in _demos.items()}


@app.post("/api/demo/reset", tags=["demonstracao"])
def demo_reset():
    for t in _demos.values():
        t.cancel()
    _demos.clear()
    servico._cache_resumo.clear()
    n = seed.popular(limpar=True)
    return {"ok": True, "leituras_historico": n}
