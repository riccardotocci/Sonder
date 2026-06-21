import { useMemo, useRef, useEffect, useCallback } from "react";
import rawStudioHtml from "../studio.html?raw";
import StudioSections from "./StudioSections.jsx";
import Songstats from "./Songstats.jsx";
import { useT, getStudioStrings } from "../i18n.jsx";

// Interruttore della sezione Songstats. Quando e' false la sezione non viene
// renderizzata e non parte alcuna chiamata a /api/songstats.
const SONGSTATS_ENABLED = false;

const STUDIO_FIELDS = [
  "title",
  "artist",
  "speech",
  "musixmatch_speech",
  "audiodb_speech",
  "mood",
  "origin",
  "reason",
  "image",
  "uri",
  "audio_b64",
  "speech_marks",
  "lyrics",
  "translated_lyrics",
  "translation_lang",
  "richsync",
  "track_id",
  "album",
];

function buildSrcDoc(studio, ttsLang, token, langCode, narrationPending) {
  const tracks = (studio.tracks || []).map((t) => {
    const out = {};
    for (const f of STUDIO_FIELDS) out[f] = t[f] !== undefined ? t[f] : "";
    return out;
  });
  const tracksJson = JSON.stringify(tracks).replace(/<\//g, "<\\/");
  const playlistName = JSON.stringify(`Sonder · ${(studio.prompt || "").slice(0, 60)}`);
  const ttsEndpoint = JSON.stringify(window.location.origin + "/api/tts");
  const i18nJson = JSON.stringify(getStudioStrings(langCode)).replace(/<\//g, "<\\/");

  return rawStudioHtml
    .replace("__TRACKS__", tracksJson)
    .replace("__TTSLANG__", JSON.stringify(ttsLang || ""))
    .replace("__PLAYLIST__", playlistName)
    .replace("__TOKEN__", JSON.stringify(token || ""))
    .replace("__TTS_ENDPOINT__", ttsEndpoint)
    .replace("__TTS_TOKEN__", JSON.stringify(""))
    .replace("__TTS_MODE__", JSON.stringify("local"))
    .replace("__STUDIO_ID__", JSON.stringify(""))
    .replace("__I18N__", i18nJson)
    .replace("__NARRATION_PENDING__", JSON.stringify(!!narrationPending))
    .replace("__AUTOPLAY__", JSON.stringify({}));
}

export default function Studio({
  studio,
  ttsLang,
  token,
  narrationPending,
  narrationSpeeches,
  onSpotifyUnavailable,
}) {
  const { t, code } = useT();
  const iframeRef = useRef(null);
  const speechesRef = useRef(null);

  // L'iframe viene costruito SOLO dai dati di fase 1. I testi narrati (fase 2)
  // arrivano dopo via postMessage, cosi' l'iframe NON viene ricaricato (cosa che
  // interromperebbe la riproduzione Spotify). narrationPending viene letto qui ma
  // NON e' una dipendenza: spegnerlo all'arrivo della narrazione non deve
  // ricostruire/ricaricare l'iframe.
  const srcDoc = useMemo(
    () => buildSrcDoc(studio, ttsLang, token, code, narrationPending),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [studio, ttsLang, token, code]
  );

  const pushNarration = useCallback(() => {
    const speeches = speechesRef.current;
    const win = iframeRef.current && iframeRef.current.contentWindow;
    if (!speeches || !win) return;
    win.postMessage({ type: "sonder-narration", speeches }, "*");
  }, []);

  useEffect(() => {
    speechesRef.current = narrationSpeeches || null;
    if (narrationSpeeches) pushNarration();
  }, [narrationSpeeches, pushNarration]);

  // Quando l'iframe segnala che il suo listener e' pronto, gli (ri)inviamo i
  // testi narrati. Copre la gara in cui la narrazione arriva prima che l'iframe
  // abbia finito di caricare/registrare il listener (LLM molto veloce).
  useEffect(() => {
    const onMsg = (ev) => {
      // Accetta il segnale solo dal nostro iframe (non da altri frame/embed).
      const win = iframeRef.current && iframeRef.current.contentWindow;
      if (ev.source !== win) return;
      if (!ev.data) return;
      if (ev.data.type === "sonder-studio-ready") pushNarration();
      // Rate limit di Spotify: l'iframe chiede al parent di disconnettere e
      // mostrare il messaggio "SPOTIFY al momento non disponibile".
      if (ev.data.type === "sonder-spotify-rate-limit") {
        if (onSpotifyUnavailable) onSpotifyUnavailable();
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [pushNarration, onSpotifyUnavailable]);

  return (
    <div>
      <div className="studio-prompt">
        {(studio.prompt || "").trim() || t("untitled")}
      </div>
      <hr className="hr-glow" />

      <iframe
        ref={iframeRef}
        className="studio-iframe"
        title="Sonder Studio"
        srcDoc={srcDoc}
        height={860}
        onLoad={pushNarration}
        sandbox="allow-scripts allow-same-origin allow-popups allow-presentation"
      />

      <StudioSections studio={studio} token={token} />
      {/* Sezione Songstats disattivata: non viene renderizzata, cosi' non parte
          nessuna chiamata a /api/songstats. Reimpostare SONGSTATS_ENABLED a true
          per riattivarla. */}
      {SONGSTATS_ENABLED && <Songstats studio={studio} token={token} />}
    </div>
  );
}
