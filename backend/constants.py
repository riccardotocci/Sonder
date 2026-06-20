"""Sonder UI/orchestration constants, ported verbatim from the Streamlit app.

These are the language maps, greetings, refusals, example prompts and the neon
palette used by the original ``app.py``. They are reused by the FastAPI backend
(narration-language detection, translation codes) and surfaced to the React
frontend via the ``/api/bootstrap`` endpoint so the UI keeps 1:1 parity.
"""
from __future__ import annotations

import re
from typing import Any

# Lingua UI -> (nome per il prompt LLM, codice biografia TheAudioDB)
LANGUAGES: dict[str, tuple[str, str]] = {
    "Italiano": ("Italiano", "IT"),
    "English": ("English", "EN"),
    "Français": ("Français", "FR"),
    "Español": ("Español", "ES"),
    "Deutsch": ("Deutsch", "DE"),
    "Português": ("Português", "PT"),
    "Nederlands": ("Nederlands", "NL"),
    "Polski": ("Polski", "PL"),
    "Русский": ("Русский", "RU"),
    "日本語": ("日本語", "JP"),
    "中文": ("中文", "CN"),
    "한국어": ("한국어", "KR"),
    "العربية": ("العربية", "AR"),
}

# Lingua di narrazione -> codice BCP-47 per la sintesi vocale del browser.
TTS_LANG: dict[str, str] = {
    "Italiano": "it-IT",
    "English": "en-US",
    "Français": "fr-FR",
    "Español": "es-ES",
    "Deutsch": "de-DE",
    "Português": "pt-PT",
    "Nederlands": "nl-NL",
    "Polski": "pl-PL",
    "Русский": "ru-RU",
    "日本語": "ja-JP",
    "中文": "zh-CN",
    "한국어": "ko-KR",
    "العربية": "ar-SA",
}

MUSIXMATCH_TRANSLATION_LANG: dict[str, str] = {
    "Italiano": "it",
    "English": "en",
    "Français": "fr",
    "Español": "es",
    "Deutsch": "de",
    "Português": "pt",
    "Nederlands": "nl",
    "Polski": "pl",
    "Русский": "ru",
    "日本語": "ja",
    "中文": "zh",
    "한국어": "ko",
    "العربية": "ar",
}

MUSIXMATCH_TRANSLATION_LANG_BY_CODE: dict[str, str] = {
    "EN": "en", "IT": "it", "FR": "fr", "ES": "es", "DE": "de", "PT": "pt",
    "NL": "nl", "PL": "pl", "RU": "ru", "JP": "ja", "CN": "zh", "KR": "ko", "AR": "ar",
}


def musixmatch_translation_code(lang_name: str = "Auto", lang_code: str = "EN") -> str:
    return (
        MUSIXMATCH_TRANSLATION_LANG.get(lang_name)
        or MUSIXMATCH_TRANSLATION_LANG_BY_CODE.get(lang_code.upper(), "en")
    )


MUSIXMATCH_SUPPORTED_LANGS: set[str] = {
    "en", "it", "fr", "es", "de", "pt", "nl", "pl", "ru", "ja", "zh", "ko", "ar",
}


def _normalize_mxm_lang(code: str) -> str:
    raw = str(code or "").strip().lower().replace("_", "-")
    if not raw:
        return ""
    short = raw.split("-")[0]
    aliases = {
        "ita": "it", "eng": "en", "fra": "fr", "fre": "fr", "spa": "es",
        "ger": "de", "deu": "de", "por": "pt", "nld": "nl", "dut": "nl",
        "pol": "pl", "rus": "ru", "jpn": "ja", "jp": "ja", "zho": "zh",
        "chi": "zh", "cn": "zh", "kor": "ko", "kr": "ko", "ara": "ar",
    }
    short = aliases.get(short, short)
    return short if short in MUSIXMATCH_SUPPORTED_LANGS else ""


def _plan_translation_lang(
    plan: dict[str, Any], lang_name: str = "Auto", lang_code: str = "EN"
) -> str:
    narration = _normalize_mxm_lang(str((plan or {}).get("narration_lang", "")))
    if narration:
        return narration
    return musixmatch_translation_code(lang_name, lang_code)


