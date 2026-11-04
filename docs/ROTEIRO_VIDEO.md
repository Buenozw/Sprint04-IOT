# Roteiro do vídeo pitch (~5 min)

Critério: **20 pontos para clareza e didática**. O vídeo precisa mostrar a ideia central, a IA funcionando de verdade (demonstração) e os benefícios para tutor e clínica. A divisão de falas abaixo é uma sugestão — troquem como preferirem.

## Antes de gravar

- [ ] `pip install -r requirements.txt` e `python -m uvicorn api.main:app` rodando
- [ ] Se tiverem uma chave da Anthropic, coloquem no `.env` (o cabeçalho deve mostrar "IA generativa: conectada"); sem chave, o modo offline também serve
- [ ] No painel, "Simular um cenário clínico" → **Restaurar dados iniciais**
- [ ] Navegador em tela cheia, zoom 110%, abas abertas: painel (`localhost:8000`) e Swagger (`localhost:8000/docs`)
- [ ] Deixar `docs/img/comparativo_metodos.png` e `docs/img/exemplo_febre_rex.png` abertos para o trecho de resultados
- [ ] Opcional: app no celular com a tela Saúde (IA) apontando para a API

## Cenas

| Tempo | Quem | Na tela | Fala (resumo) |
|---|---|---|---|
| 0:00–0:30 | Felipe | Painel do Rex "está bem" | O tutor só percebe que o pet está doente quando os sintomas já aparecem. O PetLink é uma coleira que acompanha temperatura, atividade e batimentos o tempo todo — e nesta sprint ganhou a inteligência que transforma esses números em cuidado. |
| 0:30–1:20 | Raul | Diagrama do README, depois Swagger | Mostrar o caminho de uma leitura: coleira → MQTT/HiveMQ → ponte → API → banco → modelo → IA generativa → app e clínica. No Swagger, abrir `POST /api/leituras` e mostrar que é o mesmo ponto de entrada para ESP32, app e simulador. |
| 1:20–2:20 | João Caetano | Gráfico de temperatura do Rex (faixa verde) e `exemplo_febre_rex.png` | A IA não usa "febre acima de 39,2 °C". Ela aprende o normal **de cada pet**: o Rex vive em 38,1 °C, a Bolinha perto de 39 °C. Compara a atividade com o mesmo horário dos outros dias (dormir de madrugada não é problema), ajusta os batimentos pela atividade e confirma desvios fracos em duas leituras antes de avisar. Pioras lentas são vistas pela tendência das últimas 24 h. |
| 2:20–3:40 | Ryan | Demo ao vivo no painel | Abrir o simulador, escolher **Febre com prostração** (1 leitura por segundo). Enquanto a curva sai da faixa verde: o status muda para "precisa ir ao veterinário hoje", o alerta aparece com a explicação em linguagem simples, e "Ver o que a clínica vê" mostra os z-scores. No chat: "Por que recebi esse alerta?" e depois "Posso dar dipirona?" — mostrar que o assistente se recusa a indicar remédio. Se houver tempo: "Ele teve uma convulsão" → orientação de emergência. |
| 3:40–4:20 | João Castelini | Aba **Clínica** (e, se der, o app no celular) | Para a CLYVO VET: fila ordenada pelo risco calculado pela IA, com resumo técnico pronto. A clínica pode ligar para o tutor do Rex antes que ele chegue em estado grave. Para o tutor: alertas que dizem o que mudou e o que fazer, boletim do dia personalizado por raça e idade. |
| 4:20–5:00 | João Caetano | `comparativo_metodos.png` | Avaliamos em 90 dias simulados de 3 pets: o modelo detectou 94% dos episódios contra 75% do limiar fixo, com 0,03 falso alarme por pet por semana contra quase 5. Limitações: dados sintéticos e temperatura de superfície — o próximo passo é calibrar com dados reais da CLYVO VET. Fechar com o nome do grupo e o link do repositório. |

## Dicas

- Falem dos **benefícios** em cada cena, não só da tecnologia (o enunciado pede benefícios para tutor e clínica).
- No modo "1 leitura por segundo", a febre completa leva 10 segundos — dá para narrar enquanto acontece.
- Se algo travar na gravação, "Restaurar dados iniciais" volta tudo ao começo.
- Publicar no YouTube como **não listado** e colar o link no `README.md` e no `ENTREGA.txt`.
