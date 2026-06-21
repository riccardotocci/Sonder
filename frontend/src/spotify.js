import { spotifyExchange, spotifyRefresh } from "./api.js";

const TOKEN_KEY = "sonder_spotify_session";
const VERIFIER_KEY = "sonder_pkce_verifier";
const STATE_KEY = "sonder_pkce_state";
const PERSIST_KEY = "sonder_pkce_persist";

export function consumePersistPref() {
  const pref = sessionStorage.getItem(PERSIST_KEY) === "1";
  sessionStorage.removeItem(PERSIST_KEY);
  return pref;
}

function randomString(len) {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
  const arr = new Uint8Array(len);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => chars[b % chars.length]).join("");
}

function base64UrlEncode(buffer) {
  let str = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256(plain) {
  const data = new TextEncoder().encode(plain);
  return crypto.subtle.digest("SHA-256", data);
}

// Usa sempre l'origine corrente come redirect_uri: cosi' il login torna sullo
// stesso dominio da cui e' partito (es. sonder-music.pro -> sonder-music.pro).
// E' obbligatorio per il PKCE, perche' il verifier in sessionStorage e' legato
// all'origine: un redirect su un dominio diverso lo renderebbe irraggiungibile
// e lo scambio del token fallirebbe. Fallback al valore configurato dal backend.
function resolveRedirectUri(spotifyConf) {
  if (typeof window !== "undefined" && window.location && window.location.origin) {
    return window.location.origin;
  }
  return spotifyConf.redirect_uri;
}

export function loadSpotifyToken() {
  try {
    const raw = localStorage.getItem(TOKEN_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

export function saveSpotifyToken(session) {
  try {
    localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
  } catch (e) {
    /* ignore */
  }
}

export function clearSpotifyToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch (e) {
    /* ignore */
  }
}

// Begin the PKCE flow: build the authorize URL and redirect the browser.
export async function beginSpotifyLogin(spotifyConf, persist = true) {
  const verifier = randomString(64);
  const state = randomString(16);
  const challenge = base64UrlEncode(await sha256(verifier));
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(PERSIST_KEY, persist ? "1" : "0");

  const params = new URLSearchParams({
    client_id: spotifyConf.client_id,
    response_type: "code",
    redirect_uri: resolveRedirectUri(spotifyConf),
    code_challenge_method: "S256",
    code_challenge: challenge,
    scope: spotifyConf.scopes,
    show_dialog: "true",
    state,
  });
  window.location.href = `${spotifyConf.auth_url}?${params.toString()}`;
}

// On load, if we've been redirected back with ?code=, exchange it for tokens.
export async function consumePkceRedirect(spotifyConf) {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!code) return null;

  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  const savedState = sessionStorage.getItem(STATE_KEY);

  // Clean the query string regardless of outcome.
  url.searchParams.delete("code");
  url.searchParams.delete("state");
  url.searchParams.delete("error");
  window.history.replaceState({}, document.title, url.pathname + url.search);

  if (!verifier || (savedState && state && savedState !== state)) return null;

  try {
    const data = await spotifyExchange(
      code,
      resolveRedirectUri(spotifyConf),
      verifier
    );
    sessionStorage.removeItem(VERIFIER_KEY);
    sessionStorage.removeItem(STATE_KEY);
    return { ...data, obtained_at: Date.now() };
  } catch (e) {
    console.warn("Spotify token exchange failed", e);
    return null;
  }
}

export async function refreshSpotify(refreshToken) {
  const data = await spotifyRefresh(refreshToken);
  return { ...data, refresh_token: data.refresh_token || refreshToken, obtained_at: Date.now() };
}
