import { useEffect, useState } from "react";
import { useT } from "../i18n.jsx";

// Contenuti dell'About co-locati nel componente (prosa lunga: non ha senso
// gonfiare il dizionario i18n con 9 lingue). Si seleziona la lingua corrente
// dell'interfaccia con fallback all'inglese per le lingue non tradotte.
const CONTENT = {
  en: {
    kicker: "About the project",
    tagline:
      "the realization that every song carries an inner world as vivid and complex as your own.",
    ideaHeading: "The idea",
    ideaLead:
      "Sonder takes a theme, a feeling, a message — or simply an artist and a song — and turns it into a narrated, multilingual emotional journey through real music. It doesn't just build a playlist: it tells the human story behind every track, with the voice of an AI narrator who actually read the lyrics.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Start from anything",
        text: "A theme, a mood, a sentence, or just an artist and a song. Sonder finds the music that fits.",
      },
      {
        icon: "🗣️",
        title: "A narrated journey",
        text: "An AI voice tells the emotional story behind each track, like a radio host who read between the lines.",
      },
      {
        icon: "🌍",
        title: "Multilingual by design",
        text: "Explore in 9 languages — narration, lyric translations and the whole interface follow your choice.",
      },
      {
        icon: "🗺️",
        title: "A map of origins",
        text: "See where every artist comes from, plotted on an interactive world map.",
      },
      {
        icon: "🎧",
        title: "Real, known songs",
        text: "Tracks are filtered by real streaming numbers, so you discover music that genuinely resonated.",
      },
      {
        icon: "▶️",
        title: "Listen & keep",
        text: "Play full tracks through your Spotify and save the whole journey as a playlist.",
      },
    ],
    techKicker: "Under the hood",
    techHeading: "How it works",
    techLead:
      "Behind a single prompt, Sonder chains a handful of specialized services. Everything degrades gracefully — the app boots and runs even with zero API keys, falling back to a demo mode that tells you which variable to set.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Themed lyric & track search — fetches lyrics and translations.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Artist bios, images, metadata and external IDs used to map their origins.",
      },
      {
        name: "Thinking engine (LLM)",
        text: "An OpenAI-compatible model routes your theme into balanced multilingual queries, writes the narration and derives mood & geography.",
      },
      {
        name: "Songstats",
        text: "Real streaming statistics by ISRC, used to keep only genuinely notable tracks.",
      },
      {
        name: "ElevenLabs",
        text: "Text-to-speech turns the narration into a natural AI voice.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Per-user login for full playback and one-click playlist creation.",
      },
    ],
    stackHeading: "Built with",
    archNote:
      "A React (Vite) front-end talks to a FastAPI back-end that reuses the Python service clients; in production FastAPI also serves the built single-page app. The Studio is a self-contained interactive experience rendered in an isolated frame.",
    madeBy: "Made by",
    role: "Creator & developer of Sonder",
  },
  it: {
    kicker: "Il progetto",
    tagline:
      "la consapevolezza che ogni canzone porta con sé un mondo interiore vivido e complesso quanto il tuo.",
    ideaHeading: "L'idea",
    ideaLead:
      "Sonder prende un tema, un'emozione, un messaggio — o semplicemente un artista e un brano — e lo trasforma in un viaggio emotivo narrato e multilingue attraverso musica vera. Non costruisce solo una playlist: racconta la storia umana dietro ogni brano, con la voce di un narratore AI che i testi li ha letti davvero.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Parti da qualsiasi cosa",
        text: "Un tema, un'atmosfera, una frase, o solo un artista e un brano. Sonder trova la musica giusta.",
      },
      {
        icon: "🗣️",
        title: "Un viaggio narrato",
        text: "Una voce AI racconta la storia emotiva dietro ogni brano, come un conduttore radio che ha letto tra le righe.",
      },
      {
        icon: "🌍",
        title: "Multilingue per natura",
        text: "Esplora in 9 lingue — narrazione, traduzioni dei testi e tutta l'interfaccia seguono la tua scelta.",
      },
      {
        icon: "🗺️",
        title: "Una mappa delle origini",
        text: "Scopri da dove viene ogni artista, posizionato su una mappa del mondo interattiva.",
      },
      {
        icon: "🎧",
        title: "Brani veri e conosciuti",
        text: "I brani sono filtrati sui numeri di streaming reali: scopri musica che ha davvero lasciato il segno.",
      },
      {
        icon: "▶️",
        title: "Ascolta e conserva",
        text: "Riproduci i brani interi con il tuo Spotify e salva l'intero viaggio come playlist.",
      },
    ],
    techKicker: "Sotto il cofano",
    techHeading: "Come funziona",
    techLead:
      "Dietro a un singolo prompt, Sonder concatena una serie di servizi specializzati. Tutto degrada con grazia — l'app si avvia e funziona anche senza nessuna chiave API, con un demo mode che ti dice quale variabile impostare.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Ricerca tematica di testi e brani — recupera testi e traduzioni.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Biografie, immagini, metadati e ID esterni degli artisti, usati per mapparne le origini.",
      },
      {
        name: "Motore di pensiero (LLM)",
        text: "Un modello OpenAI-compatible instrada il tema in query multilingue bilanciate, scrive la narrazione e ricava mood e geografia.",
      },
      {
        name: "Songstats",
        text: "Statistiche di streaming reali per ISRC, usate per tenere solo i brani davvero noti.",
      },
      {
        name: "ElevenLabs",
        text: "Il text-to-speech trasforma la narrazione in una voce AI naturale.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Accesso per-utente per la riproduzione completa e la creazione di playlist con un clic.",
      },
    ],
    stackHeading: "Costruito con",
    archNote:
      "Un front-end React (Vite) dialoga con un back-end FastAPI che riusa i client dei servizi in Python; in produzione FastAPI serve anche la single-page app compilata. Lo Studio è un'esperienza interattiva autonoma resa in un frame isolato.",
    madeBy: "Realizzato da",
    role: "Ideatore e sviluppatore di Sonder",
  },
};

