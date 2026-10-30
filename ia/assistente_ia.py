"""
PetLink - Camada de IA Generativa (Sprint 4)

O modelo preditivo (anomaly_detector.py) decide SE ha anomalia. Esta camada
transforma a decisao em linguagem personalizada:

  1. explicar_alerta()  -> texto para o TUTOR (simples, acolhedor, acionavel)
                           + resumo para a CLINICA (tecnico, com z-scores)
  2. resumo_diario()    -> boletim das ultimas 24h personalizado por raca/idade
  3. responder()        -> assistente conversacional que responde perguntas do
                           tutor com base nos dados reais do pet (grounding)

Provedor: Claude (Anthropic) via SDK oficial. Sem ANTHROPIC_API_KEY, ou se a
chamada falhar, cai automaticamente no modo OFFLINE (geracao por templates),
para que a aplicacao nunca fique sem resposta.

Guardrails (nos dois modos):
  - nunca diagnostica nem prescreve medicamento/dose;
  - responde apenas com base nos dados fornecidos;
  - palavras de emergencia (convulsao, envenenamento...) disparam orientacao
    fixa de atendimento imediato, ANTES de qualquer resposta gerada.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import List, Optional

log = logging.getLogger("petlink.ia")

SYSTEM_BASE = """Voce e o assistente de saude do PetLink, coleira inteligente da clinica CLYVO VET.
Fale em portugues do Brasil, de forma acolhedora, clara e objetiva.

