// Tela "Saúde (IA)" para o app PetLink (Expo / React Native).
//
// Como integrar no app existente:
//   1. Copie mobile/services/petlinkApi.js e esta tela para o projeto.
//   2. Registre no navegador de abas:
//        <Tab.Screen name="SaudeIA" component={SaudeIAScreen} initialParams={{ petId: "rex" }}
//          options={{ title: "Saúde (IA)", tabBarIcon: ({ color, size }) =>
//            <MaterialIcons name="monitor-heart" color={color} size={size} /> }} />
//   3. Ajuste API_URL em petlinkApi.js (ou EXPO_PUBLIC_PETLINK_API no .env do Expo).
// As cores ficam no objeto C abaixo; se o app usa ThemeContext, troque C pelas cores do tema.

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, RefreshControl,
  ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { MaterialIcons } from "@expo/vector-icons";
import { petlinkApi } from "../services/petlinkApi";

const C = {
  fundo: "#F2F5F3", cartao: "#FFFFFF", texto: "#17322B", secundario: "#4E6660", suave: "#7E918B",
  linha: "#DCE4E0", destaque: "#1F7A63", ok: "#2E8B57", baixa: "#C98E00", media: "#D9662F", critica: "#C33636",
};

const STATUS = {
  normal: { cor: C.ok, icone: "check-circle", titulo: (n) => `${n} está bem`, sub: "Sinais dentro do normal individual." },
  baixa: { cor: C.baixa, icone: "visibility", titulo: (n) => `${n} tem um sinal em observação`, sub: "Nada urgente: seguimos acompanhando." },
  media: { cor: C.media, icone: "warning", titulo: (n) => `${n} precisa de atenção`, sub: "Observe nas próximas horas." },
  critica: { cor: C.critica, icone: "local-hospital", titulo: (n) => `${n} precisa ir ao veterinário hoje`, sub: "A CLYVO VET já vê os mesmos dados." },
  coleira_fora_do_pet: { cor: C.suave, icone: "link-off", titulo: () => "Coleira fora do pet", sub: "Recoloque a coleira para continuar o monitoramento." },
  erro_sensor: { cor: C.suave, icone: "sensors-off", titulo: () => "Leitura inválida do sensor", sub: "A leitura foi descartada." },
  sem_dados: { cor: C.suave, icone: "hourglass-empty", titulo: (n) => `Aguardando dados de ${n}`, sub: "Ligue a coleira para começar." },
};
const SEV = { baixa: ["Leve", C.baixa], media: ["Moderado", C.media], critica: ["Crítico", C.critica] };
const num = (v, c = 1) => (v == null ? "—" : Number(v).toFixed(c).replace(".", ","));
const hora = (iso) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

function CartaoAlerta({ alerta, onLido }) {
  const [aberto, setAberto] = useState(false);
  const [rotulo, cor] = SEV[alerta.severidade];
  return (
    <View style={[s.cartao, { borderLeftWidth: 4, borderLeftColor: cor, opacity: alerta.lido ? 0.7 : 1 }]}>
      <View style={s.linhaEntre}>
        <Text style={[s.negrito, { color: cor }]}>{rotulo}</Text>
        <Text style={s.mini}>{hora(alerta.ts)}{alerta.ocorrencias > 1 ? ` · ${alerta.ocorrencias}×` : ""}</Text>
      </View>
      <Text style={s.corpo}>{alerta.explicacao_tutor}</Text>
      <View style={[s.linhaEntre, { marginTop: 8 }]}>
        <Pressable onPress={() => setAberto(!aberto)} hitSlop={8}>
          <Text style={[s.link]}>{aberto ? "Ocultar dados técnicos" : "Ver o que a clínica vê"}</Text>
        </Pressable>
        {!alerta.lido && (
          <Pressable onPress={() => onLido(alerta.id)} hitSlop={8}><Text style={s.mini}>Marcar como lido</Text></Pressable>
        )}
      </View>
      {aberto && <Text style={[s.mini, { marginTop: 8, lineHeight: 18 }]}>{alerta.resumo_clinico}</Text>}
    </View>
  );
}

