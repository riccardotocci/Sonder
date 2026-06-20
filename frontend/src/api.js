const API_BASE = "";

async function postJSON(path, body) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "";
    const raw = await res.text();
    try {
      const data = JSON.parse(raw);
      detail = data.error || data.detail || "";
    } catch (e) {
      detail = raw;
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export function getBootstrap(lang) {
  const qs = lang ? `?lang=${encodeURIComponent(lang)}` : "";
  return fetch(API_BASE + "/api/bootstrap" + qs).then((r) => r.json());
}

export function postChat(payload) {
  return postJSON("/api/chat", payload);
}

// Fase 2: genera i testi narrati per i brani gia' arricchiti dalla fase 1.
export function postNarrate(payload) {
  return postJSON("/api/narrate", payload);
}

export function postTTS(text) {
  return postJSON("/api/tts", { text });
}

export function spotifyExchange(code, redirectUri, codeVerifier) {
  return postJSON("/api/spotify/exchange", {
    code,
    redirect_uri: redirectUri,
    code_verifier: codeVerifier,
  });
}

export function spotifyRefresh(refreshToken) {
  return postJSON("/api/spotify/refresh", { refresh_token: refreshToken });
}

export function spotifyThemeRecs(spotifyToken, language, llmModel) {
  return postJSON("/api/spotify/theme-recs", {
    spotify_token: spotifyToken,
    language,
    llm_model: llmModel,
  });
}

export function spotifyCreatePlaylist(spotifyToken, tracks, name) {
  return postJSON("/api/spotify/create-playlist", {
    spotify_token: spotifyToken,
    tracks,
    name: name || "Conversation",
  });
}

export { API_BASE };
