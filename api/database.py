"""Persistencia em SQLite (biblioteca padrao) - pets, leituras, alertas e conversas."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterable, List, Optional

from api import config

_lock = threading.Lock()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pets (
    id          TEXT PRIMARY KEY,
    nome        TEXT NOT NULL,
    especie     TEXT NOT NULL CHECK (especie IN ('cao', 'gato')),
    raca        TEXT NOT NULL,
    idade       REAL NOT NULL,
    peso_kg     REAL,
    tutor       TEXT
);

CREATE TABLE IF NOT EXISTS leituras (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id        TEXT NOT NULL REFERENCES pets(id),
    ts            TEXT NOT NULL,                 -- ISO 8601, fuso -03:00
    temperatura   REAL NOT NULL,
    atividade     REAL NOT NULL,
    bpm           REAL,
    valida        INTEGER NOT NULL DEFAULT 1,
    status_sensor TEXT NOT NULL DEFAULT 'ok',
    origem        TEXT NOT NULL DEFAULT 'api'    -- api | mqtt | seed | demo
);
CREATE INDEX IF NOT EXISTS idx_leituras_pet_ts ON leituras (pet_id, ts);

CREATE TABLE IF NOT EXISTS alertas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id           TEXT NOT NULL REFERENCES pets(id),
    ts               TEXT NOT NULL,
    ultima_ocorrencia TEXT NOT NULL,
    ocorrencias      INTEGER NOT NULL DEFAULT 1,
    severidade       TEXT NOT NULL,
    risco            INTEGER NOT NULL,
    sinais_json      TEXT NOT NULL,
    detalhes_json    TEXT NOT NULL,
    mensagem         TEXT NOT NULL,
    recomendacao     TEXT NOT NULL,
    explicacao_tutor TEXT,
    resumo_clinico   TEXT,
    fonte_ia         TEXT,
    lido             INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alertas_pet_ts ON alertas (pet_id, ts);

CREATE TABLE IF NOT EXISTS mensagens_chat (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id  TEXT NOT NULL REFERENCES pets(id),
    ts      TEXT NOT NULL,
    papel   TEXT NOT NULL CHECK (papel IN ('tutor', 'assistente')),
    texto   TEXT NOT NULL,
    fonte   TEXT
);
"""


@contextmanager
def conexao():
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        with _lock:
            yield con
            con.commit()
    finally:
        con.close()


def inicializar():
    with conexao() as con:
        con.executescript(ESQUEMA)


def limpar_tudo():
    with conexao() as con:
        con.executescript("DELETE FROM mensagens_chat; DELETE FROM alertas; DELETE FROM leituras; DELETE FROM pets;")


# ---------------- pets ----------------
def salvar_pet(p: dict):
    with conexao() as con:
        con.execute("""INSERT INTO pets (id, nome, especie, raca, idade, peso_kg, tutor)
                       VALUES (:id, :nome, :especie, :raca, :idade, :peso_kg, :tutor)
                       ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, especie=excluded.especie,
                       raca=excluded.raca, idade=excluded.idade, peso_kg=excluded.peso_kg, tutor=excluded.tutor""", p)


def listar_pets() -> List[dict]:
    with conexao() as con:
        return [dict(r) for r in con.execute("SELECT * FROM pets ORDER BY nome")]


def obter_pet(pet_id: str) -> Optional[dict]:
    with conexao() as con:
        r = con.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()
        return dict(r) if r else None


# ---------------- leituras ----------------
def inserir_leituras(linhas: Iterable[dict]):
    with conexao() as con:
        con.executemany("""INSERT INTO leituras (pet_id, ts, temperatura, atividade, bpm, valida, status_sensor, origem)
                           VALUES (:pet_id, :ts, :temperatura, :atividade, :bpm, :valida, :status_sensor, :origem)""",
                        list(linhas))


def inserir_leitura(l: dict) -> int:
    with conexao() as con:
        cur = con.execute("""INSERT INTO leituras (pet_id, ts, temperatura, atividade, bpm, valida, status_sensor, origem)
                             VALUES (:pet_id, :ts, :temperatura, :atividade, :bpm, :valida, :status_sensor, :origem)""", l)
        return cur.lastrowid


