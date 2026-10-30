// Cliente da PetLink API para o app React Native (Expo).
// No celular, "localhost" é o próprio celular: use o IP do computador que roda a API,
// ex.: http://192.168.0.15:8000 (mesma rede Wi-Fi). No emulador Android: http://10.0.2.2:8000
export const API_URL = process.env.EXPO_PUBLIC_PETLINK_API || "http://192.168.0.15:8000";

async function requisicao(caminho, { method = "GET", body } = {}) {
  const resp = await fetch(`${API_URL}${caminho}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`PetLink API respondeu ${resp.status} em ${caminho}`);
  return resp.json();
}

export const petlinkApi = {
  saude: () => requisicao("/api/saude"),
  listarPets: () => requisicao("/api/pets"),
  detalhePet: (petId) => requisicao(`/api/pets/${petId}`),
  leituras: (petId, horas = 24) => requisicao(`/api/pets/${petId}/leituras?horas=${horas}`),
  alertas: (petId, limite = 10) => requisicao(`/api/pets/${petId}/alertas?limite=${limite}`),
  marcarLido: (alertaId) => requisicao(`/api/alertas/${alertaId}/lido`, { method: "PATCH" }),
  resumo: (petId) => requisicao(`/api/pets/${petId}/resumo`),
  historicoChat: (petId) => requisicao(`/api/pets/${petId}/chat`),
  perguntar: (petId, mensagem) => requisicao(`/api/pets/${petId}/chat`, { method: "POST", body: { mensagem } }),
  // Envio de leitura direto pelo app (ex.: coleira pareada via Bluetooth)
  enviarLeitura: (leitura) => requisicao("/api/leituras", { method: "POST", body: { ...leitura, origem: "app" } }),
};
