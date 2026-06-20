import { useEffect, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, GeoJSON, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { useT } from "../i18n.jsx";
import { translateLabel } from "../moodLabels.js";

const PALETTE = ["#ff2d78", "#f97316", "#22d3ee", "#facc15", "#c2410c", "#34d399"];
// Tavolozza piu' ampia per colorare gli STATI: ogni paese d'origine distinto riceve
// un colore stabile, cosi' la mappa e la legenda condividono lo stesso codice colore.
const COUNTRY_PALETTE = [
  "#ff2d78", "#22d3ee", "#facc15", "#34d399", "#f97316", "#a78bfa",
  "#60a5fa", "#f472b6", "#4ade80", "#fb7185", "#38bdf8", "#fbbf24",
];

// Chiave di raggruppamento per paese: l'ISO2 e' la piu' affidabile (combacia col
// GeoJSON), con fallback sull'etichetta leggibile dell'origine.
function countryKey(t) {
  return (t.origin_code || t.origin || "").trim().toUpperCase();
}

function GeographyMap({ tracks }) {
  const { t } = useT();
  // Il GeoJSON dei confini (Natural Earth, slim) viene caricato pigramente solo qui:
  // e' ~170KB e serve unicamente a riempire di colore lo stato d'origine.
  const [world, setWorld] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch("/world-countries.geojson")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => alive && setWorld(d))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const located = tracks.filter((t) => t.lat != null && t.lng != null);

  if (!located.length) {
    return (
      <p style={{ color: "#8f8aa8", fontSize: ".85rem" }}>
        {t("geoUnavailable")}
      </p>
    );
  }

  // Un colore per paese distinto (ordine di prima comparsa), condiviso da mappa,
  // poligoni e legenda. Tutte le canzoni dello stesso stato hanno lo stesso colore.
  const colorByCountry = {};
  located.forEach((tr) => {
    const k = countryKey(tr);
    if (k && !(k in colorByCountry)) {
      colorByCountry[k] = COUNTRY_PALETTE[
        Object.keys(colorByCountry).length % COUNTRY_PALETTE.length
      ];
    }
  });

  const geo = located.map((tr) => ({
    lat: tr.lat,
    lng: tr.lng,
    title: tr.title,
    artist: tr.artist,
    origin: tr.origin || "",
    key: countryKey(tr),
    color: colorByCountry[countryKey(tr)] || PALETTE[0],
  }));

  const distinctCountries = Object.keys(colorByCountry).length;

  // Stile dei poligoni: lo stato d'origine viene riempito col proprio colore, gli
  // altri restano quasi invisibili per non disturbare la lettura.
  const featureCountry = (f) =>
    (f?.properties?.iso || "").trim().toUpperCase();
  const styleCountry = (f) => {
    const color = colorByCountry[featureCountry(f)];
    if (color) {
      return { color, weight: 1, fillColor: color, fillOpacity: 0.45 };
    }
    return { color: "#1b1b2b", weight: 0.4, fillColor: "#11111c", fillOpacity: 0.15 };
  };

  return (
    <div>
      <div className="kpi-grid" style={{ marginTop: ".2rem" }}>
        <div className="kpi" style={{ "--kpi-accent": PALETTE[2] }}>
          <div className="kpi-label">{t("located")}</div>
          <div className="kpi-value">{geo.length}</div>
          <div className="kpi-sub">{t("artistOriginsMapped")}</div>
        </div>
        <div className="kpi" style={{ "--kpi-accent": PALETTE[1] }}>
          <div className="kpi-label">{t("places")}</div>
          <div className="kpi-value">{distinctCountries || geo.length}</div>
          <div className="kpi-sub">{t("distinctOrigins")}</div>
        </div>
      </div>

      <div className="geo-wrap">
        <div className="geo-map">
          <MapContainer
            center={[20, 0]}
            zoom={1}
            style={{ height: "100%", width: "100%", background: "#07070f" }}
            scrollWheelZoom={false}
          >
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              attribution='&copy; OpenStreetMap &copy; CARTO'
            />
            {world && (
              <GeoJSON
                key={Object.keys(colorByCountry).join(",")}
                data={world}
                style={styleCountry}
              />
            )}
            {geo.map((g, i) => (
              <CircleMarker
                key={i}
                center={[g.lat, g.lng]}
                radius={5}
                pathOptions={{
                  color: "#0b0b17",
                  weight: 2,
                  fillColor: g.color,
                  fillOpacity: 0.95,
                }}
              >
                <Tooltip>
                  {g.title} — {g.artist}
                  {g.origin ? ` · ${g.origin}` : ""}
                </Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>

        <div className="geo-legend">
          {geo.map((g, i) => (
            <div className="geo-legend-item" key={i}>
              <span className="geo-dot" style={{ color: g.color, background: g.color }} />
              <div className="geo-meta">
                <div className="geo-title">{g.title}</div>
                <div className="geo-origin">
                  {g.origin ? `📍 ${g.origin}` : g.artist}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <p style={{ color: "#8f8aa8", fontSize: ".8rem", marginTop: ".5rem" }}>
        {t("geoCaption")}
      </p>
    </div>
  );
}

function TrackDetails({ tracks }) {
  const { t } = useT();
  if (!tracks.length) {
    return (
      <p style={{ color: "#8f8aa8", fontSize: ".85rem" }}>
        {t("noTracksDetails")}
      </p>
    );
  }
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))",
        gap: 14,
      }}
    >
      {tracks.map((t, i) => {
        const color = PALETTE[i % PALETTE.length];
        return (
          <div
            className="track-card"
            key={i}
            style={{ borderTop: `4px solid ${color}` }}
          >
            <div
              style={{
                width: "100%",
                height: 130,
                borderRadius: 10,
                marginBottom: 8,
                overflow: "hidden",
                border: "1px solid rgba(255,255,255,.08)",
                background: t.image ? "transparent" : "rgba(255,255,255,.04)",
                flexShrink: 0,
              }}
            >
              {t.image && (
                <img
                  src={t.image}
                  alt=""
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    display: "block",
                  }}
                />
              )}
            </div>
            <b>
              {i + 1}. {t.title}
            </b>
            <br />
            <span>{t.artist}</span>
            {/* Riga origine sempre presente: se manca la citta' lo spazio resta
                riservato cosi' le card mantengono lo stesso allineamento. */}
            <div
              style={{
                color: "#8f8aa8",
                fontSize: ".85rem",
                minHeight: "1.2em",
              }}
            >
              {t.origin ? `📍 ${t.origin}` : "\u00A0"}
            </div>
            {t.mood ? (
              <div style={{ marginTop: 6 }}>
                <span
                  className="pill"
                  style={{
                    background: `${color}1f`,
                    border: `1px solid ${color}`,
                    color,
                  }}
                >
                  {t.mood}
                </span>
              </div>
            ) : null}
            {t.reason ? (
              <div
                style={{ color: "#c9c5dd", fontSize: ".9rem", marginTop: 6 }}
              >
                {t.reason}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function EnergyMoodChart({ tracks }) {
  const { t } = useT();
  const points = tracks
    .map((tr, i) => ({ ...tr, _i: i }))
    .filter(
      (tr) =>
        typeof tr.valence === "number" &&
        Number.isFinite(tr.valence) &&
        typeof tr.energy === "number" &&
        Number.isFinite(tr.energy)
    );

  if (!points.length) {
    return (
      <p style={{ color: "#8f8aa8", fontSize: ".85rem" }}>
        {t("energyMoodEmpty")}
      </p>
    );
  }

  const W = 460;
  const H = 360;
  const pad = 44;
  const plotW = W - pad * 2;
  const plotH = H - pad * 2;
  const xPos = (v) => pad + Math.min(Math.max(v, 0), 1) * plotW;
  const yPos = (e) => pad + (1 - Math.min(Math.max(e, 0), 1)) * plotH;
  const gridSteps = [0, 0.25, 0.5, 0.75, 1];
  const grid = "rgba(255,255,255,.08)";
  const axis = "rgba(255,255,255,.22)";
  const label = "#8f8aa8";

  // Tabella delle caratteristiche audio: ogni colonna e' una feature, ogni
  // cella e' colorata con intensita' proporzionale al valore (heatmap).
  const pct = (v) => `${Math.round(v * 100)}%`;
  const FEATURES = [
    { key: "valence", label: t("featValence"), fmt: pct },
    { key: "energy", label: t("featEnergy"), fmt: pct },
    { key: "danceability", label: t("featDance"), fmt: pct },
    { key: "acousticness", label: t("featAcoustic"), fmt: pct },
    { key: "instrumentalness", label: t("featInstr"), fmt: pct },
    { key: "liveness", label: t("featLive"), fmt: pct },
    { key: "speechiness", label: t("featSpeech"), fmt: pct },
    { key: "tempo", label: `${t("featTempo")} (BPM)`, fmt: (v) => `${Math.round(v)}`, normalize: true },
    { key: "loudness", label: `${t("featLoud")} (dB)`, fmt: (v) => v.toFixed(1), normalize: true },
  ];

  const featVal = (tr, key) => {
    const af = tr.audio_features || {};
    const v = af[key] != null ? af[key] : tr[key];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };

  // Per le feature non normalizzate (0..1) l'intensita' e' il valore stesso;
  // per tempo/volume si normalizza min-max sui brani mostrati.
  const ranges = {};
  FEATURES.forEach((f) => {
    if (!f.normalize) return;
    const vals = points.map((tr) => featVal(tr, f.key)).filter((v) => v != null);
    ranges[f.key] = vals.length ? [Math.min(...vals), Math.max(...vals)] : [0, 1];
  });

  const intensity = (f, v) => {
    if (v == null) return 0;
    if (!f.normalize) return Math.min(Math.max(v, 0), 1);
    const [mn, mx] = ranges[f.key];
    if (mx === mn) return 0.5;
    return Math.min(Math.max((v - mn) / (mx - mn), 0), 1);
  };

  const heat = (it) => {
    const cool = [34, 211, 238];
    const hot = [255, 45, 120];
    const r = Math.round(cool[0] + (hot[0] - cool[0]) * it);
    const g = Math.round(cool[1] + (hot[1] - cool[1]) * it);
    const b = Math.round(cool[2] + (hot[2] - cool[2]) * it);
    return `rgba(${r},${g},${b},${0.12 + 0.5 * it})`;
  };

  return (
    <div>
      <div style={{ display: "flex", gap: "1.5rem", alignItems: "flex-start" }}>
      <div style={{ overflowX: "auto", flexShrink: 0 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ maxWidth: W, display: "block" }}
        role="img"
        aria-label={t("energyMood")}
      >
        {gridSteps.map((g, i) => (
          <g key={i}>
            <line x1={xPos(g)} y1={pad} x2={xPos(g)} y2={H - pad} stroke={grid} />
            <line x1={pad} y1={yPos(g)} x2={W - pad} y2={yPos(g)} stroke={grid} />
          </g>
        ))}
        {/* center cross (neutral mood / mid energy) */}
        <line x1={xPos(0.5)} y1={pad} x2={xPos(0.5)} y2={H - pad} stroke={axis} strokeDasharray="4 4" />
        <line x1={pad} y1={yPos(0.5)} x2={W - pad} y2={yPos(0.5)} stroke={axis} strokeDasharray="4 4" />
        {/* frame */}
        <rect x={pad} y={pad} width={plotW} height={plotH} fill="none" stroke={axis} />

        {/* axis names */}
        <text x={W / 2} y={H - 8} textAnchor="middle" fill={label} fontSize="12" fontWeight="600">
          {t("moodAxis")}
        </text>
        <text
          x={14}
          y={H / 2}
          textAnchor="middle"
          fill={label}
          fontSize="12"
          fontWeight="600"
          transform={`rotate(-90 14 ${H / 2})`}
        >
          {t("energyAxis")}
        </text>

        {/* corner labels */}
        <text x={pad} y={H - pad + 16} textAnchor="start" fill={label} fontSize="10">
          {t("sadLabel")}
        </text>
        <text x={W - pad} y={H - pad + 16} textAnchor="end" fill={label} fontSize="10">
          {t("happyLabel")}
        </text>
        <text x={pad - 6} y={H - pad} textAnchor="end" fill={label} fontSize="10">
          {t("calmLabel")}
        </text>
        <text x={pad - 6} y={pad + 8} textAnchor="end" fill={label} fontSize="10">
          {t("energeticLabel")}
        </text>

        {/* points */}
        {points.map((tr) => {
          const color = PALETTE[tr._i % PALETTE.length];
          const cx = xPos(tr.valence);
          const cy = yPos(tr.energy);
          return (
            <g key={tr._i}>
              <circle cx={cx} cy={cy} r="7" fill={color} fillOpacity="0.85" stroke="#0b0a14" strokeWidth="1.5">
                <title>
                  {`${tr._i + 1}. ${tr.title} — ${tr.artist}`}
                  {tr.mood ? ` · ${tr.mood}` : ""}
                  {`\n${t("moodAxis")}: ${Math.round(tr.valence * 100)} · ${t("energyAxis")}: ${Math.round(tr.energy * 100)}`}
                </title>
              </circle>
              <text x={cx + 10} y={cy + 4} fill="#c9c5dd" fontSize="10">
                {tr._i + 1}
              </text>
            </g>
          );
        })}
      </svg>
      </div>

      {/* Legenda a destra del grafico */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="feat-legend-head">{t("featuresLegend")}</div>
        <div className="geo-legend" style={{ marginTop: ".4rem" }}>
          {points.map((tr) => {
            const color = PALETTE[tr._i % PALETTE.length];
            return (
              <div className="geo-legend-item" key={tr._i}>
                <span className="geo-dot" style={{ color, background: color }} />
                <div className="geo-meta">
                  <div className="geo-title">
                    {tr._i + 1}. {tr.title}
                  </div>
                  <div className="geo-origin">{tr.mood || tr.artist}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      </div>{/* fine riga flex grafico + legenda */}

      <div className="feat-legend-head" style={{ marginTop: "1rem" }}>
        {t("featuresTable")}
      </div>
      <div style={{ overflowX: "auto", marginTop: ".4rem" }}>
        <table className="feat-table">
          <thead>
            <tr>
              <th>#</th>
              <th className="feat-track-col">{t("featTrack")}</th>
              {FEATURES.map((f) => (
                <th key={f.key}>{f.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.map((tr) => {
              const color = PALETTE[tr._i % PALETTE.length];
              return (
                <tr key={tr._i}>
                  <td className="feat-num">
                    <span className="feat-dot" style={{ background: color }} />
                    {tr._i + 1}
                  </td>
                  <td className="feat-track-col">
                    <div className="feat-title">{tr.title}</div>
                    <div className="feat-artist">{tr.artist}</div>
                  </td>
                  {FEATURES.map((f) => {
                    const v = featVal(tr, f.key);
                    return (
                      <td
                        key={f.key}
                        style={{
                          background: v == null ? "transparent" : heat(intensity(f, v)),
                        }}
                      >
                        {v == null ? "—" : f.fmt(v)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p style={{ color: "#8f8aa8", fontSize: ".8rem", marginTop: ".5rem" }}>
        {t("featuresNote")}
      </p>
    </div>
  );
}

function MoodsTable({ tracks }) {
  const { t, code } = useT();
  const rows = tracks
    .map((tr, i) => ({ ...tr, _i: i }))
    .filter((tr) => Array.isArray(tr.mx_moods) && tr.mx_moods.length > 0);
  // Si nasconde quando nessuna traccia ha mood testuali (coerente con gli altri grafici).
  if (!rows.length) return null;

  // Mood unici su tutti i brani, in ordine di prima comparsa (prima riga della matrice).
  const allMoods = [];
  const seenMoods = new Set();
  rows.forEach((tr) => {
    tr.mx_moods.forEach((m) => {
      const key = String(m).toLowerCase();
      if (!seenMoods.has(key)) {
        seenMoods.add(key);
        allMoods.push(m);
      }
    });
  });

  // Etichetta brano riutilizzata nella prima colonna di entrambe le tabelle.
  const trackCell = (tr, color) => (
    <td className="feat-track-col">
      <div className="feat-title">
        <span className="feat-dot" style={{ background: color }} />
        {tr.title}
      </div>
      <div className="feat-artist">
        {tr.artist}
        {tr.genre ? ` · ${tr.genre}` : ""}
      </div>
    </td>
  );

  return (
    <>
      <div className="section-head" style={{ marginTop: "1.4rem" }}>
        <h3>🎭 {t("moodsTitle")}</h3>
        <span className="section-note">{t("moodsNote")}</span>
      </div>

      {/* Matrice brano × mood: ogni cella all'incrocio brano/mood e' colorata col
          colore del brano quando quel mood e' presente nei testi. */}
      <div style={{ overflowX: "auto", marginTop: ".4rem" }}>
        <table className="feat-table">
          <thead>
            <tr>
              <th className="feat-track-col">{t("featTrack")}</th>
              {allMoods.map((m, j) => (
                <th key={j}>{translateLabel(m, code)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((tr) => {
              const color = PALETTE[tr._i % PALETTE.length];
              const moodSet = new Set(
                tr.mx_moods.map((m) => String(m).toLowerCase())
              );
              return (
                <tr key={tr._i}>
                  {trackCell(tr, color)}
                  {allMoods.map((m, j) => {
                    const on = moodSet.has(String(m).toLowerCase());
                    return (
                      <td
                        key={j}
                        title={on ? translateLabel(m, code) : undefined}
                        style={{
                          background: on ? color : "transparent",
                          border: on
                            ? `1px solid ${color}`
                            : "1px solid rgba(255,255,255,.05)",
                          color: "#0b0b17",
                          fontWeight: 700,
                        }}
                      >
                        {on ? "●" : ""}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Seconda tabella: brano -> temi correlati. */}
      <div style={{ overflowX: "auto", marginTop: "1rem" }}>
        <table className="feat-table">
          <thead>
            <tr>
              <th className="feat-track-col">{t("featTrack")}</th>
              <th>{t("themesCol")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((tr) => {
              const color = PALETTE[tr._i % PALETTE.length];
              return (
                <tr key={tr._i}>
                  {trackCell(tr, color)}
                  <td
                    style={{
                      color: "#c9c5dd",
                      fontSize: ".85rem",
                      textAlign: "left",
                      whiteSpace: "normal",
                    }}
                  >
                    {Array.isArray(tr.mx_themes) && tr.mx_themes.length
                      ? tr.mx_themes.map((th) => translateLabel(th, code)).join(", ")
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p style={{ color: "#8f8aa8", fontSize: ".8rem", marginTop: ".5rem" }}>
        {t("moodsTableNote")}
      </p>
    </>
  );
}

export default function StudioSections({ studio, token }) {
  const { t } = useT();
  const tracks = studio.tracks || [];
  const hasEnergyMood = tracks.some(
    (tr) =>
      typeof tr.valence === "number" &&
      Number.isFinite(tr.valence) &&
      typeof tr.energy === "number" &&
      Number.isFinite(tr.energy)
  );
  return (
    <div>
      <hr className="hr-glow" />
      <div className="section-head">
        <h3>🗺️ {t("playlistGeography")}</h3>
        <span className="section-note">{t("artistOrigins")}</span>
      </div>
      <GeographyMap tracks={tracks} />

      <h3 style={{ marginTop: "1.4rem" }}>🎚️ {t("trackByTrack")}</h3>
      <TrackDetails tracks={tracks} />

      <div className="section-head" style={{ marginTop: "1.4rem" }}>
        <h3>🎯 {t("energyMood")}</h3>
        <span className="section-note">{t("energyMoodNote")}</span>
      </div>
      {hasEnergyMood ? (
        <EnergyMoodChart tracks={tracks} />
      ) : (
        <p style={{ color: "#8f8aa8", fontSize: ".85rem" }}>
          {token ? t("energyMoodEmpty") : t("addSpotifyForInfo")}
        </p>
      )}

      <MoodsTable tracks={tracks} />
    </div>
  );
}
