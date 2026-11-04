"""
PetLink - Modulo de IA preditiva (Sprint 4)

Deteccao de anomalias e tendencias de saude a partir das series temporais
coletadas pela coleira ESP32-S3 (temperatura DS18B20, frequencia cardiaca)
e pelo modulo de visao computacional (indice de atividade 0-100).

Evolucao em relacao a Sprint 3
------------------------------
1. Baseline ROBUSTO: mediana + MAD (em vez de media + desvio padrao), para que
   episodios anomalos antigos nao "contaminem" a linha de base do pet.
2. A leitura avaliada NAO entra mais no calculo do proprio baseline
   (na Sprint 3 ela entrava e diluia o z-score).
3. Baseline CIRCADIANO de atividade: cada leitura e comparada com a mesma
   faixa horaria (+-1h) dos dias anteriores - o pet dormir de madrugada
   deixa de ser "anomalia".
4. Frequencia cardiaca AJUSTADA pela atividade: regressao linear por pet
   (bpm ~ a + b * atividade). Avaliamos o residuo, entao taquicardia em repouso
   e detectada mas bpm alto durante uma corrida nao gera alarme.
5. PERSISTENCIA: desvio fraco so vira alerta se aparecer em 2 leituras
   seguidas (picos isolados de ruido sao descartados); desvio forte alerta na hora.
6. Deteccao de TENDENCIA (carater preditivo): queda sustentada de atividade
   ou elevacao gradual de temperatura nas ultimas 24h vs. os 6 dias anteriores.
7. Regras clinicas de seguranca (red flags) que sobrepoem a estatistica.
8. Validacao das leituras de sensor (descarta erro de sensor e detecta
   coleira fora do pet).

Somente biblioteca padrao - roda em qualquer Python >= 3.10.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from statistics import median, linear_regression, StatisticsError
from typing import Deque, List, Optional

# --------------------------------------------------------------------------
# Parametros do modelo (ajustados no conjunto de VALIDACAO - ver avaliacao/)
# --------------------------------------------------------------------------
JANELA_LONGA = 24 * 7          # ~7 dias de leituras horarias (baseline)
JANELA_CURTA = 24              # ~24h (tendencia)
MIN_LEITURAS_BASELINE = 24     # antes disso usamos as faixas de referencia
Z_LIMIAR = 3.0                 # desvio robusto considerado anomalo
Z_FORTE = 4.5                  # desvio forte (peso 2 na severidade)
QUEDA_TENDENCIA = 0.70         # atividade media 24h < 70% do esperado
ELEVACAO_TENDENCIA_C = 0.45    # temperatura mediana 24h subiu >= 0,45 C

# Pisos de dispersao: evitam sigma ~0 quando o pet e muito estavel
SIGMA_MIN = {"temperatura": 0.12, "atividade": 4.0, "bpm": 4.0}

# Faixas de referencia por especie (cold start, ate o baseline existir)
FAIXAS_REFERENCIA = {
    "cao":  {"temperatura": (37.5, 39.2), "bpm": (60, 140)},
    "gato": {"temperatura": (38.0, 39.2), "bpm": (140, 220)},
}

# Regras clinicas de seguranca (independem do baseline)
TEMP_RED_FLAG_ALTA = 40.5
TEMP_RED_FLAG_BAIXA = 36.5

# Validacao de sensor
TEMP_FORA_DO_PET = 35.0        # abaixo disso: coleira solta / fora do pet
TEMP_VALIDA = (25.0, 45.0)     # fora disso: erro de leitura do DS18B20
BPM_VALIDO = (20, 320)

FUSO_BR = timezone(timedelta(hours=-3))   # America/Sao_Paulo (sem horario de verao)

PERIODOS = (
    ("madrugada", 0, 6),
    ("manhã", 6, 12),
    ("tarde", 12, 18),
    ("noite", 18, 24),
)


def periodo_do_dia(ts: datetime) -> str:
    hora = ts.astimezone(FUSO_BR).hour if ts.tzinfo else ts.hour
    for nome, ini, fim in PERIODOS:
        if ini <= hora < fim:
            return nome
    return "noite"


# --------------------------------------------------------------------------
# Estruturas de dados
# --------------------------------------------------------------------------
@dataclass
class SensorReading:
    timestamp: datetime
    temperature: float              # graus Celsius (DS18B20)
    activity_score: float           # indice 0-100 (modulo de visao computacional)
    heart_rate: Optional[float] = None  # bpm (sensor da coleira) - opcional


@dataclass
class Sinal:
    tipo: str            # febre | hipotermia | letargia | taquicardia | bradicardia | tendencia_* | ...
    descricao: str
    valor: float
    referencia: Optional[float] = None
    z_score: Optional[float] = None
    peso: int = 1


@dataclass
class Alert:
    pet_id: str
    timestamp: str
    severity: str                   # "baixa" | "media" | "critica"
    signals: List[str]
    message: str
    recommendation: str
    risk_score: int = 0             # 0-100, usado na triagem da clinica
    details: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class ValidacaoLeitura:
    valida: bool
    motivo: Optional[str] = None
    status_sensor: str = "ok"       # ok | erro_sensor | coleira_fora_do_pet
    heart_rate: Optional[float] = None


def validar_leitura(temperatura: float, atividade: float,
                    bpm: Optional[float] = None) -> ValidacaoLeitura:
    """Preparacao de dados: filtra leituras fisicamente impossiveis antes do modelo."""
    if temperatura is None or not (TEMP_VALIDA[0] <= temperatura <= TEMP_VALIDA[1]):
        return ValidacaoLeitura(False, f"Temperatura {temperatura} fora da faixa do sensor", "erro_sensor")
    if atividade is None or not (0 <= atividade <= 100):
        return ValidacaoLeitura(False, f"Atividade {atividade} fora do intervalo 0-100", "erro_sensor")
    if temperatura < TEMP_FORA_DO_PET:
        return ValidacaoLeitura(False, "Temperatura próxima da ambiente: coleira possivelmente fora do pet",
                                "coleira_fora_do_pet")
    bpm_ok = bpm if (bpm is not None and BPM_VALIDO[0] <= bpm <= BPM_VALIDO[1]) else None
    return ValidacaoLeitura(True, heart_rate=bpm_ok)


# --------------------------------------------------------------------------
# Estatistica robusta
# --------------------------------------------------------------------------
def _mediana_mad(valores: List[float], piso: float):
    """Retorna (mediana, sigma robusto). sigma = 1.4826 * MAD ~ desvio padrao para dados normais."""
    if not valores:
        return None, None
    med = median(valores)
    mad = median(abs(v - med) for v in valores)
    return med, max(1.4826 * mad, piso)


# --------------------------------------------------------------------------
# Monitor individual
# --------------------------------------------------------------------------
@dataclass
class PetHealthMonitor:
    """Historico + baseline individual de um pet; avalia cada nova leitura."""

    pet_id: str
    breed: str = "SRD"
    age_years: float = 3.0
    species: str = "cao"            # "cao" | "gato"
    pet_name: Optional[str] = None
    history: Deque[SensorReading] = field(default_factory=lambda: deque(maxlen=JANELA_LONGA + 1))

    # ---------------- ingestao ----------------
    def add_reading(self, temperature: float, activity_score: float,
                    timestamp: Optional[datetime] = None,
                    heart_rate: Optional[float] = None) -> None:
        ts = timestamp or datetime.now(timezone.utc)
        self.history.append(SensorReading(ts, temperature, activity_score, heart_rate))

    # ---------------- baselines ----------------
    def _referencia(self) -> List[SensorReading]:
        """Leituras anteriores a atual (a atual nunca entra no proprio baseline)."""
        return list(self.history)[:-1][-JANELA_LONGA:]

    def baseline(self) -> Optional[dict]:
        """Resumo do baseline atual - exposto pela API para o app e a clinica."""
        ref = self._referencia() if len(self.history) > 1 else list(self.history)
        if len(ref) < MIN_LEITURAS_BASELINE:
            return None
        t_med, t_sig = _mediana_mad([r.temperature for r in ref], SIGMA_MIN["temperatura"])
        perfil = []
        for hora in range(24):
            ts_ref = datetime(2026, 1, 1, hora, tzinfo=FUSO_BR)
            m, sg = self._atividade_esperada(ref, ts_ref)
            perfil.append({"hora": hora, "mediana": round(m, 1), "sigma": round(sg, 1)})
        bpm_vals = [r.heart_rate for r in ref if r.heart_rate is not None]
        bpm_med, _ = _mediana_mad(bpm_vals, SIGMA_MIN["bpm"]) if bpm_vals else (None, None)
        return {
            "leituras_usadas": len(ref),
            "z_limiar": Z_LIMIAR,
            "temperatura": {"mediana": round(t_med, 2), "sigma": round(t_sig, 2)},
            "perfil_atividade_horario": perfil,
            "bpm_mediana": round(bpm_med, 1) if bpm_med else None,
        }

    def _atividade_esperada(self, ref: List[SensorReading], ts: datetime):
        """Atividade habitual na MESMA faixa horaria (hora atual +- 1h) dos dias anteriores."""
        hora = ts.astimezone(FUSO_BR).hour if ts.tzinfo else ts.hour
        vals = []
        for r in ref:
            h = r.timestamp.astimezone(FUSO_BR).hour if r.timestamp.tzinfo else r.timestamp.hour
            if min((h - hora) % 24, (hora - h) % 24) <= 1:
                vals.append(r.activity_score)
        if len(vals) < 6:  # pouca historia nessa faixa -> usa o dia todo
            vals = [r.activity_score for r in ref]
        return _mediana_mad(vals, SIGMA_MIN["atividade"])

    def _modelo_bpm(self, ref: List[SensorReading]):
        """Regressao linear bpm ~ atividade (por pet) + sigma robusto dos residuos."""
        pares = [(r.activity_score, r.heart_rate) for r in ref if r.heart_rate is not None]
        if len(pares) < MIN_LEITURAS_BASELINE:
            return None
        xs, ys = zip(*pares)
        try:
            inclinacao, intercepto = linear_regression(xs, ys)
        except StatisticsError:
            return None
        residuos = [y - (intercepto + inclinacao * x) for x, y in pares]
        _, sigma = _mediana_mad(residuos, SIGMA_MIN["bpm"])
        return intercepto, inclinacao, sigma

    # ---------------- sinais pontuais ----------------
    def _sinais_pontuais(self, atual: SensorReading, ref: List[SensorReading],
                         ignorar_temp: bool) -> List[Sinal]:
        sinais: List[Sinal] = []
        # ---- Sinal 1: temperatura vs baseline individual ----
        t_med, t_sig = _mediana_mad([r.temperature for r in ref], SIGMA_MIN["temperatura"])
        z_t = (atual.temperature - t_med) / t_sig
        if not ignorar_temp and abs(z_t) >= Z_LIMIAR:
            tipo = "febre" if z_t > 0 else "temperatura_baixa"
            direcao = "acima" if z_t > 0 else "abaixo"
            sinais.append(Sinal(
                tipo, f"Temperatura {atual.temperature:.1f}°C {direcao} do normal deste pet "
                      f"({t_med:.1f}°C ± {t_sig:.2f}), z={z_t:+.1f}",
                atual.temperature, round(t_med, 2), round(z_t, 2), 2 if abs(z_t) >= Z_FORTE else 1))

        # ---- Sinal 2: atividade vs mesma faixa horaria ----
        periodo = periodo_do_dia(atual.timestamp)
        a_med, a_sig = self._atividade_esperada(ref, atual.timestamp)
        z_a = (atual.activity_score - a_med) / a_sig
        if z_a <= -Z_LIMIAR:
            sinais.append(Sinal(
                "letargia", f"Atividade {atual.activity_score:.0f} muito abaixo do habitual "
                            f"para este horário ({periodo}: {a_med:.0f} ± {a_sig:.0f}), z={z_a:+.1f}",
                atual.activity_score, round(a_med, 1), round(z_a, 2), 2 if z_a <= -Z_FORTE else 1))

        # ---- Sinal 3: frequencia cardiaca ajustada pela atividade ----
        if atual.heart_rate is not None:
            modelo = self._modelo_bpm(ref)
            if modelo:
                a, b, s = modelo
                esperado = a + b * atual.activity_score
                z_b = (atual.heart_rate - esperado) / s
                if abs(z_b) >= Z_LIMIAR:
                    tipo = "taquicardia" if z_b > 0 else "bradicardia"
                    sinais.append(Sinal(
                        tipo, f"Frequência cardíaca {atual.heart_rate:.0f} bpm vs ~{esperado:.0f} bpm "
                              f"esperados para esse nível de atividade, z={z_b:+.1f}",
                        atual.heart_rate, round(esperado, 1), round(z_b, 2), 2 if abs(z_b) >= Z_FORTE else 1))
        return sinais

    # ---------------- avaliacao ----------------
    def evaluate(self) -> Optional[Alert]:
        if not self.history:
            return None

        atual = self.history[-1]
        ref = self._referencia()
        sinais: List[Sinal] = []
        red_flag = False

        # ---- Regras clinicas de seguranca ----
        if atual.temperature >= TEMP_RED_FLAG_ALTA:
            red_flag = True
            sinais.append(Sinal("febre_alta", f"Temperatura {atual.temperature:.1f}°C acima de "
                                f"{TEMP_RED_FLAG_ALTA}°C (limite clínico)", atual.temperature, peso=3))
        elif atual.temperature <= TEMP_RED_FLAG_BAIXA:
            red_flag = True
            sinais.append(Sinal("hipotermia", f"Temperatura {atual.temperature:.1f}°C abaixo de "
                                f"{TEMP_RED_FLAG_BAIXA}°C (limite clínico)", atual.temperature, peso=3))

        if len(ref) >= MIN_LEITURAS_BASELINE:
            pontuais = self._sinais_pontuais(atual, ref, red_flag)
            # Persistencia: sinal fraco (peso 1) so conta se tambem apareceu na
            # leitura anterior - elimina "picos" isolados de ruido do sensor.
            hist = list(self.history)
            if len(hist) >= 3:
                ref_ant = hist[:-2][-JANELA_LONGA:]
                tipos_ant = ({s.tipo for s in self._sinais_pontuais(hist[-2], ref_ant, False)}
                             if len(ref_ant) >= MIN_LEITURAS_BASELINE else set())
            else:
                tipos_ant = set()
            sinais.extend(s for s in pontuais if s.peso >= 2 or s.tipo in tipos_ant)

            # ---- Sinal 4: tendencias (ultimas 24h vs dias anteriores) ----
            sinais.extend(self._tendencias())
        else:
            # ---- Cold start: faixas de referencia por especie ----
            faixa = FAIXAS_REFERENCIA.get(self.species, FAIXAS_REFERENCIA["cao"])
            lo, hi = faixa["temperatura"]
            if not red_flag and not (lo <= atual.temperature <= hi):
                sinais.append(Sinal("temperatura_fora_da_faixa",
                                    f"Temperatura {atual.temperature:.1f}°C fora da faixa de referência "
                                    f"({lo}-{hi}°C); baseline individual ainda em formação",
                                    atual.temperature, peso=1))
            if atual.heart_rate is not None:
                lo, hi = faixa["bpm"]
                if not (lo * 0.8 <= atual.heart_rate <= hi * 1.3):
                    sinais.append(Sinal("bpm_fora_da_faixa",
                                        f"Frequência cardíaca {atual.heart_rate:.0f} bpm fora da faixa "
                                        f"de referência; baseline em formação", atual.heart_rate, peso=1))

        if not sinais:
            return None
        return self._montar_alerta(atual, sinais, red_flag)

    def _tendencias(self) -> List[Sinal]:
        hist = list(self.history)
        if len(hist) < MIN_LEITURAS_BASELINE + JANELA_CURTA:
            return []
        recentes, antigas = hist[-JANELA_CURTA:], hist[:-JANELA_CURTA][-JANELA_LONGA:]
        sinais = []

        # A tendencia precisa estar EM CURSO: vale para as ultimas 24h e tambem
        # para as ultimas 6h (evita alertar no dia seguinte a um episodio ja resolvido).
        def razao_atividade(janela):
            razoes = []
            for r in janela:
                esperado, _ = self._atividade_esperada(antigas, r.timestamp)
                if esperado and esperado > 1:
                    razoes.append(r.activity_score / esperado)
            return sum(razoes) / len(razoes) if razoes else None

        razao_24h, razao_6h = razao_atividade(recentes), razao_atividade(recentes[-6:])
        if razao_24h is not None and razao_24h < QUEDA_TENDENCIA and razao_6h < QUEDA_TENDENCIA:
            sinais.append(Sinal("tendencia_queda_atividade",
                                f"Atividade das últimas 24h em {razao_24h*100:.0f}% do habitual "
                                f"(queda sustentada, ainda em curso)", round(razao_24h, 2), 1.0, peso=1))

        t_ant = median(r.temperature for r in antigas)
        t_24h = median(r.temperature for r in recentes)
        t_6h = median(r.temperature for r in recentes[-6:])
        if t_24h - t_ant >= ELEVACAO_TENDENCIA_C and t_6h - t_ant >= ELEVACAO_TENDENCIA_C:
            sinais.append(Sinal("tendencia_elevacao_temperatura",
                                f"Temperatura mediana das últimas 24h {t_24h:.1f}°C vs {t_ant:.1f}°C "
                                f"nos dias anteriores (elevação gradual)", round(t_24h, 2), round(t_ant, 2), peso=1))
        return sinais

    def _montar_alerta(self, atual: SensorReading, sinais: List[Sinal], red_flag: bool) -> Alert:
        pontos = sum(s.peso for s in sinais)
        if red_flag or pontos >= 3:
            severidade = "critica"
            recomendacao = "Procurar atendimento veterinário com urgência (hoje)."
        elif pontos == 2:
            severidade = "media"
            recomendacao = "Observar o pet nas próximas horas e agendar consulta se os sinais persistirem."
        else:
            severidade = "baixa"
            recomendacao = "Sem ação imediata; o PetLink segue monitorando."
        risco = min(100, 25 * pontos + (30 if red_flag else 0))
        nome = self.pet_name or self.pet_id
        return Alert(
            pet_id=self.pet_id,
            timestamp=atual.timestamp.isoformat(),
            severity=severidade,
            signals=[s.descricao for s in sinais],
            message=f"Anomalia detectada para {nome} ({self.breed}, {self.age_years:g} anos).",
            recommendation=recomendacao,
            risk_score=risco,
            details=[asdict(s) for s in sinais],
        )


# --------------------------------------------------------------------------
# Demonstracao rapida: python -m ia.anomaly_detector
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import math
    import random

    random.seed(42)
    monitor = PetHealthMonitor(pet_id="rex", pet_name="Rex", breed="Labrador", age_years=5)
    inicio = datetime(2026, 10, 1, tzinfo=FUSO_BR)

    def atividade_normal(h):
        return max(0.0, 45 + 30 * math.sin((h - 9) / 24 * 2 * math.pi) + random.gauss(0, 6))

    print("=== Fase 1: 7 dias normais (baseline individual) ===")
    falsos = 0
    for i in range(JANELA_LONGA):
        ts = inicio + timedelta(hours=i)
        act = atividade_normal(ts.hour)
        monitor.add_reading(round(random.gauss(38.2, 0.15), 2), round(act, 1), ts,
                            round(70 + 0.5 * act + random.gauss(0, 5)))
        falsos += monitor.evaluate() is not None
    print(f"Alertas durante a fase normal: {falsos} em {JANELA_LONGA} leituras")
    print("Baseline:", json.dumps(monitor.baseline(), ensure_ascii=False))

    print("\n=== Fase 2: febre + prostracao ===")
    ts = inicio + timedelta(hours=JANELA_LONGA)
    monitor.add_reading(39.4, 12, ts, 128)
    alerta = monitor.evaluate()
    print(alerta.to_json() if alerta else "Nenhuma anomalia")