# Reverse of LANGUAGES keyed by Musixmatch/ISO 639-1 code -> (nome prompt LLM, codice TheAudioDB).
ISO_TO_LANGUAGE: dict[str, tuple[str, str]] = {
    "it": ("Italiano", "IT"),
    "en": ("English", "EN"),
    "fr": ("Français", "FR"),
    "es": ("Español", "ES"),
    "de": ("Deutsch", "DE"),
    "pt": ("Português", "PT"),
    "nl": ("Nederlands", "NL"),
    "pl": ("Polski", "PL"),
    "ru": ("Русский", "RU"),
    "ja": ("日本語", "JP"),
    "zh": ("中文", "CN"),
    "ko": ("한국어", "KR"),
    "ar": ("العربية", "AR"),
}


def resolve_narration_lang(
    plan: dict[str, Any], lang_name: str = "Auto", lang_code: str = "EN"
) -> tuple[str, str, str]:
    """Single source of truth for the narration language.

    Returns ``(language_name, audiodb_code, musixmatch_code)`` so that every
    piece of generated text (response writer, studio narrations/summary) AND the
    Musixmatch *translated lyrics* are produced in the exact same language.

    **Auto mode is removed:** the output ALWAYS follows the selected UI language,
    even when the user writes in a different language. The router's
    ``narration_lang`` (detected from the user's message) is intentionally
    ignored. If no concrete UI language is given (legacy "Auto"/empty), fall back
    to English so the language is never the song's/source language.
    """
    if not lang_name or lang_name == "Auto":
        lang_name, lang_code = "English", "EN"
    return lang_name, (lang_code or "EN"), musixmatch_translation_code(lang_name, lang_code)


def _detect_narration_lang(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) < 3:
        return ""
    try:
        from langdetect import detect
    except Exception:
        return ""
    try:
        return _normalize_mxm_lang(detect(cleaned))
    except Exception:
        return ""


GREETINGS: dict[str, str] = {
    "Italiano": "Ciao, sono **Sonder**. Di cosa vuoi parlare oggi? ",
    "English": "Hi, I'm **Sonder**. What would you like to talk about? ",
    "Français": "Salut, je suis **Sonder**. De quoi veux-tu parler ? ",
    "Español": "Hola, soy **Sonder**. ¿De qué quieres hablar? ",
    "Deutsch": "Hallo, ich bin **Sonder**. Worüber möchtest du sprechen? ",
    "Português": "Olá, sou **Sonder**. Sobre o que queres falar? ",
    "Nederlands": "Hoi, ik ben **Sonder**. Waarover wil je praten? ",
    "Polski": "Cześć, jestem **Sonder**. O czym chcesz porozmawiać? ",
    "Русский": "Привет, я **Sonder**. О чём хочешь поговорить? ",
    "日本語": "こんにちは、**Sonder** です。何について話したいですか？ ",
    "中文": "你好，我是 **Sonder**。你想聊些什么？ ",
    "한국어": "안녕하세요, 저는 **Sonder** 입니다. 무엇에 대해 이야기하고 싶으신가요? ",
    "العربية": "مرحبًا، أنا **Sonder**. عن ماذا تريد أن نتحدث؟ ",
}