const STACK = [
  "React + Vite",
  "FastAPI",
  "OpenRouter / OpenAI",
  "ElevenLabs",
  "Spotify Web API",
  "Musixmatch",
  "Songstats",
  "MusicBrainz",
  "TheAudioDB",
];

// Possibili nomi/estensioni della foto autore in /static: si prova in ordine e,
// se nessuna esiste, si ripiega sul monogramma "RT". Basta rilasciare il file in
// static/ con uno di questi nomi perché la foto compaia automaticamente.
const PHOTO_CANDIDATES = [
  "/static/riccardo.jpg",
  "/static/riccardo.png",
  "/static/riccardo.jpeg",
  "/static/riccardo.webp",
];

export default function About({ onClose }) {
  const { code, t } = useT();
  const c = CONTENT[code] || CONTENT.en;
  const [photoIdx, setPhotoIdx] = useState(0);
  const photoSrc =
    photoIdx < PHOTO_CANDIDATES.length ? PHOTO_CANDIDATES[photoIdx] : null;

  // Chiudi con ESC + blocca lo scroll del body finché l'overlay è aperto, così
  // non scorre la pagina sottostante (Studio incluso) mentre leggi l'About.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="about-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="About Sonder"
    >
      <div className="about-backdrop" onClick={onClose} />
      <div className="about-panel">
        <button
          className="about-close"
          onClick={onClose}
          title={t("aboutClose")}
          aria-label={t("aboutClose")}
        >
          ✕
        </button>

        <header className="about-head">
          <div className="about-kicker">{c.kicker}</div>
          <h1 className="about-title">Sonder</h1>
          <p className="about-tagline">
            <em>sonder</em> — {c.tagline}
          </p>
        </header>

        {/* Parte 1: l'idea */}
        <section className="about-section">
          <h2 className="about-h2">{c.ideaHeading}</h2>
          <p className="about-lead">{c.ideaLead}</p>
          <div className="about-grid">
            {c.ideaPoints.map((p) => (
              <div className="about-feature" key={p.title}>
                <span className="about-feature-icon">{p.icon}</span>
                <div>
                  <div className="about-feature-title">{p.title}</div>
                  <div className="about-feature-text">{p.text}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <hr className="hr-glow" />

        {/* Parte 2: tecnica */}
        <section className="about-section">
          <div className="about-section-kicker">{c.techKicker}</div>
          <h2 className="about-h2">{c.techHeading}</h2>
          <p className="about-lead">{c.techLead}</p>

          <ol className="about-pipeline">
            {c.pipeline.map((step, i) => (
              <li className="about-step" key={step.name}>
                <span className="about-step-num">{i + 1}</span>
                <div>
                  <div className="about-step-name">{step.name}</div>
                  <div className="about-step-text">{step.text}</div>
                </div>
              </li>
            ))}
          </ol>

          <h3 className="about-h3">{c.stackHeading}</h3>
          <div className="about-stack">
            {STACK.map((s) => (
              <span className="pill about-pill" key={s}>
                {s}
              </span>
            ))}
          </div>
          <p className="about-arch">{c.archNote}</p>
        </section>

        {/* Footer: autore */}
        <footer className="about-author">
          <div className="about-avatar">
            {photoSrc ? (
              <img
                src={photoSrc}
                alt="Riccardo Tocci"
                onError={() => setPhotoIdx((i) => i + 1)}
              />
            ) : (
              <span className="about-avatar-fallback">RT</span>
            )}
          </div>
          <div className="about-author-meta">
            <div className="about-author-label">{c.madeBy}</div>
            <div className="about-author-name">Riccardo Tocci</div>
            <div className="about-author-role">{c.role}</div>
          </div>
        </footer>
      </div>
    </div>
  );
}
