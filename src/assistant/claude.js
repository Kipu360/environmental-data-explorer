import Anthropic from "@anthropic-ai/sdk";
import { state } from "../state.js";

export { Anthropic };

let client = null;
let clientKey = null;

function clientFor(apiKey) {
  const proxyUrl = state.assistant?.proxyUrl;
  const key = proxyUrl ? state.assistant.proxyToken || "demo" : apiKey;
  const cacheKey = `${proxyUrl || ""}|${key}`;
  if (!client || clientKey !== cacheKey) {
    client = new Anthropic({ apiKey: key, ...(proxyUrl ? { baseURL: proxyUrl } : {}), dangerouslyAllowBrowser: true });
    clientKey = cacheKey;
  }
  return client;
}

export function modelLabel() {
  const model = state.assistant.model || "";
  const name = model.includes("/") ? model.split("/").slice(1).join("/") : model;
  const words = [];
  const numbers = [];
  for (const part of name.split("-")) (/^\d+$/.test(part) ? numbers : words).push(part);
  return [...words.map((word) => word[0].toUpperCase() + word.slice(1)), numbers.join(".")].filter(Boolean).join(" ");
}

// One streamed turn. Top-level cache_control caches the growing conversation, so the
// guide and tool definitions are billed at the cache-read rate after the first call.
export function streamTurn({ apiKey, system, tools, messages, onText }) {
  const { model, effort, maxTokens, fallbacks } = state.assistant;
  const request = {
    model,
    max_tokens: maxTokens,
    output_config: { effort },
    cache_control: { type: "ephemeral" },
    system,
    tools,
    messages,
  };
  const stream = fallbacks
    ? clientFor(apiKey).beta.messages.stream({ ...request, betas: ["server-side-fallback-2026-07-01"], fallbacks })
    : clientFor(apiKey).messages.stream(request);
  stream.on("text", onText);
  return stream.finalMessage();
}