REFUSALS: dict[str, str] = {
    "Italiano": "*Questo non è il mio territorio.* Sono fatto di note, versi e ombre sonore — parlami di musica e ti seguirò ovunque. ",
    "English":  "*That's outside my domain.* I'm made of notes, lyrics and sonic shadows — bring me music and I'll follow you anywhere. ",
    "Français": "*Ce n'est pas mon domaine.* Je suis fait de notes, de paroles et d'ombres sonores — parle-moi de musique et je te suivrai partout. ",
    "Español":  "*Eso está fuera de mi territorio.* Estoy hecho de notas, letras y sombras sonoras — háblame de música y te seguiré a donde sea. ",
    "Deutsch":  "*Das liegt außerhalb meines Gebiets.* Ich bin aus Noten, Texten und klanglichen Schatten gemacht — sprich über Musik und ich folge dir überallhin. ",
    "Português":"*Isso está fora do meu território.* Sou feito de notas, letras e sombras sonoras — fala-me de música e te seguirei para onde quiseres. ",
    "Nederlands":"*Dit valt buiten mijn domein.* Ik ben gemaakt van noten, teksten en klanksschaduwen — praat met me over muziek en ik volg je overal. ",
    "Polski":   "*To poza moim terenem.* Jestem zbudowany z nut, tekstów i dźwiękowych cieni — porozmawiaj ze mną o muzyce, a pójdę za tobą wszędzie. ",
    "Русский":  "*Это не моя территория.* Я соткан из нот, слов и звуковых теней — говори со мной о музыке, и я последую за тобой куда угодно. ",
    "日本語":    "*それは私の領域外です。* 私は音符、歌詞、音の影から生まれました — 音楽について話せば、どこまでもついていきます。",
    "中文":     "*这超出了我的领域。* 我由音符、歌词和声音的阴影构成——跟我谈音乐，我会陪你走遍任何地方。",
    "한국어":   "*그건 제 영역 밖입니다.* 저는 음표, 가사, 음향의 그림자로 만들어졌습니다 — 음악에 대해 이야기하면 어디든 따라가겠습니다.",
    "العربية":  "*هذا خارج نطاق تخصصي.* أنا مصنوع من نوتات موسيقية وكلمات وظلال صوتية — تحدّث إليّ عن الموسيقى وسأتبعك أينما ذهبت.",
}

LLM_RETRY_MESSAGE = "Please retry."
LLM_RETRY_ERROR_HINTS = (
    "rate out of bandwidth", "rate out of widthband", "out of bandwidth",
    "widthband", "bandwidth", "rate limit", "rate limited",
    "too many requests", "429", "quota",
)

# Palette neon "studio tecnologico".
PALETTE = ["#ff2d78", "#f97316", "#22d3ee", "#facc15", "#c2410c", "#34d399"]

