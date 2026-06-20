import { useState } from "react";
import { beginSpotifyLogin } from "../spotify.js";
import { useT } from "../i18n.jsx";

function StatusDots({ status }) {
  return (
    <div className="status-row">
      {Object.entries(status).map(([name, on]) => (
        <span key={name} className={"status-dot " + (on ? "on" : "off")}>
          <span className="dot" />
          {name}
        </span>
      ))}
    </div>
  );
}

export default function Sidebar({
  boot,
  spotify,
  onSpotifySession,
  llmModel,
  setLlmModel,
  onNewChat,
  token,
  onCollapse,
  onOpenAbout,
}) {
  const { t } = useT();
  const [stayLoggedIn, setStayLoggedIn] = useState(true);
  const [modelOpen, setModelOpen] = useState(false);
  const sp = boot.spotify;

  const handleLogin = async () => {
    try {
      await beginSpotifyLogin(sp, stayLoggedIn);
    } catch (e) {
      console.warn("login failed", e);
    }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <img src="/static/logo_text.png" alt="Sonder" />
        </div>
        <button
          className="sidebar-toggle"
          onClick={onCollapse}
          title={t("hidePanel")}
          aria-label={t("hidePanel")}
        >
          ⟨
        </button>
      </div>

      <button className="btn btn-block" onClick={onNewChat}>
        ✨ {t("newChat")}
      </button>

      <hr />

      <div>
        <h3>🎧 {t("spotifyHeading")}</h3>
        {token ? (
          <>
            <div
              style={{
                fontSize: ".82rem",
                color: "#22d3ee",
                marginBottom: ".5rem",
              }}
            >
              ✓ {t("connected")}
            </div>
            <button
              className="btn btn-block"
              onClick={() => onSpotifySession(null, false)}
            >
              {t("logOut")}
            </button>
          </>
        ) : (
          <>
            {sp.pkce_ready ? (
              <>
                <button className="btn btn-block" onClick={handleLogin}>
                  {t("logInSpotify")}
                </button>
                <label className="checkbox-row" style={{ marginTop: ".6rem" }}>
                  <input
                    type="checkbox"
                    checked={stayLoggedIn}
                    onChange={(e) => setStayLoggedIn(e.target.checked)}
                  />
                  {t("stayLoggedIn")}
                </label>
              </>
            ) : (
              <div className="sidebar-note">{t("setClientIdLogin")}</div>
            )}
          </>
        )}
      </div>

      <hr />

      <details
        className="expander"
        open={modelOpen}
        onToggle={(e) => setModelOpen(e.target.open)}
      >
        <summary>🧠 {t("thinkingModelHeading")}</summary>
        <div style={{ marginTop: ".6rem" }}>
          <label className="field-label">{t("llmModelLabel")}</label>
          <select
            className="text-input"
            value={llmModel}
            onChange={(e) => setLlmModel(e.target.value)}
          >
            {boot.llm_models.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
      </details>

      <hr />

      <div>
        <p style={{ fontSize: ".75rem", opacity: 0.7, margin: "0 0 .35rem" }}>
          powered by
        </p>
        <StatusDots status={boot.status} />
      </div>

      <div style={{ flex: 1 }} />

      <button
        className="about-banner"
        onClick={onOpenAbout}
        aria-label={t("aboutBanner")}
      >
        <span className="about-banner-glyph">✦</span>
        <span className="about-banner-text">
          <span className="about-banner-title">{t("aboutBanner")}</span>
          <span className="about-banner-sub">{t("aboutBannerSub")}</span>
        </span>
        <span className="about-banner-arrow">→</span>
      </button>
    </aside>
  );
}