export default function SaudeIAScreen({ route }) {
  const petId = route?.params?.petId ?? "rex";
  const [pet, setPet] = useState(null);
  const [alertas, setAlertas] = useState([]);
  const [resumo, setResumo] = useState(null);
  const [chat, setChat] = useState([]);
  const [pergunta, setPergunta] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState(null);
  const [atualizando, setAtualizando] = useState(false);
  const rolagem = useRef(null);

  const carregar = useCallback(async () => {
    try {
      const [d, a] = await Promise.all([petlinkApi.detalhePet(petId), petlinkApi.alertas(petId)]);
      setPet(d); setAlertas(a); setErro(null);
    } catch (e) {
      setErro("Não foi possível falar com o servidor do PetLink. Confira o endereço da API e a rede Wi-Fi.");
    }
  }, [petId]);

  const carregarResumo = useCallback(async () => {
    try { setResumo(await petlinkApi.resumo(petId)); } catch { /* boletim é opcional */ }
  }, [petId]);

  useEffect(() => {
    carregar(); carregarResumo();
    petlinkApi.historicoChat(petId).then(setChat).catch(() => {});
    const t = setInterval(carregar, 5000); // atualização contínua (tempo real)
    return () => clearInterval(t);
  }, [carregar, carregarResumo, petId]);

  const ultimoAlertaId = alertas[0]?.id;
  useEffect(() => { if (ultimoAlertaId) carregarResumo(); }, [ultimoAlertaId, carregarResumo]);

  const enviar = async (texto) => {
    const q = (texto ?? pergunta).trim();
    if (!q || enviando) return;
    setPergunta(""); setEnviando(true);
    setChat((c) => [...c, { id: `t${Date.now()}`, papel: "tutor", texto: q }]);
    try {
      const r = await petlinkApi.perguntar(petId, q);
      setChat((c) => [...c, { id: `a${Date.now()}`, papel: "assistente", texto: r.texto }]);
    } catch {
      setChat((c) => [...c, { id: `e${Date.now()}`, papel: "assistente", texto: "Sem conexão com o PetLink agora. Tente de novo em instantes." }]);
    } finally {
      setEnviando(false);
      setTimeout(() => rolagem.current?.scrollToEnd({ animated: true }), 100);
    }
  };

  const atualizar = async () => { setAtualizando(true); await Promise.all([carregar(), carregarResumo()]); setAtualizando(false); };

  if (!pet) {
    return (
      <View style={[s.tela, s.centro]}>
        {erro ? <Text style={[s.corpo, { textAlign: "center", padding: 24 }]}>{erro}</Text> : <ActivityIndicator color={C.destaque} />}
      </View>
    );
  }

  const st = STATUS[pet.status] ?? STATUS.sem_dados;
  const u = pet.ultima_leitura;

  return (
    <KeyboardAvoidingView style={s.tela} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView ref={rolagem} contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
                  refreshControl={<RefreshControl refreshing={atualizando} onRefresh={atualizar} />}>
        <View style={[s.cartao, { borderColor: st.cor }]}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
            <MaterialIcons name={st.icone} size={28} color={st.cor} />
            <Text style={s.titulo}>{st.titulo(pet.nome)}</Text>
          </View>
          <Text style={[s.mini, { marginTop: 4 }]}>{st.sub}</Text>
          {u && (
            <View style={[s.linhaEntre, { marginTop: 14 }]}>
              <View><Text style={s.mini}>Temperatura</Text><Text style={s.valor}>{num(u.temperatura)} °C</Text></View>
              <View><Text style={s.mini}>Atividade</Text><Text style={s.valor}>{num(u.atividade, 0)}</Text></View>
              <View><Text style={s.mini}>Batimentos</Text><Text style={s.valor}>{u.bpm ? `${num(u.bpm, 0)}` : "—"}</Text></View>
            </View>
          )}
          {pet.baseline && (
            <Text style={[s.mini, { marginTop: 10 }]}>
              Normal de {pet.nome}: {num(pet.baseline.temperatura.mediana)} °C (aprendido com {pet.baseline.leituras_usadas} leituras)
            </Text>
          )}
        </View>

        <Text style={s.secao}>Alertas da IA</Text>
        {alertas.length === 0
          ? <Text style={s.mini}>Nenhum alerta. Quando algo sair do normal de {pet.nome}, a explicação aparece aqui.</Text>
          : alertas.slice(0, 5).map((a) => (
              <CartaoAlerta key={a.id} alerta={a} onLido={async (id) => { await petlinkApi.marcarLido(id); carregar(); }} />
            ))}

        <Text style={s.secao}>Boletim do dia</Text>
        <View style={s.cartao}>
          <Text style={s.corpo}>{resumo ? resumo.texto : "Gerando boletim…"}</Text>
        </View>

        <Text style={s.secao}>Pergunte sobre {pet.nome}</Text>
        <View style={s.cartao}>
          {chat.length === 0 && <Text style={s.mini}>As respostas usam os dados reais da coleira. Não substitui o veterinário.</Text>}
          {chat.map((m) => (
            <View key={m.id} style={[s.bolha, m.papel === "tutor" ? s.bolhaTutor : s.bolhaIA]}>
              <Text style={{ color: m.papel === "tutor" ? "#fff" : C.texto, lineHeight: 20 }}>{m.texto}</Text>
            </View>
          ))}
          {enviando && <Text style={s.mini}>Analisando os dados de {pet.nome}…</Text>}
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
            {[`Como ${pet.nome} está hoje?`, "Por que recebi esse alerta?", "Posso dar algum remédio?"].map((q) => (
              <Pressable key={q} onPress={() => enviar(q)} style={s.chip}><Text style={{ color: C.texto, fontSize: 13 }}>{q}</Text></Pressable>
            ))}
          </View>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <TextInput value={pergunta} onChangeText={setPergunta} placeholder="Escreva sua pergunta" placeholderTextColor={C.suave}
                       style={s.entrada} onSubmitEditing={() => enviar()} returnKeyType="send" maxLength={600} />
            <Pressable onPress={() => enviar()} disabled={enviando || !pergunta.trim()}
                       style={[s.botao, (enviando || !pergunta.trim()) && { opacity: 0.5 }]}
                       accessibilityLabel="Enviar pergunta">
              <MaterialIcons name="send" size={20} color="#fff" />
            </Pressable>
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  tela: { flex: 1, backgroundColor: C.fundo },
  centro: { alignItems: "center", justifyContent: "center" },
  cartao: { backgroundColor: C.cartao, borderRadius: 14, borderWidth: 1, borderColor: C.linha, padding: 14, marginBottom: 10 },
  linhaEntre: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  titulo: { fontSize: 20, fontWeight: "700", color: C.texto, flexShrink: 1 },
  secao: { fontSize: 17, fontWeight: "700", color: C.texto, marginTop: 18, marginBottom: 8 },
  valor: { fontSize: 22, fontWeight: "700", color: C.texto },
  corpo: { fontSize: 15, color: C.texto, lineHeight: 22, marginTop: 4 },
  negrito: { fontWeight: "700", fontSize: 15 },
  mini: { fontSize: 12.5, color: C.secundario },
  link: { color: C.destaque, fontWeight: "700", fontSize: 13 },
  bolha: { borderRadius: 14, paddingHorizontal: 12, paddingVertical: 8, marginTop: 8, maxWidth: "88%" },
  bolhaTutor: { backgroundColor: C.texto, alignSelf: "flex-end" },
  bolhaIA: { backgroundColor: C.fundo, alignSelf: "flex-start" },
  chip: { borderWidth: 1, borderColor: C.linha, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  entrada: { flex: 1, borderWidth: 1, borderColor: C.linha, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8, color: C.texto, backgroundColor: C.fundo },
  botao: { backgroundColor: C.destaque, borderRadius: 10, paddingHorizontal: 14, justifyContent: "center" },
});
