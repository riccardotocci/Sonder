import { useEffect, useState, useCallback, useRef } from "react";
import Sidebar from "./components/Sidebar.jsx";
import ChatLanding from "./components/ChatLanding.jsx";
import Messages from "./components/Messages.jsx";
import ThinkingPipeline, {
  RotatingThinking,
} from "./components/ThinkingPipeline.jsx";
import Studio from "./components/Studio.jsx";
import LanguageSelector from "./components/LanguageSelector.jsx";
import About from "./components/About.jsx";
import {
  LangProvider,
  getInitialLang,
  persistLang,
  getLang,
  translate,
} from "./i18n.jsx";
import { getBootstrap, postChat, postNarrate, postSeed } from "./api.js";
import {
  loadSpotifyToken,
  saveSpotifyToken,
  clearSpotifyToken,
  consumePkceRedirect,
  consumePersistPref,
  refreshSpotify,
} from "./spotify.js";

// Imposta a false per nascondere temporaneamente la pipeline di pensiero.
const SHOW_THINKING_PIPELINE = false;

export default function App() {
  const [boot, setBoot] = useState(null);
  const [messages, setMessages] = useState([]);
  const [studio, setStudio] = useState(null);
  // Fase 2 narrazione: in attesa della generazione dei testi narrati (mostra la
  // barra di caricamento + disabilita la narrazione) e i testi una volta pronti.
  const [narrationPending, setNarrationPending] = useState(false);
  const [narrationSpeeches, setNarrationSpeeches] = useState(null);
  const [ttsLang, setTtsLang] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [searchLanguages, setSearchLanguages] = useState([]);
  const [llmModel, setLlmModel] = useState("");
  const [spotify, setSpotify] = useState(null); // { access_token, refresh_token, ... }
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [uiLang, setUiLang] = useState(getInitialLang);
  const spotifyRestored = useRef(false);
  // Bumped on every New chat (and every send) so a slow in-flight /api/chat
  // response that resolves after a reset is ignored instead of repopulating
  // the freshly-cleared conversation.
  const chatGen = useRef(0);

  const t = useCallback((key, vars) => translate(uiLang, key, vars), [uiLang]);

  const changeLang = useCallback((code) => {
    setUiLang(code);
    persistLang(code);
  }, []);

  // Bootstrap: fetch config + greeting (re-fetched when the UI language changes
  // so the greeting + example prompts follow the selected language). The
  // selected language is also what forces narration + translations downstream.
  useEffect(() => {
    getBootstrap(getLang(uiLang).key)
      .then((data) => {
        setBoot(data);
        setLlmModel((m) => m || data.selected_llm_model || "");
        // Only refresh the greeting while still on the landing (no real
        // conversation yet); never clobber an in-progress chat history.
        setMessages((m) =>
          m.length <= 1 ? [{ role: "assistant", content: data.greeting }] : m,
        );
      })
      .catch((e) => setError(String(e)));
  }, [uiLang]);

  // Restore Spotify session + finish PKCE redirect if present (run once).
  useEffect(() => {
    if (!boot || spotifyRestored.current) return;
    spotifyRestored.current = true;
    (async () => {
      const stored = loadSpotifyToken();
      if (stored) {
        // If the stored access token is already expired, refresh it before use
        // so the first request doesn't go out with a dead token.
        const expiresAt =
          (Number(stored.obtained_at) || 0) +
          (Number(stored.expires_in) || 3600) * 1000;
        if (stored.refresh_token && Date.now() > expiresAt - 60_000) {
          try {
            const refreshed = await refreshSpotify(stored.refresh_token);
            setSpotify(refreshed);
            saveSpotifyToken(refreshed);
          } catch (e) {
            console.warn("Spotify token refresh on restore failed", e);
            clearSpotifyToken();
          }
        } else {
          setSpotify(stored);
        }
      }
      const redirected = await consumePkceRedirect(boot.spotify);
      if (redirected) {
        setSpotify(redirected);
        if (consumePersistPref()) saveSpotifyToken(redirected);
      }
    })().catch((e) => console.warn("spotify restore", e));
  }, [boot]);

  const token = spotify?.access_token || "";

  // Keep the Spotify session alive: access tokens expire (~1h). Without this,
  // the player can't resolve track URIs and Songstats can't resolve ISRCs
  // (backend Spotify search returns 401), so playback and stats silently break.
  useEffect(() => {
    if (!spotify?.refresh_token) return;
    const expiresIn = Number(spotify.expires_in) || 3600;
    const obtainedAt = Number(spotify.obtained_at) || Date.now();
    const expiresAt = obtainedAt + expiresIn * 1000;
    // Refresh 60s before expiry; if already (nearly) expired, refresh now.
    const delay = Math.max(expiresAt - Date.now() - 60_000, 0);
    const persisted = !!loadSpotifyToken();
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const refreshed = await refreshSpotify(spotify.refresh_token);
        if (cancelled) return;
        setSpotify(refreshed);
        if (persisted) saveSpotifyToken(refreshed);
      } catch (e) {
        console.warn("Spotify token refresh failed", e);
        if (!cancelled) {
          clearSpotifyToken();
          setSpotify(null);
        }
      }
    }, delay);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [spotify]);

  // Gestione condivisa della risposta di /api/chat e /api/seed: aggiunge la
  // risposta dell'assistente, mostra lo Studio (fase 1) e lancia la narrazione
  // (fase 2, non bloccante). ``fallbackLabel`` e' il tema usato per la narrazione
  // quando lo Studio non porta un prompt proprio.
  const handleChatResult = useCallback(
    (res, gen, fallbackLabel) => {
      // Drop the response if a New chat (or newer send) happened meanwhile.
      if (gen !== chatGen.current) return;
      setMessages((m) => [...m, res.assistant_message]);
      setTtsLang(res.tts_lang || "");
      if (res.studio && (res.studio.tracks || []).length) {
        // Fase 1: mostra subito lo Studio con tutti i dati dei servizi.
        setStudio(res.studio);
        setNarrationSpeeches(null);
        setNarrationPending(true);
        // Fase 2 (non bloccante): genera i testi narrati e popolali quando
        // pronti. Fino ad allora lo Studio mostra una barra di caricamento e
        // disabilita la narrazione, ma consente di scegliere e lanciare i brani.
        // Watchdog: se la richiesta si blocca, sblocca comunque la UI cosi' la
        // barra di caricamento non resta all'infinito (la narrazione, se arriva
        // piu' tardi, popola ugualmente il testo).
        const watchdog = setTimeout(() => {
          if (gen !== chatGen.current) return;
          setNarrationSpeeches([]);
          setNarrationPending(false);
        }, 180000);
        postNarrate({
          prompt: res.studio.prompt || fallbackLabel,
          tracks: res.studio.tracks,
          language: getLang(uiLang).key,
          llm_model: llmModel,
        })
          .then((nr) => {
            clearTimeout(watchdog);
            if (gen !== chatGen.current) return;
            setNarrationSpeeches(nr.speeches || []);
            setNarrationPending(false);
          })
          .catch((err) => {
            clearTimeout(watchdog);
            console.warn("[narrate] failed", err);
            if (gen !== chatGen.current) return;
            // Sblocca comunque la UI: senza testi narrati la narrazione resta
            // priva di contenuto ma i comandi tornano disponibili.
            setNarrationSpeeches([]);
            setNarrationPending(false);
          });
      } else {
        setNarrationPending(false);
        setNarrationSpeeches(null);
      }
    },
    [uiLang, llmModel],
  );

  const sendPrompt = useCallback(
    async (prompt) => {
      const text = (prompt || "").trim();
      if (!text || busy) return;
      setError("");
      const gen = ++chatGen.current;
      const history = messages;
      setMessages((m) => [...m, { role: "user", content: text }]);
      setBusy(true);
      const payload = {
        messages: history,
        prompt: text,
        search_languages: searchLanguages,
        llm_model: llmModel,
        spotify_token: token,
        language: getLang(uiLang).key,
      };
      // Debug: log exactly what we send to /api/chat so we can see when the
      // LLM "struggles" / hangs (watch the elapsed time below).
      console.log("[chat] → POST /api/chat", {
        prompt: payload.prompt,
        history_len: payload.messages.length,
        language: payload.language,
        search_languages: payload.search_languages,
        llm_model: payload.llm_model || "(default)",
        has_spotify_token: !!payload.spotify_token,
        messages: payload.messages,
      });
      const startedAt = performance.now();
      try {
        const res = await postChat(payload);
        const elapsed = ((performance.now() - startedAt) / 1000).toFixed(1);
        console.log(`[chat] ← OK in ${elapsed}s`, {
          assistant_len: (res.assistant_message?.content || "").length,
          tracks: (res.assistant_message?.tracks || []).length,
          studio_tracks: (res.studio?.tracks || []).length,
          tts_lang: res.tts_lang || "",
          llm_log: res.assistant_message?.llm_log,
        });
        handleChatResult(res, gen, text);
      } catch (e) {
        const elapsed = ((performance.now() - startedAt) / 1000).toFixed(1);
        console.error(`[chat] ✗ FAILED after ${elapsed}s`, e);
        if (gen !== chatGen.current) return;
        setError(String(e.message || e));
        setMessages((m) => [
          ...m,
          { role: "assistant", content: "⚠️ " + String(e.message || e) },
        ]);
      } finally {
        if (gen === chatGen.current) setBusy(false);
      }
    },
    [messages, busy, searchLanguages, llmModel, token, uiLang, handleChatResult],
  );

  // Ricerca per artista (+ brano opzionale). Il backend recupera testi e temi da
  // Musixmatch e li passa allo stesso router LLM di /api/chat. La chat mostra
  // l'etichetta leggibile (artista — brano), non il prompt-seed lungo coi testi.
  const sendSeed = useCallback(
    async (artist, song) => {
      const a = (artist || "").trim();
      const s = (song || "").trim();
      if (!a || busy) return;
      setError("");
      const gen = ++chatGen.current;
      const history = messages;
      const label = s ? `${a} — ${s}` : a;
      setMessages((m) => [...m, { role: "user", content: label }]);
      setBusy(true);
      const payload = {
        messages: history,
        artist: a,
        song: s,
        search_languages: searchLanguages,
        llm_model: llmModel,
        spotify_token: token,
        language: getLang(uiLang).key,
      };
      console.log("[seed] → POST /api/seed", {
        artist: a,
        song: s,
        history_len: payload.messages.length,
        language: payload.language,
        search_languages: payload.search_languages,
        llm_model: payload.llm_model || "(default)",
      });
      const startedAt = performance.now();
      try {
        const res = await postSeed(payload);
        const elapsed = ((performance.now() - startedAt) / 1000).toFixed(1);
        console.log(`[seed] ← OK in ${elapsed}s`, {
          tracks: (res.assistant_message?.tracks || []).length,
          studio_tracks: (res.studio?.tracks || []).length,
        });
        handleChatResult(res, gen, label);
      } catch (e) {
        const elapsed = ((performance.now() - startedAt) / 1000).toFixed(1);
        console.error(`[seed] ✗ FAILED after ${elapsed}s`, e);
        if (gen !== chatGen.current) return;
        // "Brano/artista non trovato" (404 dal backend): niente errore tecnico in
        // chat. Annulliamo il messaggio utente ottimistico (cosi' la landing con
        // la seed bar torna visibile) e mostriamo un avviso gentile: riprova.
        if (String(e.message || e).includes("seed_not_found")) {
          setMessages(history);
          setError(translate(uiLang, "seedNotFound"));
        } else {
          setError(String(e.message || e));
          setMessages((m) => [
            ...m,
            { role: "assistant", content: "⚠️ " + String(e.message || e) },
          ]);
        }
      } finally {
        if (gen === chatGen.current) setBusy(false);
      }
    },
    [messages, busy, searchLanguages, llmModel, token, uiLang, handleChatResult],
  );

  const newChat = useCallback(() => {
    if (!boot) return;
    // Full reset of the conversation/ephemeral state back to a clean landing.
    // The Spotify session is intentionally kept. We DO reset the studio graphics
    // and the per-conversation track-language selection so a new chat starts
    // from a blank slate (no leftover studio, no inherited language filter).
    // Invalidate any in-flight chat request so its late response can't repopulate.
    chatGen.current += 1;
    setMessages([{ role: "assistant", content: boot.greeting }]);
    setStudio(null);
    setSearchLanguages([]);
    setNarrationPending(false);
    setNarrationSpeeches(null);
    setTtsLang("");
    setBusy(false);
    setError("");
  }, [boot]);

  const setSpotifySession = useCallback((session, persist) => {
    setSpotify(session);
    if (session && persist) saveSpotifyToken(session);
    if (!session) clearSpotifyToken();
  }, []);

  // Rate limit di Spotify (429): mostra "SPOTIFY al momento non disponibile" e
  // disconnette la sessione (logout). La riconnessione resta manuale: l'utente
  // ricollega Spotify dalla sidebar quando vuole riprovare.
  const handleSpotifyUnavailable = useCallback(() => {
    clearSpotifyToken();
    setSpotify(null);
    setError(translate(uiLang, "spotifyUnavailable"));
  }, [uiLang]);

  if (!boot) {
    return (
      <LangProvider code={uiLang}>
        <div className="app-shell">
          <LanguageSelector value={uiLang} onChange={changeLang} />
          <div className="main-area">
            <div className="thinking">
              <span className="spinner" /> {t("loading")}
              {error && (
                <div style={{ color: "#ff6b6b", marginTop: "1rem" }}>
                  {error}
                </div>
              )}
            </div>
          </div>
        </div>
      </LangProvider>
    );
  }

  const hasConversation = messages.length > 1;
  // Once a request has been made, hide the landing/search bar and the full chat,
  // leaving only the Thinking pipeline and the Studio.
  const showResults = hasConversation || busy || !!studio;

  return (
    <LangProvider code={uiLang}>
      <div className={"app-shell" + (sidebarOpen ? "" : " sidebar-collapsed")}>
        <LanguageSelector value={uiLang} onChange={changeLang} />
        {sidebarOpen ? (
          <Sidebar
            boot={boot}
            spotify={spotify}
            onSpotifySession={setSpotifySession}
            llmModel={llmModel}
            setLlmModel={setLlmModel}
            onNewChat={newChat}
            token={token}
            onCollapse={() => setSidebarOpen(false)}
            onOpenAbout={() => setAboutOpen(true)}
          />
        ) : (
          <button
            className="sidebar-open-btn"
            onClick={() => setSidebarOpen(true)}
            title={t("showPanel")}
            aria-label={t("showPanel")}
          >
            ☰
          </button>
        )}
        <div className="main-area">
          {!showResults && (
            <ChatLanding
              boot={boot}
              searchLanguages={searchLanguages}
              setSearchLanguages={setSearchLanguages}
              onSend={sendPrompt}
              onSeed={sendSeed}
              busy={busy}
              compact={false}
            />
          )}

          {error && (
            <div
              className="glass-card"
              style={{
                borderColor: "rgba(255,45,120,.4)",
                marginBottom: "1rem",
              }}
            >
              {error}
            </div>
          )}

          {showResults ? (
            <>
              {SHOW_THINKING_PIPELINE && (
                <ThinkingPipeline messages={messages} busy={busy} />
              )}
              {busy && !studio && (
                <div className="messages">
                  <div className="msg msg-assistant">
                    <div className="msg-avatar">🎵</div>
                    <div className="msg-body">
                      <RotatingThinking />
                    </div>
                  </div>
                </div>
              )}
              {studio && (
                <Studio
                  studio={studio}
                  ttsLang={ttsLang}
                  token={token}
                  narrationPending={narrationPending}
                  narrationSpeeches={narrationSpeeches}
                  onSpotifyUnavailable={handleSpotifyUnavailable}
                />
              )}
            </>
          ) : (
            <Messages
              messages={messages}
              busy={busy}
              token={token}
              spotifyReady={!!boot.spotify?.pkce_ready}
            />
          )}
        </div>
        {aboutOpen && <About onClose={() => setAboutOpen(false)} />}
      </div>
    </LangProvider>
  );
}
