import { UI_LANGUAGES, useT } from "../i18n.jsx";

export default function LanguageSelector({ value, onChange }) {
  const { t } = useT();
  return (
    <div className="lang-selector" title={t("interfaceLanguage")}>
      <span className="lang-selector-globe" aria-hidden="true">
        🌐
      </span>
      <select
        aria-label={t("interfaceLanguage")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {UI_LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </div>
  );
}
