"""
Avaliacao quantitativa do modelo de IA do PetLink.

Compara tres abordagens sobre series SINTETICAS rotuladas (3 pets x 90 dias,
leituras horarias, episodios clinicos injetados):

  A) Limiar fixo        - regra classica "febre se T > 39,2 °C" etc.
  B) Modelo Sprint 3    - z-score global (media/desvio), so temperatura+atividade
  C) Modelo Sprint 4    - baseline robusto individual, circadiano, bpm ajustado,
                          persistencia, tendencias e regras clinicas

Protocolo
  - Conjunto de VALIDACAO (seed 1): usado para escolher o limiar de z-score.
  - Conjunto de TESTE (seed 2): usado SO para reportar o resultado final.

Metricas
  - Recall por episodio: o episodio gerou ao menos um alerta enquanto ocorria?
  - Latencia: horas entre o inicio do episodio e o primeiro alerta.
  - Falsos alarmes: notificacoes fora de episodios, por pet por semana
    (alertas a menos de 3h um do outro contam como UMA notificacao - igual a API).
  - Precisao / recall / F1 por leitura.

Uso:  python -m avaliacao.avaliar_modelo
Gera: docs/RESULTADOS.md, docs/img/*.png, dados/dataset_*.csv
"""

from __future__ import annotations

import csv
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from ia import anomaly_detector as s4                       # noqa: E402
from avaliacao import modelo_sprint3 as s3                  # noqa: E402
from simulador.modelo_fisiologico import PETS, serie_rotulada, FUSO_BR, CENARIOS  # noqa: E402

DIAS = 90
COOLDOWN_H = 3
TOLERANCIA_POS_EPISODIO_H = 6   # recuperacao: nao conta como acerto nem como falso alarme
INICIO = datetime(2026, 6, 1, tzinfo=FUSO_BR)

COR = {"fixo": "#eb6834", "s3": "#1baf7a", "s4": "#2a78d6"}
NOME = {"fixo": "Limiar fixo", "s3": "Modelo Sprint 3", "s4": "Modelo Sprint 4"}
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"


# --------------------------------------------------------------------------
# Detectores (interface comum: alimentar(linha) -> bool alerta)
# --------------------------------------------------------------------------
class LimiarFixo:
    def __init__(self, pet):
        faixa = s4.FAIXAS_REFERENCIA[pet.especie]
        self.t_lo, self.t_hi = faixa["temperatura"]
        self.b_lo, self.b_hi = faixa["bpm"]

    def alimentar(self, lin) -> bool:
        hora = datetime.fromisoformat(lin["timestamp"]).hour
        return (not (self.t_lo <= lin["temperatura"] <= self.t_hi)
                or not (self.b_lo <= lin["bpm"] <= self.b_hi)
                or (9 <= hora <= 19 and lin["atividade"] < 8))


class Sprint3:
    def __init__(self, pet):
        self.m = s3.PetHealthMonitor(pet_id=pet.id, breed=pet.raca, age_years=pet.idade)

    def alimentar(self, lin) -> bool:
        self.m.add_reading(lin["temperatura"], lin["atividade"],
                           datetime.fromisoformat(lin["timestamp"]))
        return self.m.evaluate() is not None


class Sprint4:
    def __init__(self, pet):
        self.m = s4.PetHealthMonitor(pet_id=pet.id, breed=pet.raca, age_years=pet.idade,
                                     species=pet.especie, pet_name=pet.nome)

    def alimentar(self, lin) -> bool:
        v = s4.validar_leitura(lin["temperatura"], lin["atividade"], lin["bpm"])
        if not v.valida:
            return False
        self.m.add_reading(lin["temperatura"], lin["atividade"],
                           datetime.fromisoformat(lin["timestamp"]), v.heart_rate)
        return self.m.evaluate() is not None


DETECTORES = {"fixo": LimiarFixo, "s3": Sprint3, "s4": Sprint4}


# --------------------------------------------------------------------------
def gerar_dataset(seed: int):
    return {pid: serie_rotulada(pid, DIAS, seed, INICIO) for pid in PETS}


def salvar_csv(dataset, caminho: Path):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    campos = ["pet_id", "timestamp", "temperatura", "atividade", "bpm", "episodio", "id_episodio"]
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for linhas in dataset.values():
            for lin in linhas:
                w.writerow({k: lin[k] for k in campos})


