import { useState } from "react";
import { useT, getLangName } from "../i18n.jsx";

export default function ChatLanding({
  boot,
  searchLanguages,
  setSearchLanguages,
  onSend,
  onSeed,
  busy,
  compact,
}) {
  const { t, code } = useT();
  const [value, setValue] = useState("");
  const [artist, setArtist] = useState("");
  const [song, setSong] = useState("");
  const [seedError, setSeedError] = useState("");

  const submit = (e) => {
    e.preventDefault();
    if (!value.trim() || busy) return;
    onSend(value);
    setValue("");
  };

  const submitSeed = (e) => {
    e.preventDefault();
    if (busy) return;
    const a = artist.trim();
    const s = song.trim();
    // L'artista e' obbligatorio: niente artista -> messaggio (vuoto vs solo brano).
    if (!a) {
      setSeedError(s ? t("seedSpecifyArtist") : t("seedWriteSomething"));
      return;
    }
    setSeedError("");
    onSeed(a, s);
    setArtist("");
    setSong("");
  };

  const toggleLang = (code) => {
    setSearchLanguages((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  };

  return (
    <div>
      {!compact && (
        <div className="hero-logo">
          <img src="/static/logo_text.png" alt="Sonder" />
        </div>
      )}

      {!compact && (
        <>
          <div className="hero-kicker">Sonder</div>
          <p className="hero-sub">{t("heroSub")}</p>
        </>
      )}

      <form className="chat-bar" onSubmit={submit}>
        <input
          className="chat-input"
          placeholder={t("inputPlaceholder")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={busy}
        />
        <button className="btn-primary" type="submit" disabled={busy || !value.trim()}>
          {busy ? "…" : t("send")}
        </button>
      </form>

      <div className="seed-search">
        <label className="field-label">{t("seedLabel")}</label>
        <form className="chat-bar seed-bar" onSubmit={submitSeed}>
          <input
            className="chat-input"
            placeholder={t("seedArtistPlaceholder")}
            value={artist}
            onChange={(e) => {
              setArtist(e.target.value);
              if (seedError) setSeedError("");
            }}
            disabled={busy}
          />
          <input
            className="chat-input"
            placeholder={t("seedSongPlaceholder")}
            value={song}
            onChange={(e) => setSong(e.target.value)}
            disabled={busy}
          />
          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? "…" : t("send")}
          </button>
        </form>
        {seedError && <div className="seed-hint">{seedError}</div>}
      </div>

      <div style={{ marginTop: "1rem" }}>
        <label className="field-label">{t("searchLangsLabel")}</label>
        <div className="multiselect">
          {boot.search_languages.map((l) => (
            <button
              type="button"
              key={l.code}
              className={
                "ms-chip " + (searchLanguages.includes(l.code) ? "active" : "")
              }
              onClick={() => toggleLang(l.code)}
            >
              {getLangName(code, l.code)}
            </button>
          ))}
        </div>
      </div>

      {!compact && (
        <div className="example-prompts">
          {boot.example_prompts.map((p, i) => (
            <button
              type="button"
              key={i}
              className="example-prompt"
              onClick={() => !busy && onSend(p.text)}
            >
              {p.icon} {p.text}
            </button>
          ))}
        </div>
      )}

      <hr className="hr-glow" />
    </div>
  );
}
