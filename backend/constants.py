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
        ("🌧️", "Canzoni per una domenica mattina di pioggia"),
        ("🌙", "Musica che sa di solitudine alle 3 di notte"),
        ("🎸", "Album rock che hanno cambiato tutto"),
        ("🚗", "Jazz per un viaggio notturno in macchina"),
        ("💔", "Canzoni emozionanti su cuori spezzati e perdite"),
        ("🎬", "Le colonne sonore più cinematografiche di sempre"),
    ],
    "English": [
        ("🌧️", "Songs for a rainy Sunday morning"),
        ("🌙", "Music that sounds like 3am loneliness"),
        ("🎸", "Rock albums that changed everything"),
        ("🚗", "Jazz for a late-night drive"),
        ("💔", "Emotional songs about heartbreak and loss"),
        ("🎬", "The most cinematic soundtracks ever made"),
    ],
    "Français": [
        ("🌧️", "Chansons pour un dimanche matin pluvieux"),
        ("🌙", "Musique qui ressemble à la solitude à 3h du matin"),
        ("🎸", "Albums rock qui ont tout changé"),
        ("🚗", "Jazz pour un trajet nocturne en voiture"),
        ("💔", "Chansons émouvantes sur les chagrins d'amour"),
        ("🎬", "Les bandes originales les plus cinématographiques"),
    ],
    "Español": [
        ("🌧️", "Canciones para una mañana de domingo lluviosa"),
        ("🌙", "Música que suena a soledad a las 3 de la madrugada"),
        ("🎸", "Álbumes de rock que lo cambiaron todo"),
        ("🚗", "Jazz para un viaje nocturno en coche"),
        ("💔", "Canciones emotivas sobre corazones rotos y pérdidas"),
        ("🎬", "Las bandas sonoras más cinematográficas de siempre"),
    ],
    "Deutsch": [
        ("🌧️", "Lieder für einen regnerischen Sonntagmorgen"),
        ("🌙", "Musik, die sich wie Einsamkeit um 3 Uhr morgens anfühlt"),
        ("🎸", "Rockalbum, die alles verändert haben"),
        ("🚗", "Jazz für eine nächtliche Autofahrt"),
        ("💔", "Emotionale Lieder über Herzschmerz und Verlust"),
        ("🎬", "Die kinematischsten Soundtracks aller Zeiten"),
    ],
    "Português": [
        ("🌧️", "Músicas para uma manhã de domingo chuvosa"),
        ("🌙", "Música que parece solidão às 3 da manhã"),
        ("🎸", "Álbuns de rock que mudaram tudo"),
        ("🚗", "Jazz para uma viagem noturna de carro"),
        ("💔", "Músicas emocionantes sobre corações partidos"),
        ("🎬", "As bandas sonoras mais cinematográficas de sempre"),
    ],
    "Nederlands": [
        ("🌧️", "Nummers voor een regenachtige zondagochtend"),
        ("🌙", "Muziek die klinkt als eenzaamheid om 3 uur 's nachts"),
        ("🎸", "Rockalbums die alles veranderd hebben"),
        ("🚗", "Jazz voor een nachtelijke autorit"),
        ("💔", "Emotionele nummers over hartpijn en verlies"),
        ("🎬", "De meest cinematografische soundtracks ooit"),
    ],
    "Polski": [
        ("🌧️", "Piosenki na deszczowy niedzielny poranek"),
        ("🌙", "Muzyka brzmiąca jak samotność o 3 w nocy"),
        ("🎸", "Albumy rockowe, które zmieniły wszystko"),
        ("🚗", "Jazz na nocną jazdę samochodem"),
        ("💔", "Emocjonalne piosenki o złamanych sercach i stracie"),
        ("🎬", "Najbardziej kinowe ścieżki dźwiękowe w historii"),
    ],
    "Русский": [
        ("🌧️", "Песни для дождливого воскресного утра"),
        ("🌙", "Музыка, звучащая как одиночество в 3 ночи"),
        ("🎸", "Рок-альбомы, изменившие всё"),
        ("🚗", "Джаз для ночной поездки на машине"),
        ("💔", "Эмоциональные песни о разбитом сердце и потере"),
        ("🎬", "Самые кинематографичные саундтреки всех времён"),
    ],
    "日本語": [
        ("🌧️", "雨の日曜日の朝にぴったりな曲"),
        ("🌙", "夜中の3時の孤独を感じさせる音楽"),
        ("🎸", "すべてを変えたロックアルバム"),
        ("🚗", "深夜のドライブに合うジャズ"),
        ("💔", "失恋と喪失を歌った感動的な曲"),
        ("🎬", "史上最も映画的なサウンドトラック"),
    ],
    "中文": [
        ("🌧️", "适合雨天周日早晨的歌曲"),
        ("🌙", "听起来像凌晨三点孤独感的音乐"),
        ("🎸", "改变了一切的摇滚专辑"),
        ("🚗", "深夜开车时听的爵士乐"),
        ("💔", "关于心碎与失去的感人歌曲"),
        ("🎬", "有史以来最具电影感的原声带"),
    ],
    "한국어": [
        ("🌧️", "비 오는 일요일 아침에 어울리는 노래"),
        ("🌙", "새벽 3시의 외로움처럼 들리는 음악"),
        ("🎸", "모든 것을 바꾼 록 앨범"),
        ("🚗", "심야 드라이브를 위한 재즈"),
        ("💔", "실연과 상실에 관한 감성적인 노래"),
        ("🎬", "역대 가장 영화적인 사운드트랙"),
    ],
    "العربية": [
        ("🌧️", "أغاني لصباح أحد ممطر"),
        ("🌙", "موسيقى تبدو كالوحدة في الساعة الثالثة صباحاً"),
        ("🎸", "ألبومات روك غيّرت كل شيء"),
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