def executar(dataset, chave):
    """Roda um detector sobre todos os pets e devolve as predicoes por leitura."""
    preds = {}
    for pid, linhas in dataset.items():
        det = DETECTORES[chave](PETS[pid])
        preds[pid] = [det.alimentar(lin) for lin in linhas]
    return preds


def metricas(dataset, preds, ignorar_horas_iniciais=24 * 7):
    ep_info = defaultdict(lambda: {"inicio": None, "detectado_em": None, "tipo": ""})
    vp = fp = fn = 0
    falsos_alarmes, horas_normais = 0, 0
    for pid, linhas in dataset.items():
        ultimo_fa, fim_ultimo_ep = -10 ** 9, -10 ** 9
        for i, (lin, alerta) in enumerate(zip(linhas, preds[pid])):
            ep = lin["id_episodio"]
            if ep:
                fim_ultimo_ep = i
            if i < ignorar_horas_iniciais:
                continue          # primeira semana: baseline em formacao para todos
            if not ep and i - fim_ultimo_ep <= TOLERANCIA_POS_EPISODIO_H:
                continue          # pet se recuperando: janela de tolerancia (igual p/ todos)
            if ep:
                info = ep_info[ep]
                info["tipo"] = lin["episodio"]
                if info["inicio"] is None:
                    info["inicio"] = i
                if alerta and info["detectado_em"] is None:
                    info["detectado_em"] = i
                vp += alerta
                fn += not alerta
            else:
                horas_normais += 1
                if alerta:
                    fp += 1
                    if i - ultimo_fa > COOLDOWN_H:
                        falsos_alarmes += 1
                    ultimo_fa = i
    eps = list(ep_info.values())
    detectados = [e for e in eps if e["detectado_em"] is not None]
    latencias = [e["detectado_em"] - e["inicio"] for e in detectados]
    por_tipo = defaultdict(lambda: [0, 0])
    for e in eps:
        por_tipo[e["tipo"]][1] += 1
        por_tipo[e["tipo"]][0] += e["detectado_em"] is not None
    precisao = vp / (vp + fp) if vp + fp else 0.0
    recall_l = vp / (vp + fn) if vp + fn else 0.0
    return {
        "episodios": len(eps),
        "recall_episodios": len(detectados) / len(eps) if eps else 0.0,
        "latencia_mediana_h": statistics.median(latencias) if latencias else None,
        "falsos_alarmes_pet_semana": falsos_alarmes / (horas_normais / (24 * 7)),
        "precisao": precisao,
        "recall_leituras": recall_l,
        "f1": 2 * precisao * recall_l / (precisao + recall_l) if precisao + recall_l else 0.0,
        "por_tipo": dict(por_tipo),
    }


# --------------------------------------------------------------------------
# Graficos
# --------------------------------------------------------------------------
def _eixos(ax):
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def grafico_comparativo(res, caminho):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    chaves = ["fixo", "s3", "s4"]
    paineis = [
        ("Episódios detectados (%)", [res[k]["recall_episodios"] * 100 for k in chaves], "{:.0f}%"),
        ("Falsos alarmes por pet por semana", [res[k]["falsos_alarmes_pet_semana"] for k in chaves], "{:.2f}"),
    ]
    for ax, (titulo, valores, fmt) in zip(axes, paineis):
        ax.set_facecolor("#fcfcfb")
        barras = ax.bar([NOME[k] for k in chaves], valores, color=[COR[k] for k in chaves],
                        width=0.55, edgecolor="#fcfcfb", linewidth=2)
        for b, v in zip(barras, valores):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), fmt.format(v),
                    ha="center", va="bottom", fontsize=10, color=INK, fontweight="bold")
        ax.set_title(titulo, loc="left", fontsize=11, color=INK, pad=10)
        _eixos(ax)
        ax.tick_params(axis="x", colors=INK2)
    axes[0].set_ylim(0, 110)
    fig.tight_layout()
    fig.savefig(caminho, facecolor=fig.get_facecolor())
    plt.close(fig)


