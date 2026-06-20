import { useEffect, useState } from "react";
import { useT } from "../i18n.jsx";

const API_BASE = "";

// Nomi leggibili dei provider Songstats (chiave = source minuscola).
const PROVIDER_NAMES = {
  spotify: "Spotify",
  apple_music: "Apple Music",
  youtube: "YouTube",
  tiktok: "TikTok",
  soundcloud: "SoundCloud",
  deezer: "Deezer",
  shazam: "Shazam",
  tidal: "Tidal",
  amazon: "Amazon",
  itunes: "iTunes",
  beatport: "Beatport",
  pandora: "Pandora",
  napster: "Napster",
};

function prettyProvider(p) {
  const key = String(p).toLowerCase();
  if (PROVIDER_NAMES[key]) return PROVIDER_NAMES[key];
  return String(p)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function humanNumber(value) {
  let v = Number(value);
  if (!Number.isFinite(v)) return "0";
  const units = [
    ["B", 1e9],
    ["M", 1e6],
    ["K", 1e3],
  ];
  for (const [unit, threshold] of units) {
    if (Math.abs(v) >= threshold) {
      return (v / threshold).toFixed(1).replace(".0", "") + unit;
    }
  }
  return String(Math.trunc(v));
}

// Valore grezzo di una etichetta "headline" per un brano (null se assente).
function rawValue(r, rawLabel) {
  const list = Array.isArray(r.headline) ? r.headline : [];
  const found = list.find((p) => p && p[0] === rawLabel);
  if (!found) return null;
  const v = Number(found[1]);
  return Number.isFinite(v) ? v : null;
}

// Tabella heatmap riusabile: righe = brani, colonne = caratteristiche.
// `columns` = [{ key, label, value: (row) => number|null }].
function HeatTable({ rows, columns, firstColLabel }) {
  // Massimo per colonna: ogni metrica ha scala diversa, quindi si normalizza
  // colonna per colonna per l'intensita' della heatmap.
  const colMax = {};
  columns.forEach((col) => {
    let mx = 0;
    rows.forEach((r) => {
      const v = col.value(r);
      if (Number.isFinite(v) && v > mx) mx = v;
    });
    colMax[col.key] = mx || 1;
  });

  return (
    <div style={{ overflowX: "auto", marginTop: ".4rem" }}>
      <table className="feat-table">
        <thead>
          <tr>
            <th className="feat-track-col">{firstColLabel}</th>
            {columns.map((col) => (
              <th key={col.key}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="feat-track-col feat-title" title={r.label}>
                {r.label}
              </td>
              {columns.map((col) => {
                const v = col.value(r);
                const has = v !== null && Number.isFinite(v);
                const intensity = has
                  ? Math.max(v / colMax[col.key], 0.04)
                  : 0;
                return (
                  <td
                    key={col.key}
                    className="feat-num"
                    title={has ? `${col.label}: ${humanNumber(v)}` : undefined}
                    style={{
                      background: has
                        ? `rgba(255,45,120,${(0.1 + intensity * 0.5).toFixed(3)})`
                        : "transparent",
                    }}
                  >
                    {has ? humanNumber(v) : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Songstats({ studio, token }) {
  const { t } = useT();
  const tracks = studio.tracks || [];
  const [state, setState] = useState({ loading: true, data: null, error: "" });

  useEffect(() => {
    if (!tracks.length) {
      setState({ loading: false, data: { available: true, rows: [] }, error: "" });
      return;
    }
    let cancelled = false;
    setState({ loading: true, data: null, error: "" });
    fetch(API_BASE + "/api/songstats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tracks, spotify_token: token || "" }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setState({ loading: false, data, error: "" });
      })
      .catch((e) => {
        if (!cancelled)
          setState({ loading: false, data: null, error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [studio, token]);

  if (!tracks.length) return null;

  const { loading, data, error } = state;

  let body;
  if (loading) {
    body = (
      <div className="thinking">
        <span className="spinner" /> {t("loadingSongstats")}
      </div>
    );
  } else if (error) {
    body = <p style={{ color: "#8f8aa8", fontSize: ".85rem" }}>{error}</p>;
  } else if (!data.available) {
    const msg =
      data.reason === "no_key" ? t("songstatsNoKey") : t("addSpotifyForInfo");
    body = <p style={{ color: "#8f8aa8", fontSize: ".85rem" }}>{msg}</p>;
  } else if (!data.rows.length) {
    body = (
      <p style={{ color: "#8f8aa8", fontSize: ".85rem" }}>
        {t("songstatsNoData")}
      </p>
    );
  } else {
    const rows = data.rows;

    // Le etichette "headline" hanno forma "Metrica · provider" (oppure solo
    // "Metrica" quando esiste una sola fonte). Si raggruppano per provider:
    // ogni provider -> Map(metrica -> { count, sum }). Le metriche senza
    // suffisso finiscono nella tabella generale insieme alle riproduzioni totali.
    const providerMeta = new Map(); // provider -> Map(metric -> {count,sum})
    const generalMeta = new Map(); // metric senza provider -> {count,sum}

    const bump = (bucket, metric, v) => {
      const m = bucket.get(metric) || { count: 0, sum: 0 };
      m.count += 1;
      m.sum += v;
      bucket.set(metric, m);
    };

    rows.forEach((r) => {
      (Array.isArray(r.headline) ? r.headline : []).forEach((pair) => {
        const rawLabel = pair && pair[0];
        const v = Number(pair && pair[1]);
        if (!rawLabel || !Number.isFinite(v)) return;
        const idx = rawLabel.indexOf(" · ");
        if (idx >= 0) {
          const metric = rawLabel.slice(0, idx);
          const provider = rawLabel.slice(idx + 3);
          if (!providerMeta.has(provider)) providerMeta.set(provider, new Map());
          bump(providerMeta.get(provider), metric, v);
        } else {
          bump(generalMeta, rawLabel, v);
        }
      });
    });

    const byCoverageThenMag = (a, b) =>
      b[1].count - a[1].count || b[1].sum - a[1].sum;

    // Tabella generale: riproduzioni totali + eventuali metriche senza provider.
    const generalColumns = [
      {
        key: "__streams__",
        label: t("totalStreams"),
        value: (r) => Number(r.total_streams) || 0,
      },
      ...[...generalMeta.entries()]
        .sort(byCoverageThenMag)
        .map(([metric]) => ({
          key: metric,
          label: metric,
          value: (r) => rawValue(r, metric),
        })),
    ];

    // Provider ordinati per grandezza complessiva (somma di tutte le metriche),
    // cosi' i provider piu' rilevanti compaiono per primi.
    const providerTables = [...providerMeta.entries()]
      .map(([provider, mmap]) => {
        const total = [...mmap.values()].reduce((s, m) => s + m.sum, 0);
        const columns = [...mmap.entries()]
          .sort(byCoverageThenMag)
          .map(([metric]) => ({
            key: metric,
            label: metric,
            value: (r) => rawValue(r, `${metric} · ${provider}`),
          }));
        return { provider, total, columns };
      })
      .sort((a, b) => b.total - a.total);

    body = (
      <>
        <div className="feat-legend-head">{t("songstatsGeneral")}</div>
        <HeatTable
          rows={rows}
          columns={generalColumns}
          firstColLabel={t("featTrack")}
        />
        {providerTables.map((pt) => (
          <div key={pt.provider}>
            <div className="feat-legend-head">{prettyProvider(pt.provider)}</div>
            <HeatTable
              rows={rows}
              columns={pt.columns}
              firstColLabel={t("featTrack")}
            />
          </div>
        ))}
      </>
    );
  }

  return (
    <div>
      <hr className="hr-glow" />
      <div className="section-head">
        <h3>📊 {t("streamingStatsHeading")}</h3>
        {data && data.available && (data.rows || []).length ? (
          <span className="section-note">{t("realtimeReach")}</span>
        ) : null}
      </div>
      {body}
    </div>
  );
}