EXAMPLE_PROMPTS: dict[str, list[tuple[str, str]]] = {
    "Italiano": [
        ("🕊️", "Canzoni che parlano di libertà"),
        ("🌙", "Musica che tratta la solitudine"),
        ("✨", "Canzoni che parlano di speranza"),
        ("🚗", "Jazz per un viaggio notturno in macchina"),
        ("💔", "Canzoni emozionanti su cuori spezzati e perdite"),
        ("🎬", "Le colonne sonore più cinematografiche di sempre"),
    ],
    "English": [
        ("🕊️", "Songs about freedom"),
        ("🌙", "Music about solitude"),
        ("✨", "Songs about hope"),
        ("🚗", "Jazz for a late-night drive"),
        ("💔", "Emotional songs about heartbreak and loss"),
        ("🎬", "The most cinematic soundtracks ever made"),
    ],
    "Français": [
        ("🕊️", "Chansons qui parlent de liberté"),
        ("🌙", "Musique qui parle de solitude"),
        ("✨", "Chansons qui parlent d'espoir"),
        ("🚗", "Jazz pour un trajet nocturne en voiture"),
        ("💔", "Chansons émouvantes sur les chagrins d'amour"),
        ("🎬", "Les bandes originales les plus cinématographiques"),
    ],
    "Español": [
        ("🕊️", "Canciones que hablan de libertad"),
        ("🌙", "Música que trata la soledad"),
        ("✨", "Canciones que hablan de esperanza"),
        ("🚗", "Jazz para un viaje nocturno en coche"),
        ("💔", "Canciones emotivas sobre corazones rotos y pérdidas"),
        ("🎬", "Las bandas sonoras más cinematográficas de siempre"),
    ],
    "Deutsch": [
        ("🕊️", "Lieder über Freiheit"),
        ("🌙", "Musik über Einsamkeit"),
        ("✨", "Lieder über Hoffnung"),
        ("🚗", "Jazz für eine nächtliche Autofahrt"),
        ("💔", "Emotionale Lieder über Herzschmerz und Verlust"),
        ("🎬", "Die kinematischsten Soundtracks aller Zeiten"),
    ],
    "Português": [
        ("🕊️", "Canções que falam de liberdade"),
        ("🌙", "Música que trata da solidão"),
        ("✨", "Canções que falam de esperança"),
        ("🚗", "Jazz para uma viagem noturna de carro"),
        ("💔", "Músicas emocionantes sobre corações partidos"),
        ("🎬", "As bandas sonoras mais cinematográficas de sempre"),
    ],
    "Nederlands": [
        ("🕊️", "Nummers over vrijheid"),
        ("🌙", "Muziek over eenzaamheid"),
        ("✨", "Nummers over hoop"),
        ("🚗", "Jazz voor een nachtelijke autorit"),
        ("💔", "Emotionele nummers over hartpijn en verlies"),
        ("🎬", "De meest cinematografische soundtracks ooit"),
    ],
    "Polski": [
        ("🕊️", "Piosenki o wolności"),
        ("🌙", "Muzyka o samotności"),
        ("✨", "Piosenki o nadziei"),
        ("🚗", "Jazz na nocną jazdę samochodem"),
        ("💔", "Emocjonalne piosenki o złamanych sercach i stracie"),
        ("🎬", "Najbardziej kinowe ścieżki dźwiękowe w historii"),
    ],
    "Русский": [
        ("🕊️", "Песни о свободе"),
        ("🌙", "Музыка об одиночестве"),
        ("✨", "Песни о надежде"),
        ("🚗", "Джаз для ночной поездки на машине"),
        ("💔", "Эмоциональные песни о разбитом сердце и потере"),
        ("🎬", "Самые кинематографичные саундтреки всех времён"),
    ],
    "日本語": [
        ("🕊️", "自由について歌った曲"),
        ("🌙", "孤独を扱った音楽"),
        ("✨", "希望について歌った曲"),
        ("🚗", "深夜のドライブに合うジャズ"),
        ("💔", "失恋と喪失を歌った感動的な曲"),
        ("🎬", "史上最も映画的なサウンドトラック"),
    ],
    "中文": [
        ("🕊️", "关于自由的歌曲"),
        ("🌙", "关于孤独的音乐"),
        ("✨", "关于希望的歌曲"),
        ("🚗", "深夜开车时听的爵士乐"),
        ("💔", "关于心碎与失去的感人歌曲"),
        ("🎬", "有史以来最具电影感的原声带"),
    ],
    "한국어": [
        ("🕊️", "자유에 관한 노래"),
        ("🌙", "고독을 다룬 음악"),
        ("✨", "희망에 관한 노래"),
        ("🚗", "심야 드라이브를 위한 재즈"),
        ("💔", "실연과 상실에 관한 감성적인 노래"),
        ("🎬", "역대 가장 영화적인 사운드트랙"),
    ],
    "العربية": [
        ("🕊️", "أغاني عن الحرية"),
        ("🌙", "موسيقى عن الوحدة"),
        ("✨", "أغاني عن الأمل"),
        ("🚗", "جاز لقيادة ليلية"),
        ("💔", "أغاني عاطفية عن القلوب المكسورة والخسارة"),
        ("🎬", "أروع الموسيقى التصويرية السينمائية على الإطلاق"),
    ],
}


def user_facing_llm_error(exc: Exception) -> str:
    raw = str(exc).lower()
    if any(hint in raw for hint in LLM_RETRY_ERROR_HINTS):
        return LLM_RETRY_MESSAGE
    return f"⚠️ LLM: {exc}"


def strip_narration_source_label(text: str) -> str:
    return re.sub(
        r"^\s*(?:\*\*)?\s*(?:musixmatch|theaudiodb|audio\s*db)\s*(?:\*\*)?\s*[:\-–—]?\s*",
        "",
        text or "",
        flags=re.IGNORECASE,
    ).strip()


def compact_text(text: str, limit: int = 360) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