def grafico_limiar(varredura, escolhido, caminho):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    zs = [v["z"] for v in varredura]
    paineis = [("Episódios detectados (%)", [v["recall"] * 100 for v in varredura], "{:.0f}%", (0, 112)),
               ("Falsos alarmes por pet por semana", [v["fa"] for v in varredura], "{:.2f}", None)]
    for ax, (titulo, ys, fmt, lim) in zip(axes, paineis):
        ax.set_facecolor("#fcfcfb")
        ax.plot(zs, ys, color=COR["s4"], linewidth=2, marker="o", markersize=7,
                markeredgecolor="#fcfcfb", markeredgewidth=2)
        for z, y in zip(zs, ys):
            if z == escolhido:
                ax.annotate(fmt.format(y), (z, y), textcoords="offset points", xytext=(0, 9),
                            ha="center", fontsize=9.5, color=INK, fontweight="bold")
        ax.axvline(escolhido, color=MUTED, linestyle=(0, (3, 3)), linewidth=1)
        ax.set_xticks(zs)
        ax.set_xticklabels([f"{z:.1f}" + ("\nescolhido" if z == escolhido else "") for z in zs])
        ax.set_xlabel("limiar de z-score", color=INK2, fontsize=9)
        ax.set_title(titulo, loc="left", fontsize=11, color=INK, pad=10)
        if lim:
            ax.set_ylim(*lim)
        else:
            ax.set_ylim(0, max(ys) * 1.25)
        _eixos(ax)
    fig.suptitle("Escolha do limiar (conjunto de validação)", x=0.01, ha="left", fontsize=12, color=INK, y=1.0)
    fig.tight_layout()
    fig.savefig(caminho, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def grafico_episodio(caminho):
    """Linha do tempo do Rex: 2 dias normais + episodio de febre, com o alerta."""
    from simulador.modelo_fisiologico import historico_normal, episodio
    fim_hist = datetime(2026, 10, 20, 9, tzinfo=FUSO_BR)
    linhas = historico_normal("rex", 8, fim_hist, seed=3) + episodio("rex", "febre_leve", fim_hist, seed=3)
    fim2 = fim_hist + timedelta(hours=8)
    linhas += historico_normal("rex", 1, fim2 + timedelta(hours=24), seed=4)[:14]
    pet = PETS["rex"]
    mon = s4.PetHealthMonitor("rex", pet.raca, pet.idade, pet.especie, pet.nome)
    pontos = []
    for lin in linhas:
        ts = datetime.fromisoformat(lin["timestamp"])
        mon.add_reading(lin["temperatura"], lin["atividade"], ts, lin["bpm"])
        al = mon.evaluate()
        pontos.append((ts, lin["temperatura"], al.severity if al else None))
    pontos = pontos[-72:]
    base = mon.baseline()
    fixo_hi = s4.FAIXAS_REFERENCIA["cao"]["temperatura"][1]

    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    xs = [p[0] for p in pontos]
    med, sig = base["temperatura"]["mediana"], base["temperatura"]["sigma"]
    ax.axhspan(med - s4.Z_LIMIAR * sig, med + s4.Z_LIMIAR * sig, color="#cde2fb", alpha=0.7, lw=0)
    ax.axhline(fixo_hi, color=COR["fixo"], linestyle=(0, (4, 3)), linewidth=1.2)
    ax.plot(xs, [p[1] for p in pontos], color=COR["s4"], linewidth=2)
    cores_sev = {"baixa": "#fab219", "media": "#ec835a", "critica": "#d03b3b"}
    primeiro = next((p for p in pontos if p[2]), None)
    for p in pontos:
        if p[2]:
            ax.plot(p[0], p[1], "o", color=cores_sev[p[2]], markersize=8, markeredgecolor="#fcfcfb", markeredgewidth=2)
    ax.text(xs[2], med + s4.Z_LIMIAR * sig + 0.03, "faixa normal do Rex (baseline individual)", fontsize=8.5, color=INK2)
    ax.text(xs[2], fixo_hi + 0.04, f"limiar fixo {fixo_hi} °C", fontsize=8.5, color=INK2)
    if primeiro:
        rel = "abaixo" if primeiro[1] < fixo_hi else "acima"
        ax.annotate(f"1º alerta PetLink: {primeiro[1]:.1f} °C ({rel} do limiar fixo)",
                    (primeiro[0], primeiro[1]), xytext=(-250, -4), textcoords="offset points",
                    fontsize=9, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=1))
    ax.set_title("Rex (Labrador): febre discreta simulada — temperatura (°C)", loc="left", fontsize=11, color=INK, pad=10)
    ax.set_ylim(37.4, max(fixo_hi, max(p[1] for p in pontos)) + 0.25)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m %Hh", tz=FUSO_BR))
    _eixos(ax)
    fig.tight_layout()
    fig.savefig(caminho, facecolor=fig.get_facecolor())
    plt.close(fig)