Regras obrigatorias:
- Baseie-se SOMENTE nos dados do pet fornecidos no contexto. Se um dado nao estiver la, diga que nao tem essa informacao.
- NUNCA de diagnostico fechado e NUNCA indique medicamento, dose ou tratamento caseiro.
- Diferencie claramente "o que os sensores mostram" de "o que pode significar".
- Quando houver alerta de severidade "critica", oriente procurar o veterinario hoje.
- Sempre que fizer sentido, sugira acompanhar pelo app ou falar com a CLYVO VET.
- Assuntos que nao sejam sobre o pet ou cuidados com ele: recuse com gentileza e volte ao tema.
"""

PALAVRAS_EMERGENCIA = [
    "convuls", "envenen", "veneno", "sangr", "nao respira", "dificuldade para respirar", "falta de ar",
    "desmai", "atropel", "engoliu", "chocolate", "nao acorda", "inconsciente", "vomitando sangue",
]

ORIENTACAO_EMERGENCIA = ("⚠️ Isso pode ser uma emergência. Leve o pet imediatamente a um pronto-atendimento "
                         "veterinário ou ligue para a CLYVO VET agora. Não dê medicamentos por conta própria.")


SEVERIDADE_ROTULO = {"baixa": "leve", "media": "moderada", "critica": "crítica"}
ESPECIE_ROTULO = {"cao": "cão", "gato": "gato"}


def recomendacao_tutor(severidade: str, nome: str) -> str:
    return {"critica": f"Procure o veterinário com {nome} ainda hoje.",
            "media": f"Observe {nome} nas próximas horas e agende uma consulta se os sinais continuarem.",
            "baixa": "Não é preciso fazer nada agora: o PetLink segue acompanhando."}[severidade]


def _normalizar(txt: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def detectar_emergencia(texto: str) -> bool:
    t = _normalizar(texto)
    return any(p in t for p in PALAVRAS_EMERGENCIA)


class AssistenteIA:
    def __init__(self, api_key: str = "", modelo: str = "claude-haiku-5-5", timeout: float = 20.0):
        self.modelo = modelo
        self._cliente = None
        if api_key:
            try:
                import anthropic
                self._cliente = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)
            except Exception as e:  # SDK ausente ou erro de configuracao
                log.warning("IA generativa indisponivel (%s) - usando modo offline", e)

    @property
    def modo(self) -> str:
        return "llm" if self._cliente else "offline"

    # ------------------------------------------------------------------
    def _gerar(self, system: str, mensagens: List[dict], max_tokens: int = 500) -> Optional[str]:
        if not self._cliente:
            return None
        try:
            resp = self._cliente.messages.create(model=self.modelo, max_tokens=max_tokens,
                                                 system=system, messages=mensagens)
            texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            return texto or None
        except Exception as e:
            log.warning("Falha na chamada ao LLM (%s) - usando modo offline", e)
            return None

    # ------------------------------------------------------------------
    # 1) Explicacao do alerta (tutor + clinica)
    # ------------------------------------------------------------------
    def explicar_alerta(self, pet: dict, alerta: dict, contexto: dict) -> dict:
        prompt = (
            "Um alerta foi gerado pelo modelo preditivo do PetLink. Escreva DOIS textos e responda "
            "APENAS com um JSON valido no formato {\"tutor\": \"...\", \"clinica\": \"...\"}.\n"
            "- tutor: ate 70 palavras, linguagem simples, sem jargao nem z-score, explicando o que mudou "
            "em relacao ao normal DESTE pet e o que fazer agora (use a recomendacao do alerta).\n"
            "- clinica: ate 60 palavras, tom tecnico para o veterinario, com valores, referencia individual, "
            "z-scores e possiveis diferenciais a investigar (sem fechar diagnostico).\n\n"
            f"PET: {json.dumps(pet, ensure_ascii=False)}\n"
            f"ALERTA: {json.dumps(alerta, ensure_ascii=False)}\n"
            f"CONTEXTO 24H: {json.dumps(contexto, ensure_ascii=False)}"
        )
        bruto = self._gerar(SYSTEM_BASE, [{"role": "user", "content": prompt}], max_tokens=600)
        if bruto:
            m = re.search(r"\{.*\}", bruto, re.S)
            try:
                dados = json.loads(m.group(0)) if m else None
                if dados and dados.get("tutor") and dados.get("clinica"):
                    return {"tutor": dados["tutor"].strip(), "clinica": dados["clinica"].strip(), "fonte": "llm"}
            except json.JSONDecodeError:
                pass
        return {**self._explicar_offline(pet, alerta), "fonte": "offline"}

    @staticmethod
    def _explicar_offline(pet: dict, alerta: dict) -> dict:
        nome = pet["nome"]
        frases = {
            "febre": f"a temperatura de {nome} está acima do que é normal para {nome}",
            "febre_alta": f"a temperatura de {nome} passou do limite de segurança",
            "temperatura_baixa": f"a temperatura de {nome} está abaixo do habitual",
            "hipotermia": f"a temperatura de {nome} está muito baixa",
            "letargia": f"{nome} está se movimentando bem menos do que costuma neste horário",
            "taquicardia": f"o coração de {nome} está mais acelerado do que o esperado para o nível de atividade",
            "bradicardia": f"o coração de {nome} está mais lento do que o esperado",
            "tendencia_queda_atividade": f"{nome} vem se movimentando menos nas últimas 24 horas",
            "tendencia_elevacao_temperatura": f"a temperatura de {nome} vem subindo aos poucos no último dia",
            "temperatura_fora_da_faixa": f"a temperatura de {nome} está fora da faixa de referência da espécie",
            "bpm_fora_da_faixa": f"os batimentos de {nome} estão fora da faixa de referência da espécie",
        }
        tipos = [d["tipo"] for d in alerta.get("detalhes", [])]
        partes = [frases.get(t, "um sinal fora do padrão foi detectado") for t in tipos] or ["algo fora do padrão foi detectado"]
        o_que = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
        tutor = f"Notamos que {o_que}. {recomendacao_tutor(alerta['severidade'], nome)}"
        if alerta["severidade"] == "critica":
            tutor += " A equipe da CLYVO VET já pode ver esses dados."
        clinica = (f"{pet['nome']} ({ESPECIE_ROTULO.get(pet['especie'], pet['especie'])}, {pet['raca']}, "
                   f"{pet['idade']:g} anos). Severidade {SEVERIDADE_ROTULO[alerta['severidade']]}, "
                   f"risco {alerta['risco']}/100. Sinais: " + "; ".join(alerta.get("sinais", [])) + ".")
        return {"tutor": tutor, "clinica": clinica}

    # ------------------------------------------------------------------
    # 2) Resumo diario personalizado
    # ------------------------------------------------------------------
    def resumo_diario(self, pet: dict, contexto: dict) -> dict:
        prompt = (
            "Escreva o boletim diario de saude deste pet para o tutor (ate 90 palavras, 2 paragrafos curtos): "
            "1) como foram as ultimas 24h comparadas ao normal DELE; 2) uma dica de cuidado especifica para "
            "a especie, raca e idade. Sem listas, sem titulo.\n\n"
            f"PET: {json.dumps(pet, ensure_ascii=False)}\nCONTEXTO: {json.dumps(contexto, ensure_ascii=False)}"
        )
        texto = self._gerar(SYSTEM_BASE, [{"role": "user", "content": prompt}], max_tokens=400)
        if texto:
            return {"texto": texto, "fonte": "llm"}
        return {"texto": self._resumo_offline(pet, contexto), "fonte": "offline"}

    @staticmethod
    def _dica(pet: dict) -> str:
        especie, raca, idade = pet["especie"], _normalizar(pet["raca"]), pet["idade"]
        if especie == "gato":
            return ("Gatos costumam esconder desconforto; vale observar se a ingestão de água e o uso da caixa "
                    "de areia seguem normais.")
        if idade >= 8:
            return (f"Aos {idade:g} anos, passeios mais curtos e frequentes poupam as articulações; "
                    "check-ups semestrais são recomendados para cães idosos.")
        if "labrador" in raca or "golden" in raca:
            return "Labradores tendem a ganhar peso com facilidade: mantenha a rotina de exercícios e controle os petiscos."
        return "Mantenha a rotina de passeios e hidratação, principalmente nos dias mais quentes."

    def _resumo_offline(self, pet: dict, ctx: dict) -> str:
        nome = pet["nome"]
        if not ctx.get("leituras_24h"):
            return f"Ainda não há leituras suficientes de {nome} nas últimas 24 horas."
        alertas = ctx.get("alertas_24h", [])
        t = ctx.get("temperatura_24h", {})
        razao = ctx.get("atividade_vs_habitual")
        if alertas:
            pior = max(alertas, key=lambda a: {"baixa": 1, "media": 2, "critica": 3}[a["severidade"]])
            qtd = "1 alerta" if len(alertas) == 1 else f"{len(alertas)} alertas"
            p1 = (f"Nas últimas 24h, {nome} teve {qtd}, o mais importante de severidade "
                  f"{SEVERIDADE_ROTULO[pior['severidade']]}. {recomendacao_tutor(pior['severidade'], nome)}")
        else:
            p1 = f"Dia tranquilo para {nome}: os sinais ficaram dentro do normal de {nome}."
        detalhes = []
        if t:
            detalhes.append(f"temperatura entre {t['min']:.1f} e {t['max']:.1f} °C".replace(".", ","))
        if razao is not None:
            detalhes.append(f"atividade em {razao*100:.0f}% do habitual")
        if detalhes:
            p1 += " (" + ", ".join(detalhes) + ")."
        return p1 + "\n\n" + self._dica(pet)

    # ------------------------------------------------------------------
    # 3) Assistente conversacional
    # ------------------------------------------------------------------
    def responder(self, pet: dict, contexto: dict, historico: List[dict], pergunta: str) -> dict:
        emergencia = detectar_emergencia(pergunta)
        system = (SYSTEM_BASE + "\nResponda em ate 110 palavras.\n\nDADOS ATUAIS DO PET (fonte de verdade):\n"
                  + json.dumps({"pet": pet, **contexto}, ensure_ascii=False))
        msgs = []
        for m in historico[-10:]:
            papel = "user" if m["papel"] == "tutor" else "assistant"
            if msgs and msgs[-1]["role"] == papel:
                msgs[-1]["content"] += "\n" + m["texto"]
            else:
                msgs.append({"role": papel, "content": m["texto"]})
        if msgs and msgs[0]["role"] == "assistant":
            msgs.pop(0)
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1]["content"] += "\n" + pergunta
        else:
            msgs.append({"role": "user", "content": pergunta})

        texto = self._gerar(system, msgs, max_tokens=400)
        fonte = "llm" if texto else "offline"
        if not texto:
            texto = self._responder_offline(pet, contexto, pergunta)
        if emergencia and ORIENTACAO_EMERGENCIA not in texto:
            texto = ORIENTACAO_EMERGENCIA + "\n\n" + texto
        return {"texto": texto, "fonte": fonte, "emergencia": emergencia}

    def _responder_offline(self, pet: dict, ctx: dict, pergunta: str) -> str:
        q = _normalizar(pergunta)
        nome = pet["nome"]
        ultima = ctx.get("ultima_leitura") or {}
        base = ctx.get("baseline") or {}
        if detectar_emergencia(pergunta):
            return "Enquanto isso, mantenha o pet em local calmo e arejado e leve os dados do app ao atendimento."
        # Seguranca antes de qualquer outra intencao: pergunta sobre remedio nunca vira resposta sobre febre
        if any(p in q for p in ("remedio", "medicament", "dose", "dipirona", "paracetamol", "tratar")):
            return ("Não posso indicar medicamentos ou doses — alguns remédios humanos são tóxicos para pets. "
                    "Fale com a CLYVO VET, que já tem acesso aos dados da coleira.")
        if any(p in q for p in ("febre", "temperatura", "quente", "calor")):
            if not ultima:
                return f"Ainda não recebi leituras de temperatura de {nome}."
            ref = base.get("temperatura", {}).get("mediana")
            comp = f" O normal de {nome} fica em torno de {ref:.1f} °C." if ref else ""
            return f"A última temperatura de {nome} foi {ultima['temperatura']:.1f} °C.{comp} " + self._status_txt(ctx)
        if any(p in q for p in ("ativ", "brinc", "cansad", "parad", "dormi", "quieto", "preguic")):
            razao = ctx.get("atividade_vs_habitual")
            if razao is None:
                return f"Ainda não tenho dados suficientes de atividade de {nome}."
            return (f"Nas últimas 24h, {nome} ficou com {razao*100:.0f}% da atividade habitual para cada horário. "
                    + ("Está dentro do esperado." if razao >= 0.75 else f"Está abaixo do normal de {nome}; vale observar se está comendo e bebendo água."))
        if any(p in q for p in ("coracao", "batimento", "bpm", "cardiac")):
            if not ultima.get("bpm"):
                return f"Não tenho leitura recente de batimentos de {nome}."
            return f"A última frequência cardíaca de {nome} foi {ultima['bpm']:.0f} bpm. " + self._status_txt(ctx)
        if any(p in q for p in ("alerta", "aviso", "notifica", "por que", "porque")):
            alertas = ctx.get("alertas_24h", [])
            if not alertas:
                return f"{nome} não teve alertas nas últimas 24 horas."
            a = alertas[0]
            explicacao = a.get("explicacao") or "; ".join(a["sinais"]) + "."
            return f"O alerta mais recente foi de severidade {SEVERIDADE_ROTULO[a['severidade']]}. {explicacao}"
        if any(p in q for p in ("como esta", "tudo bem", "saude", "resumo", "hoje")):
            return self._resumo_offline(pet, ctx)
        return (f"Posso ajudar com informações sobre {nome}: temperatura, atividade, batimentos, alertas ou o resumo "
                f"do dia. Para dúvidas clínicas, fale com a CLYVO VET. (Assistente em modo offline.)")

    @staticmethod
    def _status_txt(ctx: dict) -> str:
        s = ctx.get("status")
        return {"normal": "No momento os sinais estão dentro do normal.",
                "baixa": "Há um alerta leve em observação.",
                "media": "Há um alerta moderado: observe o pet nas próximas horas.",
                "critica": "Há um alerta crítico: procure o veterinário hoje."}.get(s, "")