def ultimas_leituras(pet_id: str, limite: int, somente_validas: bool = True) -> List[dict]:
    """Retorna as `limite` leituras mais recentes em ordem cronologica."""
    filtro = "AND valida = 1" if somente_validas else ""
    with conexao() as con:
        rows = con.execute(f"""SELECT * FROM leituras WHERE pet_id = ? {filtro}
                               ORDER BY ts DESC, id DESC LIMIT ?""", (pet_id, limite)).fetchall()
    return [dict(r) for r in reversed(rows)]


def leituras_desde(pet_id: str, ts_inicio: str) -> List[dict]:
    with conexao() as con:
        rows = con.execute("SELECT * FROM leituras WHERE pet_id = ? AND ts >= ? ORDER BY ts, id",
                           (pet_id, ts_inicio)).fetchall()
    return [dict(r) for r in rows]


# ---------------- alertas ----------------
def _alerta_dict(r) -> dict:
    d = dict(r)
    d["sinais"] = json.loads(d.pop("sinais_json"))
    d["detalhes"] = json.loads(d.pop("detalhes_json"))
    d["lido"] = bool(d["lido"])
    return d


def inserir_alerta(a: dict) -> int:
    with conexao() as con:
        cur = con.execute("""INSERT INTO alertas (pet_id, ts, ultima_ocorrencia, severidade, risco, sinais_json,
                             detalhes_json, mensagem, recomendacao, explicacao_tutor, resumo_clinico, fonte_ia)
                             VALUES (:pet_id, :ts, :ts, :severidade, :risco, :sinais_json, :detalhes_json,
                             :mensagem, :recomendacao, :explicacao_tutor, :resumo_clinico, :fonte_ia)""", a)
        return cur.lastrowid


def registrar_reocorrencia(alerta_id: int, ts: str):
    with conexao() as con:
        con.execute("UPDATE alertas SET ocorrencias = ocorrencias + 1, ultima_ocorrencia = ? WHERE id = ?",
                    (ts, alerta_id))


def ultimo_alerta(pet_id: str) -> Optional[dict]:
    with conexao() as con:
        r = con.execute("SELECT * FROM alertas WHERE pet_id = ? ORDER BY ultima_ocorrencia DESC, id DESC LIMIT 1",
                        (pet_id,)).fetchone()
        return _alerta_dict(r) if r else None


def listar_alertas(pet_id: Optional[str] = None, limite: int = 50) -> List[dict]:
    with conexao() as con:
        if pet_id:
            rows = con.execute("SELECT * FROM alertas WHERE pet_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
                               (pet_id, limite)).fetchall()
        else:
            rows = con.execute("SELECT * FROM alertas ORDER BY ts DESC, id DESC LIMIT ?", (limite,)).fetchall()
        return [_alerta_dict(r) for r in rows]


def obter_alerta(alerta_id: int) -> Optional[dict]:
    with conexao() as con:
        r = con.execute("SELECT * FROM alertas WHERE id = ?", (alerta_id,)).fetchone()
        return _alerta_dict(r) if r else None


def marcar_lido(alerta_id: int) -> bool:
    with conexao() as con:
        return con.execute("UPDATE alertas SET lido = 1 WHERE id = ?", (alerta_id,)).rowcount > 0


# ---------------- chat ----------------
def salvar_mensagem(pet_id: str, ts: str, papel: str, texto: str, fonte: Optional[str] = None):
    with conexao() as con:
        con.execute("INSERT INTO mensagens_chat (pet_id, ts, papel, texto, fonte) VALUES (?, ?, ?, ?, ?)",
                    (pet_id, ts, papel, texto, fonte))


def historico_chat(pet_id: str, limite: int = 12) -> List[dict]:
    with conexao() as con:
        rows = con.execute("SELECT * FROM mensagens_chat WHERE pet_id = ? ORDER BY id DESC LIMIT ?",
                           (pet_id, limite)).fetchall()
    return [dict(r) for r in reversed(rows)]