# --------------------------------------------------------------------------
def main():
    t0 = time.time()
    docs, img, dados = RAIZ / "docs", RAIZ / "docs" / "img", RAIZ / "dados"
    img.mkdir(parents=True, exist_ok=True)

    validacao, teste = gerar_dataset(seed=1), gerar_dataset(seed=2)
    salvar_csv(validacao, dados / "dataset_validacao.csv")
    salvar_csv(teste, dados / "dataset_teste.csv")

    # 1) Varredura do limiar no conjunto de VALIDACAO
    original = s4.Z_LIMIAR
    varredura = []
    for z in (2.0, 2.5, 3.0, 3.5, 4.0):
        s4.Z_LIMIAR = z
        m = metricas(validacao, executar(validacao, "s4"))
        varredura.append({"z": z, "recall": m["recall_episodios"], "fa": m["falsos_alarmes_pet_semana"],
                          "lat": m["latencia_mediana_h"]})
        print(f"  validacao z={z}: recall={m['recall_episodios']:.2f}  falsos/pet/sem={m['falsos_alarmes_pet_semana']:.2f}")
    s4.Z_LIMIAR = original

    # 2) Resultado final no conjunto de TESTE
    preds = {k: executar(teste, k) for k in DETECTORES}
    res = {k: metricas(teste, preds[k]) for k in DETECTORES}
    por_pet = {pid: {k: metricas({pid: teste[pid]}, {pid: preds[k][pid]}) for k in DETECTORES} for pid in teste}
    for k, m in res.items():
        print(f"  teste {NOME[k]:16s} recall_ep={m['recall_episodios']:.2f} lat={m['latencia_mediana_h']} "
              f"fa/pet/sem={m['falsos_alarmes_pet_semana']:.2f} F1={m['f1']:.2f}")

    grafico_comparativo(res, img / "comparativo_metodos.png")
    grafico_limiar(varredura, original, img / "escolha_limiar.png")
    grafico_episodio(img / "exemplo_febre_rex.png")

    # 3) Relatorio
    tipos = sorted({t for m in res.values() for t in m["por_tipo"]})
    L = []
    L.append("# Resultados da avaliação do modelo de IA\n")
    L.append(f"> Gerado automaticamente por `python -m avaliacao.avaliar_modelo` em "
             f"{datetime.now(FUSO_BR):%d/%m/%Y %H:%M}. Dados **sintéticos** (ver `simulador/modelo_fisiologico.py`).\n")
    L.append("## Protocolo\n")
    L.append(f"- 3 pets (Rex, Luna, Bolinha) × {DIAS} dias × 1 leitura/hora = "
             f"{sum(len(v) for v in teste.values())} leituras por conjunto.")
    L.append("- Episódios clínicos injetados aleatoriamente a cada 4–8 dias: "
             + ", ".join(f"`{c}`" for c in tipos) + ".")
    L.append("- **Validação (seed 1)** → escolha do limiar de z-score. **Teste (seed 2)** → números abaixo (nunca usado para ajuste).")
    L.append("- Primeira semana descartada para todos os métodos (baseline em formação).")
    L.append(f"- As {TOLERANCIA_POS_EPISODIO_H} h logo após cada episódio são uma janela de tolerância (recuperação do pet): "
             "não contam como acerto nem como falso alarme, para nenhum método.\n")
    L.append("## Resultado no conjunto de teste\n")
    L.append("| Métrica | Limiar fixo | Modelo Sprint 3 | **Modelo Sprint 4** |")
    L.append("|---|---|---|---|")
    def linha(rot, f):
        L.append(f"| {rot} | " + " | ".join(f(res[k]) if k != "s4" else f"**{f(res[k])}**" for k in DETECTORES) + " |")
    linha("Episódios detectados", lambda m: f"{m['recall_episodios']*100:.0f}% de {m['episodios']}")
    linha("Latência mediana até o 1º alerta", lambda m: "—" if m["latencia_mediana_h"] is None else f"{m['latencia_mediana_h']:.0f} h")
    linha("Falsos alarmes / pet / semana", lambda m: f"{m['falsos_alarmes_pet_semana']:.2f}")
    linha("Precisão (por leitura)", lambda m: f"{m['precisao']*100:.0f}%")
    linha("Recall (por leitura)", lambda m: f"{m['recall_leituras']*100:.0f}%")
    linha("F1 (por leitura)", lambda m: f"{m['f1']:.2f}")
    L.append("\n![Comparativo](img/comparativo_metodos.png)\n")
    L.append("### Detecção por tipo de episódio\n")
    L.append("| Episódio | Limiar fixo | Sprint 3 | **Sprint 4** |")
    L.append("|---|---|---|---|")
    for t in tipos:
        cel = []
        for k in DETECTORES:
            d, n = res[k]["por_tipo"].get(t, [0, 0])
            cel.append(f"**{d}/{n}**" if k == "s4" else f"{d}/{n}")
        L.append(f"| `{t}` — {CENARIOS[t]['descricao']} | " + " | ".join(cel) + " |")
    L.append("\n### Por pet (o efeito da individualização)\n")
    L.append("| Pet | Normal individual | Falsos alarmes/semana — limiar fixo | Sprint 3 | **Sprint 4** | Episódios detectados — limiar fixo | Sprint 3 | **Sprint 4** |")
    L.append("|---|---|---|---|---|---|---|---|")
    for pid, mm in por_pet.items():
        p = PETS[pid]
        fa = [f"{mm[k]['falsos_alarmes_pet_semana']:.2f}" for k in DETECTORES]
        ep = [f"{sum(v[0] for v in mm[k]['por_tipo'].values())}/{mm[k]['episodios']}" for k in DETECTORES]
        L.append(f"| {p.nome} ({p.raca}) | {p.temp_media:.2f} °C | {fa[0]} | {fa[1]} | **{fa[2]}** | {ep[0]} | {ep[1]} | **{ep[2]}** |")
    L.append("\n> O recall **por leitura** é naturalmente menor que o por episódio: no `declinio_gradual` (72 h) "
             "as primeiras horas são quase indistinguíveis do normal, e o objetivo é alertar *durante* o episódio, "
             "não em todas as horas dele.\n")
    L.append("## Escolha do limiar (validação)\n")
    L.append("| z | Episódios detectados | Falsos alarmes / pet / semana | Latência mediana |")
    L.append("|---|---|---|---|")
    for v in varredura:
        marca = " ← escolhido" if v["z"] == original else ""
        lat = "—" if v["lat"] is None else f"{v['lat']:.0f} h"
        L.append(f"| {v['z']:.1f}{marca} | {v['recall']*100:.0f}% | {v['fa']:.2f} | {lat} |")
    L.append("\n![Escolha do limiar](img/escolha_limiar.png)\n")
    L.append("## Exemplo: por que baseline individual?\n")
    L.append("O Rex tem temperatura normal mais baixa que a média da espécie. Uma febre de ~39 °C nele está "
             "**abaixo** do limiar fixo de 39,2 °C — a regra clássica não dispara, o PetLink sim. Já a Bolinha "
             "tem o normal perto de 39 °C, e o limiar fixo dispara alarmes falsos com frequência.\n")
    L.append("![Episódio do Rex](img/exemplo_febre_rex.png)\n")
    L.append("## Limitações\n")
    L.append("- Dados sintéticos: os parâmetros fisiológicos são plausíveis, mas não substituem validação com dados clínicos reais.")
    L.append("- A temperatura da coleira é de superfície; em produção ela precisa ser calibrada contra a temperatura retal.")
    L.append("- O modelo sinaliza desvios; **não faz diagnóstico** — a decisão clínica é sempre do veterinário.")
    (docs / "RESULTADOS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"OK em {time.time()-t0:.0f}s -> docs/RESULTADOS.md, docs/img/, dados/")


if __name__ == "__main__":
    main()
