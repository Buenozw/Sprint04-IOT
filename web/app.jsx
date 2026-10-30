/* PetLink — painel do tutor e da clínica (React + Tailwind, sem build).
   Consome a PetLink API (mesma origem). Para apontar para outra API: ?api=http://host:8000 */

const { useState, useEffect, useRef, useCallback, useMemo } = React;
const API = new URLSearchParams(location.search).get("api") || "";
const INTERVALO_MS = 3000;

async function api(caminho, opcoes = {}) {
  const r = await fetch(API + caminho, {
    headers: { "Content-Type": "application/json" }, ...opcoes,
    body: opcoes.body ? JSON.stringify(opcoes.body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status} em ${caminho}`);
  return r.json();
}

/* ---------------- utilidades ---------------- */
const fmtHora = (iso) => { const d = new Date(iso); return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };
const fmtNum = (v, c = 1) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: c, maximumFractionDigits: c }));
const horaBR = (iso) => { const d = new Date(iso); return (d.getUTCHours() + 21) % 24; }; // America/Sao_Paulo (UTC-3)
const especie = (p) => (p.especie === "gato" ? "felino" : "canino");

const STATUS = {
  normal: { cor: "var(--color-ok)", rotulo: "Normal", frase: (n) => `${n} está bem.`, sub: (n) => `Os sinais estão dentro do normal de ${n}.` },
  baixa: { cor: "var(--color-baixa)", rotulo: "Em observação", frase: (n) => `${n} tem um sinal em observação.`, sub: () => "Nada urgente: o PetLink segue acompanhando." },
  media: { cor: "var(--color-media)", rotulo: "Atenção", frase: (n) => `${n} precisa de atenção nas próximas horas.`, sub: () => "Observe o pet e agende consulta se os sinais continuarem." },
  critica: { cor: "var(--color-critica)", rotulo: "Crítico", frase: (n) => `${n} precisa ir ao veterinário hoje.`, sub: () => "A CLYVO VET já está vendo os mesmos dados." },
  coleira_fora_do_pet: { cor: "var(--color-nevoa)", rotulo: "Coleira fora", frase: (n) => `A coleira de ${n} parece estar fora do pet.`, sub: () => "A temperatura medida está próxima da ambiente. Recoloque a coleira." },
  erro_sensor: { cor: "var(--color-nevoa)", rotulo: "Erro de sensor", frase: () => "Recebemos uma leitura impossível do sensor.", sub: () => "Ela foi descartada e não entrou na análise." },
  sem_dados: { cor: "var(--color-nevoa)", rotulo: "Sem dados", frase: (n) => `Ainda não recebemos dados de ${n}.`, sub: () => "Ligue a coleira para começar o monitoramento." },
};
const SEV = { baixa: "Leve", media: "Moderado", critica: "Crítico" };

function Selo({ status, pequeno }) {
  const s = STATUS[status] || STATUS.sem_dados;
  return (
    <span className={`inline-flex items-center gap-1.5 ${pequeno ? "text-xs" : "text-sm"} font-bold`} style={{ color: s.cor }}>
      <span className={`inline-block rounded-full ${pequeno ? "w-2 h-2" : "w-2.5 h-2.5"} ${status === "critica" ? "pulso" : ""}`} style={{ background: s.cor }} />
      {s.rotulo}
    </span>
  );
}

function useLargura() {
  const ref = useRef(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/* ---------------- gráfico de temperatura com a faixa individual ---------------- */
function GraficoTemperatura({ leituras, baseline, alertas, nome }) {
  const [ref, W] = useLargura();
  const [foco, setFoco] = useState(null);
  const H = 220, m = { t: 16, r: 16, b: 28, l: 44 };
  const validas = leituras.filter((l) => l.valida);
  if (!validas.length) return <div ref={ref} className="h-[220px] grid place-items-center text-nevoa">Sem leituras ainda.</div>;

  const t0 = new Date(validas[0].ts).getTime(), t1 = new Date(validas[validas.length - 1].ts).getTime() || t0 + 1;
  const faixa = baseline ? [baseline.temperatura.mediana - baseline.z_limiar * baseline.temperatura.sigma,
                            baseline.temperatura.mediana + baseline.z_limiar * baseline.temperatura.sigma] : null;
  const temps = validas.map((l) => l.temperatura).concat(faixa || []);
  const yMin = Math.floor((Math.min(...temps) - 0.2) * 2) / 2, yMax = Math.ceil((Math.max(...temps) + 0.2) * 2) / 2;
  const x = (ts) => m.l + ((new Date(ts).getTime() - t0) / Math.max(1, t1 - t0)) * (W - m.l - m.r);
  const y = (v) => m.t + (1 - (v - yMin) / (yMax - yMin)) * (H - m.t - m.b);
  const caminho = validas.map((l, i) => `${i ? "L" : "M"}${x(l.ts).toFixed(1)},${y(l.temperatura).toFixed(1)}`).join("");
  const ticksY = []; for (let v = yMin; v <= yMax + 1e-6; v += 0.5) ticksY.push(v);
  const ticksX = validas.filter((l) => horaBR(l.ts) % 12 === 0);
  const tsAlerta = new Set(alertas.map((a) => a.ts));
  const corSev = { baixa: "var(--color-baixa)", media: "var(--color-media)", critica: "var(--color-critica)" };

  const mover = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    let melhor = null, dist = 1e9;
    validas.forEach((l) => { const d = Math.abs(x(l.ts) - px); if (d < dist) { dist = d; melhor = l; } });
    setFoco(melhor);
  };

  return (
    <div ref={ref} className="relative">
      <svg width={W} height={H} onMouseMove={mover} onMouseLeave={() => setFoco(null)} role="img"
           aria-label={`Temperatura de ${nome} nas últimas horas, com a faixa normal individual`}>
        {faixa && <rect x={m.l} width={W - m.l - m.r} y={y(faixa[1])} height={y(faixa[0]) - y(faixa[1])} fill="var(--color-faixa)" rx="4" />}
        {ticksY.map((v) => (
          <g key={v}>
            <line x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} stroke="var(--color-linha)" strokeWidth="1" />
            <text x={m.l - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--color-nevoa)">{fmtNum(v)}</text>
          </g>
        ))}
        {ticksX.map((l) => (
          <text key={l.ts} x={x(l.ts)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--color-nevoa)">
            {horaBR(l.ts) === 0 ? fmtHora(l.ts).slice(0, 5) : `${horaBR(l.ts)}h`}
          </text>
        ))}
        {faixa && <text x={m.l + 8} y={y(faixa[1]) + 14} fontSize="11.5" fill="var(--color-musgo)">faixa normal de {nome}</text>}
        <path d={caminho} fill="none" stroke="var(--color-traco)" strokeWidth="2" strokeLinejoin="round" />
        {validas.filter((l) => tsAlerta.has(l.ts)).map((l) => {
          const a = alertas.find((q) => q.ts === l.ts);
          return <circle key={l.ts} cx={x(l.ts)} cy={y(l.temperatura)} r="5.5" fill={corSev[a.severidade]} stroke="#fff" strokeWidth="2" />;
        })}
        {foco && (
          <g>
            <line x1={x(foco.ts)} x2={x(foco.ts)} y1={m.t} y2={H - m.b} stroke="var(--color-musgo)" strokeDasharray="3 3" />
            <circle cx={x(foco.ts)} cy={y(foco.temperatura)} r="4.5" fill="var(--color-traco)" stroke="#fff" strokeWidth="2" />
          </g>
        )}
      </svg>
      {foco && (
        <div className="absolute pointer-events-none bg-pinho text-white text-xs rounded-lg px-2.5 py-1.5 shadow-lg"
             style={{ left: Math.min(x(foco.ts) + 10, W - 150), top: 8 }}>
          <div className="font-bold">{fmtHora(foco.ts)}</div>
          <div>{fmtNum(foco.temperatura)} °C · atividade {fmtNum(foco.atividade, 0)}{foco.bpm ? ` · ${fmtNum(foco.bpm, 0)} bpm` : ""}</div>
        </div>
      )}
    </div>
  );
}

/* ---------------- atividade observada x habitual para o horário ---------------- */
function GraficoAtividade({ leituras, baseline, nome }) {
  const [ref, W] = useLargura();
  const [foco, setFoco] = useState(null);
  const H = 130, m = { t: 10, r: 16, b: 22, l: 44 };
  const validas = leituras.filter((l) => l.valida).slice(-48);
  if (!validas.length) return <div ref={ref} />;
  const perfil = baseline ? baseline.perfil_atividade_horario : null;
  const esperado = (l) => (perfil ? perfil[horaBR(l.ts)].mediana : null);
  const n = validas.length, passo = (W - m.l - m.r) / n, larg = Math.max(2, passo - 2);
  const y = (v) => m.t + (1 - v / 100) * (H - m.t - m.b);
  const linhaEsperada = perfil ? validas.map((l, i) => `${i ? "L" : "M"}${(m.l + i * passo + passo / 2).toFixed(1)},${y(esperado(l)).toFixed(1)}`).join("") : "";
  return (
    <div ref={ref} className="relative">
      <svg width={W} height={H} onMouseLeave={() => setFoco(null)} role="img" aria-label={`Atividade de ${nome} comparada ao habitual`}>
        {[0, 50, 100].map((v) => (
          <g key={v}>
            <line x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} stroke="var(--color-linha)" />
            <text x={m.l - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--color-nevoa)">{v}</text>
          </g>
        ))}
        {validas.map((l, i) => {
          const abaixo = perfil && l.atividade < esperado(l) * 0.5;
          return (
            <g key={l.id} onMouseEnter={() => setFoco({ l, i })}>
              <rect x={m.l + i * passo} y={m.t} width={passo} height={H - m.t - m.b} fill="transparent" />
              <rect x={m.l + i * passo + 1} y={y(l.atividade)} width={larg} height={Math.max(1, y(0) - y(l.atividade))}
                    rx="2" fill={abaixo ? "var(--color-media)" : "var(--color-atividade)"} opacity={foco && foco.i !== i ? 0.55 : 1} />
            </g>
          );
        })}
        {perfil && <path d={linhaEsperada} fill="none" stroke="var(--color-pinho)" strokeWidth="1.6" strokeDasharray="4 3" />}
      </svg>
      {foco && (
        <div className="absolute pointer-events-none bg-pinho text-white text-xs rounded-lg px-2.5 py-1.5 shadow-lg"
             style={{ left: Math.min(m.l + foco.i * passo + 12, W - 170), top: 0 }}>
          <div className="font-bold">{fmtHora(foco.l.ts)}</div>
          <div>atividade {fmtNum(foco.l.atividade, 0)}{perfil ? ` · habitual ${fmtNum(esperado(foco.l), 0)}` : ""}</div>
        </div>
      )}
    </div>
  );
}

/* ---------------- alertas ---------------- */
function CartaoAlerta({ a, onLido }) {
  const [aberto, setAberto] = useState(false);
  const cor = { baixa: "var(--color-baixa)", media: "var(--color-media)", critica: "var(--color-critica)" }[a.severidade];
  return (
    <article className={`bg-cartao rounded-xl border border-linha pl-4 pr-4 py-3 ${a.lido ? "opacity-70" : ""}`} style={{ borderLeft: `4px solid ${cor}` }}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-bold" style={{ color: cor }}>{SEV[a.severidade]}</span>
        <time className="text-xs text-nevoa">{fmtHora(a.ts)}{a.ocorrencias > 1 ? ` · repetiu ${a.ocorrencias}×` : ""}</time>
      </div>
      <p className="mt-1.5 leading-relaxed">{a.explicacao_tutor}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <button className="text-traco font-bold hover:underline" onClick={() => setAberto(!aberto)} aria-expanded={aberto}>
          {aberto ? "Ocultar dados técnicos" : "Ver o que a clínica vê"}
        </button>
        {!a.lido && <button className="text-musgo hover:underline" onClick={() => onLido(a.id)}>Marcar como lido</button>}
        <span className="text-nevoa ml-auto">{a.fonte_ia === "llm" ? "texto gerado por IA" : "texto gerado offline"}</span>
      </div>
      {aberto && (
        <div className="mt-3 rounded-lg bg-papel p-3 text-sm">
          <p className="text-musgo">{a.resumo_clinico}</p>
          <ul className="mt-2 space-y-1">
            {a.detalhes.map((d, i) => (
              <li key={i} className="flex justify-between gap-3 border-t border-linha pt-1">
                <span>{d.tipo.replaceAll("_", " ")}</span>
                <span className="tabular-nums text-musgo">{d.z_score !== null ? `z = ${fmtNum(d.z_score, 1)}` : "regra clínica"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

/* ---------------- boletim + chat (IA generativa) ---------------- */
function Boletim({ pet, versao }) {
  const [r, setR] = useState(null);
  const [carregando, setCarregando] = useState(false);
  const carregar = useCallback(async () => {
    setCarregando(true);
    try { setR(await api(`/api/pets/${pet.id}/resumo`)); } finally { setCarregando(false); }
  }, [pet.id]);
  useEffect(() => { carregar(); }, [carregar, versao]);
  return (
    <section className="bg-cartao rounded-2xl border border-linha p-5">
      <div className="flex items-baseline justify-between">
        <h3 className="font-display text-xl font-bold">Boletim do dia</h3>
        <button onClick={carregar} className="text-sm text-traco font-bold hover:underline" disabled={carregando}>
          {carregando ? "Gerando…" : "Atualizar"}
        </button>
      </div>
      <div className="mt-3 space-y-3 leading-relaxed text-[15px] max-w-prose">
        {r ? r.texto.split("\n").filter(Boolean).map((p, i) => <p key={i}>{p}</p>) : <p className="text-nevoa">Gerando boletim…</p>}
      </div>
    </section>
  );
}

function Chat({ pet }) {
  const [msgs, setMsgs] = useState([]);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const fim = useRef(null);
  useEffect(() => { api(`/api/pets/${pet.id}/chat`).then(setMsgs).catch(() => setMsgs([])); }, [pet.id]);
  useEffect(() => { fim.current?.scrollIntoView({ block: "nearest" }); }, [msgs]);
  const enviar = async (q) => {
    const pergunta = (q ?? texto).trim();
    if (!pergunta || enviando) return;
    setTexto(""); setEnviando(true);
    setMsgs((m) => [...m, { papel: "tutor", texto: pergunta, id: "t" + Date.now() }]);
    try {
      const r = await api(`/api/pets/${pet.id}/chat`, { method: "POST", body: { mensagem: pergunta } });
      setMsgs((m) => [...m, { papel: "assistente", texto: r.texto, fonte: r.fonte, id: "a" + Date.now() }]);
    } catch {
      setMsgs((m) => [...m, { papel: "assistente", texto: "Não consegui falar com o servidor do PetLink. Verifique se a API está rodando.", id: "e" + Date.now() }]);
    } finally { setEnviando(false); }
  };
  const sugestoes = [`Como ${pet.nome} está hoje?`, "Por que recebi esse alerta?", "A temperatura está normal?", "Posso dar algum remédio?"];
  return (
    <section className="bg-cartao rounded-2xl border border-linha p-5 flex flex-col">
      <h3 className="font-display text-xl font-bold">Pergunte sobre {pet.nome}</h3>
      <p className="text-sm text-musgo mt-1">As respostas usam os dados reais da coleira. O assistente não substitui o veterinário.</p>
      <div className="mt-4 flex-1 max-h-80 min-h-40 overflow-y-auto space-y-3 pr-1">
        {msgs.length === 0 && <p className="text-nevoa text-sm">Escolha uma pergunta abaixo ou escreva a sua.</p>}
        {msgs.map((m) => (
          <div key={m.id} className={`flex ${m.papel === "tutor" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 whitespace-pre-line leading-relaxed text-[15px] ${m.papel === "tutor" ? "bg-pinho text-white rounded-br-md" : "bg-papel rounded-bl-md"}`}>
              {m.texto}
            </div>
          </div>
        ))}
        {enviando && <div className="text-sm text-nevoa">Analisando os dados de {pet.nome}…</div>}
        <div ref={fim} />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {sugestoes.map((s) => (
          <button key={s} onClick={() => enviar(s)} className="text-sm rounded-full border border-linha px-3 py-1 hover:bg-papel">{s}</button>
        ))}
      </div>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); enviar(); }}>
        <label htmlFor="pergunta" className="sr-only">Sua pergunta</label>
        <input id="pergunta" value={texto} onChange={(e) => setTexto(e.target.value)} maxLength={600}
               placeholder={`Ex.: ${pet.nome} está dormindo mais que o normal?`}
               className="flex-1 min-w-0 rounded-xl border border-linha bg-papel px-3 py-2 focus:outline-none focus:border-traco" />
        <button className="rounded-xl bg-traco text-white font-bold px-4 py-2 disabled:opacity-50" disabled={enviando || !texto.trim()}>Enviar</button>
      </form>
    </section>
  );
}

/* ---------------- painel de demonstração ---------------- */
const CENARIOS = [
  ["febre", "Febre com prostração"], ["febre_leve", "Febre discreta"], ["letargia", "Prostração sem febre"],
  ["taquicardia", "Coração acelerado em repouso"], ["declinio_gradual", "Piora lenta (72 h)"],
  ["hipotermia", "Hipotermia"], ["coleira_fora", "Coleira fora do pet"], ["normal", "Voltar ao normal"],
];
function PainelDemo({ pet, rodando, aoMudar }) {
  const [aberto, setAberto] = useState(false);
  const [rapido, setRapido] = useState(true);
  const iniciar = async (c) => {
    await api("/api/demo/cenario", { method: "POST", body: { pet_id: pet.id, cenario: c, ao_vivo: true, intervalo_s: rapido ? 1 : 3 } });
    aoMudar();
  };
  const reset = async () => { if (confirm("Apagar alertas e conversas e recriar 7 dias de histórico normal?")) { await api("/api/demo/reset", { method: "POST" }); aoMudar(); } };
  return (
    <section className="mt-8 border-t border-linha pt-4">
      <button onClick={() => setAberto(!aberto)} className="text-sm font-bold text-musgo hover:text-pinho" aria-expanded={aberto}>
        {aberto ? "Fechar simulador" : "Simular um cenário clínico"} {rodando && <span className="text-traco pulso">(simulação em andamento)</span>}
      </button>
      {aberto && (
        <div className="mt-3">
          <p className="text-sm text-musgo max-w-prose">Cada leitura simulada representa 1 hora de coleira e passa pelo mesmo caminho de uma leitura real: validação, banco, modelo preditivo e IA generativa.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {CENARIOS.map(([id, nome]) => (
              <button key={id} onClick={() => iniciar(id)} className="rounded-lg border border-linha bg-cartao px-3 py-1.5 text-sm hover:border-traco">{nome}</button>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-musgo">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={rapido} onChange={(e) => setRapido(e.target.checked)} /> 1 leitura por segundo</label>
            <button onClick={reset} className="text-critica hover:underline">Restaurar dados iniciais</button>
          </div>
        </div>
      )}
    </section>
  );
}

/* ---------------- visão do tutor ---------------- */
function VisaoTutor({ pet, saude, aoMudar }) {
  const [det, setDet] = useState(null);
  const [leituras, setLeituras] = useState([]);
  const [alertas, setAlertas] = useState([]);
  const [rodando, setRodando] = useState(false);
  const carregar = useCallback(async () => {
    const [d, l, a, e] = await Promise.all([
      api(`/api/pets/${pet.id}`), api(`/api/pets/${pet.id}/leituras?horas=48`),
      api(`/api/pets/${pet.id}/alertas?limite=20`), api("/api/demo/estado"),
    ]);
    setDet(d); setLeituras(l); setAlertas(a); setRodando(!!e[pet.id]);
  }, [pet.id]);
  useEffect(() => { setDet(null); carregar(); const t = setInterval(carregar, INTERVALO_MS); return () => clearInterval(t); }, [carregar]);
  const lido = async (id) => { await api(`/api/alertas/${id}/lido`, { method: "PATCH" }); carregar(); };
  if (!det) return <p className="py-16 text-nevoa">Carregando {pet.nome}…</p>;

  const st = STATUS[det.status] || STATUS.sem_dados;
  const u = det.ultima_leitura;
  const versaoBoletim = alertas.length ? alertas[0].id + ":" + alertas[0].ocorrencias : 0;
  const leiturasJanela = leituras.slice(-72);
  const alertasJanela = alertas.filter((a) => leiturasJanela.length && a.ts >= leiturasJanela[0].ts);

  return (
    <div>
      <section className="pt-6 pb-2 grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <Selo status={det.status} />
          <h2 className="font-display text-4xl sm:text-5xl font-bold leading-[1.05] mt-2 max-w-[22ch]">{st.frase(pet.nome)}</h2>
          <p className="mt-2 text-musgo text-lg">{st.sub(pet.nome)}</p>
        </div>
        {u && (
          <dl className="grid grid-cols-3 gap-6 text-right">
            <div><dt className="text-sm text-musgo">Temperatura</dt><dd className="font-display text-3xl font-bold tabular-nums">{fmtNum(u.temperatura)}<span className="text-lg"> °C</span></dd></div>
            <div><dt className="text-sm text-musgo">Atividade</dt><dd className="font-display text-3xl font-bold tabular-nums">{fmtNum(u.atividade, 0)}</dd></div>
            <div><dt className="text-sm text-musgo">Batimentos</dt><dd className="font-display text-3xl font-bold tabular-nums">{u.bpm ? fmtNum(u.bpm, 0) : "—"}<span className="text-lg"> bpm</span></dd></div>
            <div className="col-span-3 text-xs text-nevoa -mt-4">última leitura {fmtHora(u.ts)}</div>
          </dl>
        )}
      </section>

      <section className="mt-4 bg-cartao rounded-2xl border border-linha p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-display text-xl font-bold">Temperatura nas últimas 72 h</h3>
          <p className="text-sm text-musgo">{det.baseline ? `Normal de ${pet.nome}: ${fmtNum(det.baseline.temperatura.mediana)} °C, aprendido com ${det.baseline.leituras_usadas} leituras` : "A faixa normal aparece depois das primeiras 24 leituras"}</p>
        </div>
        <div className="mt-3"><GraficoTemperatura leituras={leiturasJanela} baseline={det.baseline} alertas={alertasJanela} nome={pet.nome} /></div>
        <div className="mt-5 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-display text-lg font-bold">Atividade x habitual para cada horário</h3>
          <p className="text-sm text-musgo"><span className="inline-block w-5 border-t-2 border-dashed border-pinho align-middle mr-1.5" />habitual · <span className="inline-block w-2.5 h-2.5 rounded-sm bg-media align-middle mr-1" />menos da metade do habitual</p>
        </div>
        <div className="mt-2"><GraficoAtividade leituras={leiturasJanela} baseline={det.baseline} nome={pet.nome} /></div>
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section>
          <h3 className="font-display text-xl font-bold">Alertas da IA</h3>
          <div className="mt-3 space-y-3">
            {alertas.length === 0 && <p className="text-musgo bg-cartao rounded-xl border border-linha p-4">Nenhum alerta. Quando algo sair do normal de {pet.nome}, a explicação aparece aqui.</p>}
            {alertas.slice(0, 6).map((a) => <CartaoAlerta key={a.id} a={a} onLido={lido} />)}
          </div>
        </section>
        <div className="space-y-6">
          <Boletim pet={pet} versao={versaoBoletim} />
          <Chat pet={pet} />
        </div>
      </div>

      <PainelDemo pet={pet} rodando={rodando} aoMudar={() => { carregar(); aoMudar(); }} />
    </div>
  );
}

/* ---------------- visão da clínica ---------------- */
function VisaoClinica({ abrirPet }) {
  const [fila, setFila] = useState(null);
  useEffect(() => {
    const c = () => api("/api/clinica/triagem").then(setFila).catch(() => {});
    c(); const t = setInterval(c, INTERVALO_MS); return () => clearInterval(t);
  }, []);
  if (!fila) return <p className="py-16 text-nevoa">Carregando fila…</p>;
  const emAlerta = fila.filter((f) => f.risco > 0).length;
  return (
    <div className="pt-6">
      <h2 className="font-display text-4xl sm:text-5xl font-bold leading-tight">
        {emAlerta ? `${emAlerta} ${emAlerta > 1 ? "pacientes pedem" : "paciente pede"} atenção agora.` : "Nenhum paciente em alerta."}
      </h2>
      <p className="mt-2 text-musgo text-lg max-w-prose">Fila ordenada pelo risco calculado pelo modelo preditivo. O resumo clínico é gerado pela IA a partir dos desvios em relação ao normal de cada pet.</p>
      <ol className="mt-6 space-y-3">
        {fila.map((f) => {
          const u = f.ultima_leitura;
          const cor = (STATUS[f.status] || STATUS.sem_dados).cor;
          return (
            <li key={f.pet.id} className="bg-cartao rounded-2xl border border-linha p-5 grid gap-4 md:grid-cols-[200px_1fr_140px] md:items-start">
              <div>
                <button onClick={() => abrirPet(f.pet.id)} className="font-display text-2xl font-bold hover:underline text-left">{f.pet.nome}</button>
                <p className="text-sm text-musgo">{f.pet.raca} · {f.pet.idade} anos · {especie(f.pet)}</p>
                <p className="text-sm text-musgo">Tutor(a): {f.pet.tutor}</p>
              </div>
              <div className="text-[15px] leading-relaxed">
                {f.alerta ? (
                  <>
                    <p>{f.alerta.resumo_clinico}</p>
                    <p className="mt-1 text-xs text-nevoa">alerta de {fmtHora(f.alerta.ts)}{f.alerta.ocorrencias > 1 ? `, repetiu ${f.alerta.ocorrencias}×` : ""}</p>
                  </>
                ) : (
                  <p className="text-musgo">Sem desvios nas últimas horas{u ? ` · ${fmtNum(u.temperatura)} °C, atividade ${fmtNum(u.atividade, 0)}, ${u.bpm ? fmtNum(u.bpm, 0) + " bpm" : "sem bpm"}` : ""}.</p>
                )}
              </div>
              <div className="md:text-right">
                <Selo status={f.status} />
                <div className="mt-2 h-2 rounded-full bg-papel overflow-hidden" aria-label={`Risco ${f.risco} de 100`}>
                  <div className="h-full rounded-full" style={{ width: `${f.risco}%`, background: cor }} />
                </div>
                <p className="mt-1 text-xs text-nevoa tabular-nums">risco {f.risco}/100</p>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* ---------------- app ---------------- */
function App() {
  const [visao, setVisao] = useState("tutor");
  const [pets, setPets] = useState([]);
  const [petId, setPetId] = useState(null);
  const [saude, setSaude] = useState(null);
  const [erro, setErro] = useState(null);
  const carregar = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([api("/api/pets"), api("/api/saude")]);
      setPets(p); setSaude(s); setErro(null);
      setPetId((atual) => atual || (p[0] && (p.find((x) => x.id === "rex") || p[0]).id));
    } catch (e) { setErro("A API do PetLink não respondeu. Rode: uvicorn api.main:app --reload"); }
  }, []);
  useEffect(() => { carregar(); const t = setInterval(carregar, INTERVALO_MS); return () => clearInterval(t); }, [carregar]);
  const pet = pets.find((p) => p.id === petId);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-16">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3 py-4 border-b border-linha">
        <div className="flex items-center gap-2.5">
          <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="14" fill="var(--color-pinho)" /><path d="M6 17h6l2-5 4 10 2-5h6" stroke="var(--color-faixa)" strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          <span className="font-display text-xl font-bold">PetLink</span>
          <span className="text-sm text-musgo">para CLYVO VET</span>
        </div>
        <nav className="flex rounded-xl bg-cartao border border-linha p-1 text-sm" aria-label="Visão">
          {[["tutor", "Tutor"], ["clinica", "Clínica"]].map(([id, nome]) => (
            <button key={id} onClick={() => setVisao(id)} aria-pressed={visao === id}
                    className={`px-3.5 py-1.5 rounded-lg font-bold ${visao === id ? "bg-pinho text-white" : "text-musgo hover:text-pinho"}`}>{nome}</button>
          ))}
        </nav>
        {saude && (
          <span className="ml-auto text-sm text-musgo" title={saude.ia_generativa === "llm" ? `Modelo: ${saude.modelo_llm}` : "Sem ANTHROPIC_API_KEY: textos gerados por templates"}>
            IA generativa: <b className={saude.ia_generativa === "llm" ? "text-traco" : "text-baixa"}>{saude.ia_generativa === "llm" ? "conectada" : "modo offline"}</b>
          </span>
        )}
      </header>

      {erro && <p className="mt-6 rounded-xl border border-critica/40 bg-cartao p-4 text-critica font-bold">{erro}</p>}

      {visao === "tutor" && pets.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Pets">
          {pets.map((p) => (
            <button key={p.id} role="tab" aria-selected={p.id === petId} onClick={() => setPetId(p.id)}
                    className={`rounded-full border px-4 py-1.5 text-sm flex items-center gap-2 ${p.id === petId ? "border-pinho bg-cartao font-bold" : "border-linha text-musgo hover:border-musgo"}`}>
              <span className={`w-2 h-2 rounded-full ${p.status === "critica" ? "pulso" : ""}`} style={{ background: (STATUS[p.status] || STATUS.sem_dados).cor }} />
              {p.nome} <span className="text-nevoa font-normal">{p.raca}</span>
            </button>
          ))}
        </div>
      )}

      {visao === "tutor" && pet && <VisaoTutor key={pet.id} pet={pet} saude={saude} aoMudar={carregar} />}
      {visao === "clinica" && <VisaoClinica abrirPet={(id) => { setPetId(id); setVisao("tutor"); }} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("raiz")).render(<App />);
