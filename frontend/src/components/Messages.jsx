import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { spotifyCreatePlaylist } from "../api.js";
import { LlmLog, RotatingThinking } from "./ThinkingPipeline.jsx";
import { useT } from "../i18n.jsx";

function Markdown({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ""}</ReactMarkdown>
  );
}

function PlaylistButton({ tracks, token, spotifyReady }) {
  const { t } = useT();
  const [status, setStatus] = useState("idle"); // idle | busy | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  if (!spotifyReady) {
    return (
      <p style={{ marginTop: ".6rem", fontSize: ".85rem", color: "#8f8aa8" }}>
        {t("setClientIdPlaylist")}
      </p>
    );
  }
  if (!token) {
    return (
      <p style={{ marginTop: ".6rem", fontSize: ".85rem", color: "#8f8aa8" }}>
        {t("loginToCreatePlaylist")}
      </p>
    );
  }

  const onCreate = async () => {
    setStatus("busy");
    setError("");
    try {
      const res = await spotifyCreatePlaylist(token, tracks, "Conversation");
      if (res.ok) {
        setResult(res);
        setStatus("done");
      } else {
        setError(res.error || t("couldNotCreatePlaylist"));
        setStatus("error");
      }
    } catch (e) {
      setError(String(e.message || e));
      setStatus("error");
    }
  };

  return (
    <div style={{ marginTop: ".6rem" }}>
      {status !== "done" && (
        <button
          className="btn-primary"
          style={{ width: "100%" }}
          onClick={onCreate}
          disabled={status === "busy"}
        >
          {status === "busy" ? t("creating") : t("createPlaylist")}
        </button>
      )}
      {status === "error" && (
        <p style={{ color: "#ff6b6b", marginTop: ".5rem", fontSize: ".85rem" }}>
          {error}
        </p>
      )}
      {status === "done" && result && (
        <div style={{ marginTop: ".5rem" }}>
          <p style={{ color: "#22d3ee", fontSize: ".9rem" }}>
            {t("playlistCreated", {
              name: result.name,
              count: result.track_count,
            })}
          </p>
          {result.embed_url && (
            <iframe
              title="Spotify playlist"
              src={result.embed_url}
              width="100%"
              height="380"
              frameBorder="0"
              allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
              loading="lazy"
              style={{ borderRadius: "12px", border: "none" }}
            />
          )}
          {result.url && (
            <p style={{ marginTop: ".4rem", fontSize: ".85rem" }}>
              <a href={result.url} target="_blank" rel="noreferrer">
                {t("openOnSpotify")}
              </a>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function TrackCards({ tracks, token, spotifyReady }) {
  const { t } = useT();
  if (!tracks || !tracks.length) return null;
  return (
    <>
      <hr className="hr-glow" />
      <h5 style={{ margin: "0 0 .6rem 0" }}>🎧 {t("musixmatchTracks")}</h5>
      {tracks.map((t, i) => (
        <div className="track-card" key={i}>
          <b>
            {i + 1}. {t.title}
          </b>
          <br />
          <span>{t.artist}</span>
        </div>
      ))}
      <PlaylistButton tracks={tracks} token={token} spotifyReady={spotifyReady} />
    </>
  );
}

function Message({ msg, token, spotifyReady }) {
  const { t } = useT();
  const isAssistant = msg.role === "assistant";
  return (
    <div className={"msg " + (isAssistant ? "msg-assistant" : "msg-user")}>
      <div className="msg-avatar">{isAssistant ? "🎵" : "🧑"}</div>
      <div className="msg-body">
        <Markdown>{msg.content}</Markdown>
        <LlmLog log={msg.llm_log} />
        {msg.reasoning ? (
          <details className="expander" style={{ marginTop: ".6rem" }}>
            <summary>🧠 {t("modelReasoning")}</summary>
            <div style={{ marginTop: ".5rem" }}>
              <Markdown>{msg.reasoning}</Markdown>
            </div>
          </details>
        ) : null}
        <TrackCards
          tracks={msg.tracks}
          token={token}
          spotifyReady={spotifyReady}
        />
      </div>
    </div>
  );
}

export default function Messages({ messages, busy, token, spotifyReady }) {
  return (
    <div className="messages">
      {messages.map((m, i) => (
        <Message key={i} msg={m} token={token} spotifyReady={spotifyReady} />
      ))}
      {busy && (
        <div className="msg msg-assistant">
          <div className="msg-avatar">🎵</div>
          <div className="msg-body">
            <RotatingThinking />
          </div>
        </div>
      )}
    </div>
  );
}
