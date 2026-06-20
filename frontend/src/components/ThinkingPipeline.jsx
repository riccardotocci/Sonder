import { useEffect, useState } from "react";
import { useT, getThinkingSteps } from "../i18n.jsx";

// While a request is in flight we can't know which backend step is running
// (the chat call is a single blocking request), so we walk through a set of
// playful, step-themed messages on a timer to make the wait feel alive and
// give the impression of progress. We advance forward and hold on the last
// ("almost there") message instead of looping, so it never feels like it
// restarted from scratch.
export function RotatingThinking() {
  const { t, code } = useT();
  const steps = getThinkingSteps(code);
  const [i, setI] = useState(0);

  useEffect(() => {
    setI(0);
    if (steps.length <= 1) return undefined;
    const id = setInterval(() => {
      setI((prev) => (prev < steps.length - 1 ? prev + 1 : prev));
    }, 2600);
    return () => clearInterval(id);
  }, [code]); // eslint-disable-line react-hooks/exhaustive-deps

  const label = steps.length ? steps[Math.min(i, steps.length - 1)] : t("thinking");
  return (
    <div className="thinking">
      <span className="spinner" /> {label}
    </div>
  );
}

export function LlmLog({ log, open = false }) {
  const { t } = useT();
  if (!log || !log.length) return null;
  return (
    <details className="expander" style={{ marginTop: ".6rem" }} open={open}>
      <summary>🔎 {t("thinkingPipeline")}</summary>
      <div style={{ marginTop: ".5rem" }}>
        {log.map((entry, i) => (
          <div key={i} style={{ marginBottom: ".5rem" }}>
            <div
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                color: "#22d3ee",
                fontSize: ".75rem",
                textTransform: "uppercase",
                letterSpacing: ".1em",
              }}
            >
              {entry.title || entry.step || ""}
            </div>
            <div
              style={{
                whiteSpace: "pre-wrap",
                color: "#a8a3c0",
                fontSize: ".85rem",
              }}
            >
              {entry.detail || entry.body || entry.text || ""}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

export default function ThinkingPipeline({ messages, busy }) {
  const logs = messages.filter(
    (m) => m.role === "assistant" && m.llm_log && m.llm_log.length
  );

  return (
    <div className="messages">
      {logs.map((m, i) => (
        <LlmLog key={i} log={m.llm_log} open />
      ))}
      {busy && <RotatingThinking />}
    </div>
  );
}
