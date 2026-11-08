import { state } from "../state.js";

// Los proveedores que el proxy tiene con key. Si no hay proxy, no hay lista.
export async function providerOptions() {
  const proxyUrl = state.assistant?.proxyUrl;
  if (!proxyUrl) return [];
  try {
    const response = await fetch(`${proxyUrl.replace(/\/$/, "")}/v1/providers`, {
      headers: { Authorization: `Bearer ${state.assistant.proxyToken || "demo"}` },
      cache: "no-store",
    });
    if (!response.ok) return [];
    const data = await response.json();
    const options = [];
    for (const provider of data.providers || []) {
      if (!provider.configured) continue;
      for (const model of provider.models || []) {
        options.push({ value: `${provider.id}/${model}`, label: `${provider.id} · ${model}` });
      }
    }
    return options;
  } catch {
    return [];
  }
}

// Deja el primero del catálogo si el modelo configurado no está disponible.
export function pickProvider(options) {
  if (!options.length) return null;
  const current = state.assistant.model;
  const match = options.find((option) => option.value === current);
  if (!match) state.assistant.model = options[0].value;
  return state.assistant.model;
}
