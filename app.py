"""Sonder - interfaccia Streamlit.

Entry point dell'applicazione. Orchestra il flusso:
    Musixmatch -> TheAudioDB -> LLM (Thinking) -> Spotify -> UI

L'app si avvia anche senza chiavi API: ogni sezione entra in "modalita' demo"
e indica quale variabile inserire nel file .env.
"""
from __future__ import annotations

import base64
import functools
import html
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from core.config import (
    settings,
    SONGSTATS_MIN_STREAMS,
    SEARCH_LANGUAGE_OPTIONS,
    LLM_MODEL_OPTIONS,
)
from core.musixmatch_client import MusixmatchClient, MusixmatchError
from core.audiodb_client import AudioDBClient, AudioDBError
from core.lastfm_client import LastFMClient, LastFMError
from core.storyteller import Storyteller, StorytellerError
from core.spotify_client import SpotifyClient, SpotifyError
from core.songstats_client import SongstatsClient, SongstatsError
from core import spotify_pkce
from core import tts_server

# --------------------------------------------------------------------------- #
# Logo helpers
# --------------------------------------------------------------------------- #
_LOGO_DIR = Path(__file__).parent / "static"


@st.cache_data(show_spinner=False)
def _logo_b64(filename: str) -> str:
    """Restituisce il contenuto base64 di un file immagine nella cartella static."""
    p = _LOGO_DIR / filename
    if not p.exists():
        return ""
    return base64.b64encode(p.read_bytes()).decode()


# Il verifier PKCE va conservato lato server: il redirect verso Spotify provoca
# un full page reload e Streamlit avvia una nuova sessione, quindi st.session_state
# non sopravvive. NB: anche le variabili a livello di modulo in app.py vengono
# azzerate a ogni rerun (lo script principale e' rieseguito da capo), percio'
# usiamo st.cache_resource, che persiste nel processo server tra sessioni e rerun.
@st.cache_resource
def _pkce_store() -> dict[str, str]:
    """Store condiviso state -> verifier, persistente tra sessioni/rerun."""
    return {}


@st.cache_resource
def _persistent_token_store() -> dict[str, object]:
    """Store del token Spotify persistente tra sessioni/rerun (usato da Stay logged in)."""
    return {}


@st.cache_resource
def _stay_logged_store() -> dict[str, bool]:
    """Mappa state -> stay_logged; sopravvive al redirect OAuth verso Spotify."""
    return {}

# Lingua UI -> (nome per il prompt LLM, codice biografia TheAudioDB)
# "🌐 Auto" => il modello riconosce automaticamente la lingua dell'utente.
LANGUAGES: dict[str, tuple[str, str]] = {
    "🌐 Auto": ("Auto", "EN"),
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

# Lingua di narrazione -> codice BCP-47 per la sintesi vocale del browser (Web Speech API).
TTS_LANG: dict[str, str] = {
    "Auto": "",
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
    "Auto": "en",
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
    "EN": "en",
    "IT": "it",
    "FR": "fr",
    "ES": "es",
    "DE": "de",
    "PT": "pt",
    "NL": "nl",
    "PL": "pl",
    "RU": "ru",
    "JP": "ja",
    "CN": "zh",
    "KR": "ko",
    "AR": "ar",
}


def musixmatch_translation_code(lang_name: str = "Auto", lang_code: str = "EN") -> str:
    return (
        MUSIXMATCH_TRANSLATION_LANG.get(lang_name)
        or MUSIXMATCH_TRANSLATION_LANG_BY_CODE.get(lang_code.upper(), "en")
    )

# Saluto iniziale della chat per ciascuna lingua (per "Auto" usiamo un saluto bilingue).
GREETINGS: dict[str, str] = {
    "Auto": "Hi, I'm **Sonder**. What would you like to talk about? "
            "Feel free to write in any language and I'll reply in the same. ",
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

# Messaggi di rifiuto in-character per argomenti fuori ambito musicale.
REFUSALS: dict[str, str] = {
    "Auto":     "*Questo non è il mio territorio.* Sono fatto di note, versi e ombre sonore — parlami di musica e ti seguirò ovunque. ",
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
    "rate out of bandwidth",
    "rate out of widthband",
    "out of bandwidth",
    "widthband",
    "bandwidth",
    "rate limit",
    "rate limited",
    "too many requests",
    "429",
    "quota",
)

# Palette neon "studio tecnologico", ciclata per indice su pill e card.
PALETTE = ["#ff2d78", "#f97316", "#22d3ee", "#facc15", "#c2410c", "#34d399"]

EXAMPLE_PROMPTS: dict[str, list[tuple[str, str]]] = {
    "Auto": [
        ("🌧️", "Songs for a rainy Sunday morning"),
        ("🌙", "Music that sounds like 3am loneliness"),
        ("🎸", "Rock albums that changed everything"),
        ("🚗", "Jazz for a late-night drive"),
        ("💔", "Emotional songs about heartbreak and loss"),
        ("🎬", "The most cinematic soundtracks ever made"),
    ],
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

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap');

    /* Fondo "sala di regia": nero profondo, aurore neon e griglia tecnica */
    .stApp {
        background:
            radial-gradient(1100px 620px at 88% -10%, rgba(255,45,120,0.13), transparent 60%),
            radial-gradient(960px 560px at 4% 0%, rgba(249,115,22,0.12), transparent 60%),
            radial-gradient(900px 640px at 50% 118%, rgba(34,211,238,0.09), transparent 62%),
            linear-gradient(rgba(255,255,255,0.022) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.022) 1px, transparent 1px),
            #07070f;
        background-size: auto, auto, auto, 44px 44px, 44px 44px, auto;
        color: #e8e6f5;
    }
    /* Corpo del testo: sans tecnologico */
    .stApp, .stMarkdown, p, li { font-family: 'Inter', 'Segoe UI', sans-serif; }
    .block-container { max-width: 1360px; }

    /* Occhiello / kicker sopra il titolo */
    .hero-kicker {
        font-family: 'JetBrains Mono', monospace;
        text-transform: uppercase; letter-spacing: .42em;
        font-size: .68rem; font-weight: 600; color: #22d3ee;
        margin-bottom: .55rem;
    }

    /* Titolo: display tecnologico con gradiente neon e glow */
    .hero-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.9rem;
        font-weight: 700;
        letter-spacing: .02em;
        line-height: 1.1;
        background: linear-gradient(95deg, #ff2d78, #f97316 45%, #22d3ee 90%);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        filter: drop-shadow(0 0 18px rgba(249,115,22,.35));
        margin: 0;
    }
    /* Titolo "finestra": l'ultima richiesta dell'utente diventa l'insegna */
    .studio-kicker {
        font-family: 'JetBrains Mono', monospace;
        text-transform: uppercase; letter-spacing: .4em;
        font-size: .64rem; font-weight: 600; color: #f97316; margin-bottom: .35rem;
    }
    .studio-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2.7rem; font-weight: 700; line-height: 1.05;
        background: linear-gradient(95deg, #ff2d78, #f97316 50%, #22d3ee);
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent; margin: 0 0 .2rem 0;
    }
    /* Intestazione piccola = testo scritto in chat, appena sotto il logo */
    .studio-prompt {
        font-family: 'JetBrains Mono', monospace;
        color: #8f8aa8; font-size: .92rem;
        margin: .25rem 0 0 0;
    }
    .studio-prompt::before { content: '> '; color: #22d3ee; }
    .hero-sub {
        font-family: 'Inter', sans-serif;
        color: #8f8aa8;
        font-size: 1.2rem;
        line-height: 1.4;
        margin-top: .35rem;
        max-width: 760px;
    }

    /* Linea laser sfumata */
    .hr-glow {
        height: 2px; border: 0; margin: 1.2rem 0 1.7rem 0; border-radius: 2px;
        background: linear-gradient(90deg, #ff2d78, #f97316 45%, #22d3ee 75%, transparent);
        box-shadow: 0 0 12px rgba(249,115,22,.5);
        opacity: .85;
    }

    /* Pill / parole chiave (colore impostato inline per varieta') */
    .pill {
        display:inline-block; padding: 5px 15px; margin: 4px 7px 4px 0;
        border-radius: 999px; font-size: .78rem; font-weight: 600;
        font-family: 'JetBrains Mono', monospace; letter-spacing: .03em;
        backdrop-filter: blur(6px);
    }

    /* Archetipo: display con gradiente neon */
    .archetype {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.95rem; font-weight: 600;
        background: linear-gradient(90deg, #ff2d78, #f97316);
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: .1rem 0 .7rem 0; line-height: 1.15;
    }

    /* Card brano: vetro scuro con bagliore al passaggio */
    .track-card {
        padding: 13px 17px; margin-bottom: 11px; border-radius: 14px;
        background: linear-gradient(160deg, rgba(255,255,255,.05), rgba(255,255,255,.02));
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 8px 24px rgba(0,0,0,0.35);
        backdrop-filter: blur(10px);
        transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
    }
    .track-card:hover {
        transform: translateY(-2px);
        border-color: rgba(249,115,22,.45);
        box-shadow: 0 12px 30px rgba(249,115,22,0.22);
    }
    .track-card b { color: #f3f1ff; font-family: 'Space Grotesk', sans-serif; font-weight: 600; }
    .track-card span { color: #8f8aa8; font-size: .88rem; }

    /* Testo della canzone su pannello scuro */
    .lyrics-box {
        white-space: pre-wrap; font-size: .95rem; line-height: 1.6;
        font-family: 'Inter', sans-serif;
        color: #c9c5dd; max-height: 460px; overflow-y: auto;
        padding: 16px 18px;
        background: rgba(255,255,255,.04); border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.08);
    }

    /* Pulsante principale: neon */
    div[data-testid="stFormSubmitButton"] button {
        background: linear-gradient(100deg, #ff2d78, #f97316);
        color: #fff !important; border: 0; border-radius: 12px; font-weight: 700;
        font-family: 'Space Grotesk', sans-serif; letter-spacing: .02em;
        padding: .6rem 1rem;
        box-shadow: 0 0 22px rgba(255,45,120,.35);
        transition: transform .15s ease, box-shadow .15s ease, filter .15s ease;
    }
    div[data-testid="stFormSubmitButton"] button:hover {
        transform: translateY(-1px); filter: brightness(1.1);
        box-shadow: 0 0 32px rgba(249,115,22,.5);
    }
    div[data-testid="stFormSubmitButton"] button p { font-weight: 700; }

    /* Sidebar: pannello di controllo scuro */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0b0b17 0%, #0e0d1d 100%);
        border-right: 1px solid rgba(255,255,255,.07);
    }
    section[data-testid="stSidebar"] .stMarkdown h3 {
        font-family: 'Space Grotesk', sans-serif; letter-spacing: .04em;
    }
    section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.08); }

    /* Riquadro stato API in sidebar */
    .api-box {
        background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
        border-radius: 12px; padding: 10px 12px;
    }
    .api-row {
        display: flex; align-items: center; gap: 8px;
        font-family: 'JetBrains Mono', monospace; font-size: .76rem;
        color: #c9c5dd; padding: 3px 0;
    }
    .api-dot {
        width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto;
        box-shadow: 0 0 8px currentColor;
    }
    .api-state { margin-left: auto; color: #8f8aa8; font-size: .7rem; }

    /* Bottoni standard e link-button in stile pannello */
    .stButton button, .stLinkButton a {
        border-radius: 12px !important;
        border: 1px solid rgba(249,115,22,.35) !important;
        background: rgba(249,115,22,.10) !important;
        color: #e8e6f5 !important;
        font-family: 'Space Grotesk', sans-serif !important;
        transition: box-shadow .15s ease, border-color .15s ease;
    }
    .stButton button:hover, .stLinkButton a:hover {
        border-color: #f97316 !important;
        box-shadow: 0 0 18px rgba(249,115,22,.35);
    }

    /* Campi di input scuri con focus neon */
    .stTextInput input, .stTextArea textarea {
        border-radius: 12px !important;
        border: 1px solid rgba(255,255,255,.12) !important;
        background: rgba(255,255,255,.05) !important;
        color: #e8e6f5 !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #ff2d78 !important;
        box-shadow: 0 0 0 2px rgba(255,45,120,.2) !important;
    }

    /* Barra di input principale: stile simile alla chat bar */
    div[data-testid="stTextInput"] input {
        border-radius: 14px !important;
        border: 1px solid rgba(249,115,22,.35) !important;
        background: rgba(20,16,36,.85) !important;
        color: #e8e6f5 !important;
        font-size: 1rem !important;
        padding: 0.65rem 1rem !important;
        box-shadow: 0 0 18px rgba(249,115,22,.12) !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #f97316 !important;
        box-shadow: 0 0 28px rgba(249,115,22,.25) !important;
    }

    /* Barra chat scura */
    div[data-testid="stChatInput"] {
        border-radius: 14px;
        border: 1px solid rgba(249,115,22,.3);
        box-shadow: 0 0 24px rgba(249,115,22,.15);
    }

    /* Heading tecnologici */
    h1, h2, h3, h4 { font-family: 'Space Grotesk', sans-serif; color: #f3f1ff; }
    details summary { font-family: 'Space Grotesk', sans-serif; }
</style>
"""


# --------------------------------------------------------------------------- #
# Helpers UI
# --------------------------------------------------------------------------- #
def render_pills(items: list[str]) -> None:
    if not items:
        return
    spans = []
    for index, item in enumerate(items):
        color = PALETTE[index % len(PALETTE)]
        spans.append(
            f'<span class="pill" style="background:{color}1f;'
            f'border:1px solid {color};color:{color};">{item}</span>'
        )
    st.markdown("".join(spans), unsafe_allow_html=True)


LLM_MODEL_LABELS = {value: label for label, value in LLM_MODEL_OPTIONS}


def llm_model_values() -> list[str]:
    """Modelli LLM selezionabili; include quello da .env se non gia' presente."""
    values = [value for _, value in LLM_MODEL_OPTIONS]
    if settings.llm_model and settings.llm_model not in values:
        values.insert(0, settings.llm_model)
    return values


def selected_llm_model() -> str:
    """Modello LLM attivo per la sessione (scelta utente o default da .env)."""
    values = llm_model_values()
    selected = st.session_state.get("llm_model") or settings.llm_model
    if selected not in values:
        selected = values[0] if values else settings.llm_model
    st.session_state["llm_model"] = selected
    return selected


def render_llm_model_selector() -> None:
    """Box in sidebar per scegliere quale LLM usare nelle prossime chiamate."""
    values = llm_model_values()
    if not values:
        return
    selected = selected_llm_model()
    label_map = dict(LLM_MODEL_LABELS)
    if settings.llm_model and settings.llm_model not in label_map:
        label_map[settings.llm_model] = "Configured in .env"
    index = values.index(selected) if selected in values else 0
    with st.sidebar.expander("🧠 LLM model", expanded=False):
        chosen = st.selectbox(
            "Model",
            values,
            index=index,
            format_func=lambda value: label_map.get(value, value),
            key="llm_model_selectbox",
        )
        st.session_state["llm_model"] = chosen
        st.caption(f"Using `{chosen}` for the next LLM calls.")


def render_status_sidebar() -> None:
    st.sidebar.markdown("### 🔌 API Status")
    rows = []
    statuses: dict[str, bool] = dict(settings.status())
    # Always show ElevenLabs even if the module was cached before the property was added.
    if "ElevenLabs TTS" not in statuses:
        statuses["ElevenLabs TTS"] = getattr(settings, "elevenlabs_ready", False)
    for service, ready in statuses.items():
        dot = "#2de26d" if ready else "#ff4d6d"
        label = "ready" if ready else "missing key"
        rows.append(
            f'<div class="api-row"><span class="api-dot" style="background:{dot};"></span>'
            f'<b>{service}</b><span class="api-state">{label}</span></div>'
        )
    st.sidebar.markdown(
        f'<div class="api-box">{"".join(rows)}</div>', unsafe_allow_html=True
    )
    st.sidebar.caption("Set keys in the `.env` file (see `.env.example`).")
    st.sidebar.markdown("---")


# --------------------------------------------------------------------------- #
# Tool musicali (contesto + playlist)
# --------------------------------------------------------------------------- #
def fetch_song_context(title: str, artist: str, lang_code: str) -> tuple[str, list[str]]:
    """Recupera testo (Musixmatch) e biografia (TheAudioDB) come contesto per la chat."""
    parts: list[str] = []
    notes: list[str] = []

    if title and settings.musixmatch_ready:
        try:
            mx_client = MusixmatchClient()
            matches = mx_client.search_tracks(track=title, artist=artist, has_lyrics=True, limit=1)
            if matches:
                track = matches[0]
                lyrics_text, richsync_body, translated_text = fetch_musixmatch_text(
                    mx_client,
                    track.track_id,
                    track.has_lyrics,
                    track.has_richsync,
                    translation_lang=MUSIXMATCH_TRANSLATION_LANG_BY_CODE.get(
                        lang_code.upper(), "en"
                    ),
                )
                parts.append(f"Brano: «{track.track_name or title}» di {track.artist_name or artist or 'artista sconosciuto'}")
                if richsync_body:
                    parts.append("Richsync word-level (Musixmatch): disponibile")
                if translated_text:
                    parts.append("Traduzione testo (Musixmatch):\n" + translated_text)
                if lyrics_text:
                    parts.append("Testo (Musixmatch):\n" + lyrics_text)
            else:
                notes.append("Musixmatch: no track found.")
        except MusixmatchError as exc:
            notes.append(f"Musixmatch: {exc}")
    elif title:
        notes.append("Musixmatch not configured: lyrics were not fetched.")

    bio = ""
    if artist and settings.audiodb_ready:
        try:
            artist_obj = AudioDBClient().get_artist(artist)
            if artist_obj:
                bio = artist_obj.biography(lang_code)
                if bio:
                    parts.append(f"Biografia di {artist} (TheAudioDB):\n{bio}")
        except AudioDBError as exc:
            notes.append(f"TheAudioDB: {exc}")

    # Fallback: se TheAudioDB non ha dato nulla, prova Last.fm.
    if artist and not bio and settings.lastfm_ready:
        try:
            lf_bio = LastFMClient().get_biography(name=artist, lang=lang_code)
            if lf_bio:
                parts.append(f"Biografia di {artist} (Last.fm):\n{lf_bio}")
        except LastFMError as exc:
            notes.append(f"Last.fm: {exc}")

    return "\n\n".join(parts), notes


def render_track_cards(tracks: list[dict[str, str]]) -> None:
    for index, t in enumerate(tracks):
        color = PALETTE[index % len(PALETTE)]
        reason = f'<span> — {t["reason"]}</span>' if t.get("reason") else ""
        st.markdown(
            f'<div class="track-card" style="border-left:5px solid {color};">'
            f'<b>{t.get("artist", "")} — {t.get("title", "")}</b>{reason}</div>',
            unsafe_allow_html=True,
        )


def user_facing_llm_error(exc: Exception) -> str:
    raw = str(exc).lower()
    if any(hint in raw for hint in LLM_RETRY_ERROR_HINTS):
        return LLM_RETRY_MESSAGE
    return f"⚠️ LLM: {exc}"


def fetch_musixmatch_text(
    mx_client: MusixmatchClient,
    track_id: int,
    has_lyrics: bool,
    has_richsync: bool,
    translation_lang: str = "",
) -> tuple[str, list[dict[str, Any]], str]:
    lyrics_text = ""
    translated_text = ""
    richsync_body: list[dict[str, Any]] = []
    if has_richsync:
        try:
            richsync = mx_client.get_richsync(track_id)
            if richsync and not richsync.is_empty:
                richsync_body = richsync.body
                lyrics_text = richsync.text
        except MusixmatchError:
            pass
    if not lyrics_text and has_lyrics:
        try:
            lyrics = mx_client.get_lyrics(track_id)
            lyrics_text = lyrics.body if lyrics and not lyrics.is_empty else ""
        except MusixmatchError:
            lyrics_text = ""
    if translation_lang:
        try:
            translation = mx_client.get_lyrics_translation(track_id, translation_lang)
            translated_text = (
                translation.body if translation and not translation.is_empty else ""
            )
        except MusixmatchError:
            translated_text = ""
    return lyrics_text, richsync_body, translated_text


def musixmatch_track_payload(
    mx_client: MusixmatchClient,
    track: Any,
    reason: str = "",
    translation_lang: str = "",
) -> dict[str, Any]:
    lyrics_text, richsync_body, translated_text = fetch_musixmatch_text(
        mx_client,
        track.track_id,
        track.has_lyrics,
        track.has_richsync,
        translation_lang=translation_lang,
    )
    return {
        "title": track.track_name,
        "artist": track.artist_name,
        "album": track.album_name,
        "track_id": str(track.track_id),
        "reason": reason,
        "lyrics": lyrics_text,
        "translated_lyrics": translated_text,
        "translation_lang": translation_lang,
        "richsync": richsync_body,
        "has_lyrics": track.has_lyrics,
        "has_richsync": track.has_richsync,
    }


# --------------------------------------------------------------------------- #
# Songstats (statistiche reali + soglia di notorieta')
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=512)
def _resolve_isrc(title: str, artist: str) -> str:
    """Risolve l'ISRC di una traccia via Spotify (chiave per le statistiche Songstats).

    Le statistiche Songstats si interrogano per ISRC (``GET /tracks/stats?isrc=...``),
    un identificatore univoco e affidabile: evita le ambiguita' della ricerca testuale.
    In cache di processo e thread-safe (usabile dai worker senza contesto Streamlit).
    """
    if not settings.spotify_ready or not title:
        return ""
    try:
        track = SpotifyClient().search_track(title, artist or None)
    except Exception:  # noqa: BLE001 - mai propagare verso UI/filtri
        return ""
    return (track.isrc if track else "") or ""


@functools.lru_cache(maxsize=512)
def _songstats_track_stats(title: str, artist: str) -> dict[str, Any] | None:
    """Lookup Songstats per traccia, in cache di processo (thread-safe).

    Risolve prima l'ISRC via Spotify, poi interroga Songstats per ISRC (percorso
    canonico). Restituisce un dict semplice (o ``None``) cosi' da poter essere usato sia
    nel filtro di popolarita' sia nei grafici. NON usa ``st.cache_data`` perche' viene
    invocato anche da thread di lavoro privi del contesto Streamlit.
    """
    if not settings.songstats_ready or not (title or artist):
        return None
    isrc = _resolve_isrc(title, artist)
    if not isrc:
        return None
    try:
        stats = SongstatsClient().track_stats_by_isrc(isrc, title, artist)
    except Exception:  # noqa: BLE001 - mai propagare verso la UI
        return None
    if not stats or stats.is_empty:
        return None
    return {
        "name": stats.name,
        "subtitle": stats.subtitle,
        "avatar": stats.avatar,
        "sources": stats.sources,
        "total_streams": stats.total_streams,
        "headline": stats.headline_metrics(),
        "isrc": isrc,
    }


@functools.lru_cache(maxsize=256)
def _songstats_artist_stats(name: str) -> dict[str, Any] | None:
    """Lookup Songstats per artista, in cache di processo."""
    if not settings.songstats_ready or not name:
        return None
    try:
        stats = SongstatsClient().artist_stats(name)
    except (SongstatsError, Exception):  # noqa: BLE001
        return None
    if not stats or stats.is_empty:
        return None
    return {
        "name": stats.name,
        "subtitle": stats.subtitle,
        "avatar": stats.avatar,
        "sources": stats.sources,
        "total_streams": stats.total_streams,
        "headline": stats.headline_metrics(),
    }


def apply_popularity_floor(
    tracks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Esclude i brani poco noti sotto la soglia Songstats (task 4).

    - Le tracce per cui Songstats non restituisce stream (o non e' configurato) vengono
      MANTENUTE (beneficio del dubbio), per non svuotare i risultati.
    - I lookup avvengono in parallelo. Le statistiche trovate vengono allegate alla
      traccia (chiave ``songstats``) per riuso nei grafici, evitando doppie chiamate.
    """
    notes: list[str] = []
    if not settings.songstats_ready or not tracks:
        return tracks, notes

    def lookup(t: dict[str, Any]) -> dict[str, Any] | None:
        return _songstats_track_stats(t.get("title", ""), t.get("artist", ""))

    with ThreadPoolExecutor(max_workers=min(8, len(tracks))) as executor:
        stats_list = list(executor.map(lookup, tracks))

    kept: list[dict[str, Any]] = []
    dropped = 0
    for track, stats in zip(tracks, stats_list):
        if stats:
            track["songstats"] = stats
            streams = int(stats.get("total_streams", 0) or 0)
            if streams and streams < SONGSTATS_MIN_STREAMS:
                dropped += 1
                continue
        kept.append(track)
    if dropped:
        notes.append(
            f"Songstats: {dropped} brano/i poco noto/i nascosto/i "
            f"(sotto {SONGSTATS_MIN_STREAMS:,} stream)."
        )
    # Sicurezza: non restituire mai una lista vuota se c'erano risultati.
    if not kept and tracks:
        return tracks, notes
    return kept, notes


def search_musixmatch_from_plan(
    plan: dict[str, Any],
    lang_name: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not settings.musixmatch_ready:
        return [], ["Musixmatch not configured: set `MUSIXMATCH_API_KEY` or `MXM_KEY`."]

    notes: list[str] = []
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    mx_client = MusixmatchClient()
    translation_lang = MUSIXMATCH_TRANSLATION_LANG.get(lang_name, "en")
    try:
        limit = int(plan.get("limit", 8))
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 8))

    queries = plan.get("queries") or []
    if not isinstance(queries, list):
        queries = []

    # 1) Raccogli i match unici (in ordine) senza ancora scaricare testi/richsync.
    collected: list[tuple[Any, str]] = []  # (Track, reason)
    for query in queries:
        if len(collected) >= limit or not isinstance(query, dict):
            continue
        q = str(query.get("q", "")).strip()
        q_track = str(query.get("q_track", "")).strip()
        q_artist = str(query.get("q_artist", "")).strip()
        q_lyrics = str(query.get("q_lyrics", "")).strip()
        reason = str(query.get("reason", "")).strip()
        if not any((q, q_track, q_artist, q_lyrics)):
            continue
        try:
            matches = mx_client.search_tracks(
                query=q or None,
                track=q_track or None,
                artist=q_artist or None,
                lyrics=q_lyrics or None,
                has_lyrics=True,
                limit=limit - len(collected),
            )
        except MusixmatchError as exc:
            notes.append(f"Musixmatch: {exc}")
            continue
        for match in matches:
            if match.track_id in seen:
                continue
            seen.add(match.track_id)
            collected.append((match, reason))
            if len(collected) >= limit:
                break

    # 2) Scarica testo/richsync/traduzione in PARALLELO (task 9), preservando l'ordine.
    #    Un client per worker: evita di condividere la stessa requests.Session tra thread.
    def build_payload(item: tuple[Any, str]) -> dict[str, Any]:
        match, reason = item
        return musixmatch_track_payload(
            MusixmatchClient(),
            match,
            reason=reason,
            translation_lang=translation_lang,
        )

    if collected:
        with ThreadPoolExecutor(max_workers=min(8, len(collected))) as executor:
            results = list(executor.map(build_payload, collected))

    # 3) Soglia di notorieta' Songstats (task 4): esclude i brani poco noti.
    results, floor_notes = apply_popularity_floor(results)
    notes.extend(floor_notes)
    return results, notes


def create_spotify_playlist(tracks: list[dict[str, str]], name: str) -> None:
    """Crea su Spotify la playlist suggerita dal bot e ne mostra il player."""
    try:
        sp = SpotifyClient()
        playlist = sp.create_thematic_playlist(
            name=f"Sonder · {name}"[:100],
            description="Curated by Sonder during the conversation.",
            tracks=tracks,
        )
        st.success(f"Playlist created: {playlist.name} ({playlist.track_count} tracks)")
        components.iframe(playlist.embed_url, height=380)
        if playlist.url:
            st.markdown(f"[Open on Spotify]({playlist.url})")
    except SpotifyError as exc:
        st.error(f"Spotify: {exc}")


# --------------------------------------------------------------------------- #
# Spotify per-utente (Authorization Code + PKCE)
# --------------------------------------------------------------------------- #
def handle_spotify_callback() -> None:
    """Se torniamo dal login Spotify (?code&state), scambia il code con un token."""
    qp = st.query_params
    code = qp.get("code")
    state = qp.get("state")
    if not code or not state:
        return
    verifier = st.session_state.pop(f"_pkce_{state}", None) or _pkce_store().pop(state, None)
    if not verifier:
        st.session_state["sp_auth_error"] = (
            "Sessione di login scaduta o non trovata: riprova a fare login."
        )
    else:
        try:
            token = spotify_pkce.exchange_code(
                client_id=settings.spotify_client_id,
                redirect_uri=settings.spotify_redirect_uri,
                code=code,
                verifier=verifier,
            )
            tok_data = {
                "access_token": token.get("access_token", ""),
                "refresh_token": token.get("refresh_token", ""),
                "expires_at": time.time() + int(token.get("expires_in", 3600)),
                "scope": token.get("scope", ""),
            }
            st.session_state["sp_token"] = tok_data
            # Salviamo sempre nel persistent store (vive nel processo server):
            # così, dopo il login completato in una nuova scheda, anche la scheda
            # originale recupera il token al refresh. "Stay logged in" resta la
            # preferenza esplicita dell'utente.
            _persistent_token_store()["token"] = tok_data
            _stay_logged_store().pop(state, None)
            st.session_state.pop("sp_auth_error", None)
        except spotify_pkce.SpotifyPKCEError as exc:
            st.session_state["sp_auth_error"] = str(exc)
    st.query_params.clear()
    st.rerun()


def spotify_token() -> str:
    """Restituisce un access token valido, rinnovandolo se scaduto."""
    tok = st.session_state.get("sp_token")
    if not tok:
        # Prova a ripristinare dal persistent store (Stay logged in).
        persisted = _persistent_token_store().get("token")
        if persisted:
            st.session_state["sp_token"] = persisted
            tok = persisted
        else:
            return ""
    if isinstance(tok, str):  # retrocompatibilita' con sessioni precedenti
        return tok
    if time.time() > tok.get("expires_at", 0) - 60 and tok.get("refresh_token"):
        try:
            new = spotify_pkce.refresh_access_token(
                client_id=settings.spotify_client_id,
                refresh_token=tok["refresh_token"],
            )
            tok["access_token"] = new.get("access_token", tok["access_token"])
            tok["refresh_token"] = new.get("refresh_token", tok["refresh_token"])
            tok["expires_at"] = time.time() + int(new.get("expires_in", 3600))
            tok["scope"] = new.get("scope", tok.get("scope", ""))
            st.session_state["sp_token"] = tok
            if _persistent_token_store().get("token"):
                _persistent_token_store()["token"] = tok
        except spotify_pkce.SpotifyPKCEError:
            st.session_state.pop("sp_token", None)
            _persistent_token_store().pop("token", None)
            return ""
    return tok.get("access_token", "")


def render_spotify_login(container) -> None:
    """Mostra in sidebar lo stato/login Spotify per-utente."""
    container.markdown("### 🎧 Spotify")
    if not settings.spotify_pkce_ready:
        container.caption(
            "Set `SPOTIFY_CLIENT_ID` (public) in `.env` to enable "
            "login with your own account."
        )
        return

    if st.session_state.get("sp_auth_error"):
        container.error(f"Login Spotify: {st.session_state['sp_auth_error']}")

    redirect_uri = settings.spotify_redirect_uri
    if "localhost" in redirect_uri or "127.0.0.1" in redirect_uri:
        container.warning(
            "For the deployed app, set `SPOTIFY_REDIRECT_URI` to "
            "`https://sonder.streamlit.app/` in Streamlit Secrets and add "
            "that exact Redirect URI in the Spotify dashboard. Use "
            "`http://127.0.0.1:8501` only when running locally."
        )
    elif not redirect_uri.startswith("https://"):
        container.warning(
            "On Streamlit Cloud, `SPOTIFY_REDIRECT_URI` must be an HTTPS URL "
            "and must match the Spotify dashboard Redirect URI exactly."
        )

    if spotify_token():
        container.success("🟢 Connected to your Spotify")
        if container.button("Disconnect Spotify", use_container_width=True):
            st.session_state.pop("sp_token", None)
            _persistent_token_store().pop("token", None)
            st.session_state.pop("sp_auth_error", None)
            st.rerun()
        return

    # Prepara un nuovo tentativo di login (verifier/state freschi).
    verifier = spotify_pkce.make_verifier()
    challenge = spotify_pkce.make_challenge(verifier)
    state = spotify_pkce.make_state()
    # Salva il verifier lato server: sopravvive al redirect verso Spotify
    # (la nuova sessione Streamlit non conserva st.session_state).
    _pkce_store()[state] = verifier
    st.session_state[f"_pkce_{state}"] = verifier
    auth_url = spotify_pkce.build_auth_url(
        client_id=settings.spotify_client_id,
        redirect_uri=settings.spotify_redirect_uri,
        state=state,
        challenge=challenge,
    )
    # NB: Spotify Accounts rifiuta di aprirsi dentro frame/webview annidati e
    # molti ambienti (webview, preview) bloccano anche target="_top". Apriamo
    # quindi l'OAuth in una scheda esterna (target="_blank"): il token viene
    # salvato lato server, così la scheda originale lo riprende al refresh.
    stay_logged = container.checkbox(
        "Stay logged in",
        value=bool(_persistent_token_store().get("token") or st.session_state.get("sp_stay_logged")),
        key="sp_stay_logged",
    )
    # Salva la preferenza nel server store DOPO il checkbox, così sopravvive
    # al redirect OAuth che azzera st.session_state.
    _stay_logged_store()[state] = stay_logged
    container.markdown(
        f'<a href="{html.escape(auth_url)}" target="_blank" rel="noopener noreferrer" '
        'style="display:block;text-align:center;padding:10px 14px;'
        'border-radius:10px;font-weight:700;text-decoration:none;'
        'color:#04150b;background:linear-gradient(100deg,#1db954,#2de26d);'
        'box-shadow:0 0 14px rgba(29,185,84,.35);">'
        '🔑 Log in with your Spotify account</a>',
        unsafe_allow_html=True,
    )
    container.caption(
        "Spotify login opens in a new browser tab. After approving access, "
        "come back here or refresh this tab."
    )


# --------------------------------------------------------------------------- #
# Studio: regia audio-narrata a 3 colonne
# --------------------------------------------------------------------------- #
def empty_studio(prompt: str) -> dict:
    """Struttura vuota della regia (usata quando manca l'LLM o non ci sono brani)."""
    return {"prompt": prompt, "tracks": [], "summary": "", "moods": []}


def build_studio(
    prompt: str,
    tracks: list[dict[str, str]],
    lang_name: str,
    lang_code: str,
) -> dict:
    """Arricchisce i brani con: discorso parlato, immagine artista, id Spotify e geo."""
    enriched: list[dict] = [dict(t) for t in tracks]
    summary = ""
    moods: list[str] = []

    translation_lang = musixmatch_translation_code(lang_name, lang_code)

    # 1) Pre-fetch in PARALLELO (task 9) per ogni brano: correzione metadati Musixmatch,
    #    testo/richsync/traduzione, bio (AudioDB -> Last.fm) e immagine artista.
    #    La catena Musixmatch -> AudioDB resta SEQUENZIALE dentro ogni worker (il nome
    #    artista canonico serve alla bio), ma i brani sono elaborati in parallelo.
    #    Ogni worker crea client propri: niente requests.Session condivise tra thread.
    def enrich_track(t: dict) -> None:
        artist = t.get("artist", "")
        title = t.get("title", "")
        mx = MusixmatchClient() if settings.musixmatch_ready else None

        # 1a) Musixmatch: valida e corregge titolo+artista con i dati canonici,
        #     poi recupera il testo. Va PRIMA di AudioDB così usiamo il nome
        #     artista corretto anche per la bio.
        if mx and title:
            try:
                track_id = t.get("track_id")
                best = mx.get_track(int(track_id)) if track_id else None
                if not best:
                    matches = mx.search_tracks(track=title, artist=artist, has_lyrics=True, limit=1)
                    best = matches[0] if matches else None
                if best:
                    t["title"] = best.track_name or title
                    t["artist"] = best.artist_name or artist
                    t["album"] = best.album_name
                    t["track_id"] = str(best.track_id)
                    t["has_lyrics"] = best.has_lyrics
                    t["has_richsync"] = best.has_richsync
                    artist = t["artist"]  # nome canonico per AudioDB / Last.fm
                    title = t["title"]
                    if not t.get("lyrics") and not t.get("richsync"):
                        lyrics_text, richsync_body, translated_text = fetch_musixmatch_text(
                            mx,
                            best.track_id,
                            best.has_lyrics,
                            best.has_richsync,
                            translation_lang=translation_lang,
                        )
                        t["lyrics"] = lyrics_text
                        t["richsync"] = richsync_body
                        t["translated_lyrics"] = translated_text
                        t["translation_lang"] = translation_lang
                    elif not t.get("translated_lyrics"):
                        try:
                            translation = mx.get_lyrics_translation(
                                best.track_id,
                                translation_lang,
                            )
                            t["translated_lyrics"] = (
                                translation.body
                                if translation and not translation.is_empty
                                else ""
                            )
                            t["translation_lang"] = translation_lang
                        except MusixmatchError:
                            t.setdefault("translated_lyrics", "")
                            t.setdefault("translation_lang", translation_lang)
                else:
                    t.setdefault("lyrics", "")
                    t.setdefault("richsync", [])
            except MusixmatchError:
                t.setdefault("lyrics", "")
                t.setdefault("richsync", [])

        # 1b) Bio + immagine da AudioDB (usa il nome artista già corretto da Musixmatch)
        bio = ""
        if settings.audiodb_ready and artist:
            try:
                a = AudioDBClient().get_artist(artist)
                if a:
                    bio = a.biography(lang_code) or ""
                    t["image"] = a.image_url
            except AudioDBError:
                pass

        # 1c) Fallback bio da Last.fm
        if not bio and settings.lastfm_ready and artist:
            try:
                bio = LastFMClient().get_biography(name=artist, lang=lang_code) or ""
            except LastFMError:
                pass

        t["_bio"] = bio  # campo temporaneo letto da studio_brief(), rimosso dopo

    if enriched:
        with ThreadPoolExecutor(max_workers=min(8, len(enriched))) as executor:
            list(executor.map(enrich_track, enriched))

    # 2) Discorsi parlati + mood + origine geografica + riassunto (una sola chiamata LLM).
    #    I track dict includono ora _bio e lyrics, usati da studio_brief().
    if settings.llm_ready:
        try:
            brief = Storyteller(model=selected_llm_model()).studio_brief(
                title=prompt, tracks=enriched, language=lang_name
            )
        except StorytellerError:
            brief = {}
        narrations = brief.get("narrations") or []
        for i, t in enumerate(enriched):
            n = narrations[i] if i < len(narrations) else {}
            t["speech"] = str(n.get("speech", "")).strip()
            t["mood"] = str(n.get("mood", "")).strip()
            t["origin"] = str(n.get("origin", "")).strip()
            try:
                t["lat"] = float(n.get("lat"))
            except (TypeError, ValueError):
                t["lat"] = None
            try:
                t["lng"] = float(n.get("lng"))
            except (TypeError, ValueError):
                t["lng"] = None
        summary = str(brief.get("summary", "")).strip()
        moods = [str(m).strip() for m in (brief.get("moods") or []) if str(m).strip()]

    # 3) Rimuovi il campo temporaneo e imposta i default per i campi mancanti.
    # NB: la risoluzione del brano su Spotify avviene lato browser (flusso PKCE).
    for t in enriched:
        t.pop("_bio", None)
        t.setdefault("speech", "")
        t.setdefault("mood", "")
        t.setdefault("origin", "")
        t.setdefault("lat", None)
        t.setdefault("lng", None)
        t.setdefault("image", "")
        t.setdefault("audio_b64", "")
        t.setdefault("lyrics", "")
        t.setdefault("translated_lyrics", "")
        t.setdefault("translation_lang", translation_lang)
        t.setdefault("richsync", [])

    # 4) Task 1: l'audio di narrazione ElevenLabs NON viene piu' pre-generato qui per
    #    tutti i brani. Viene prodotto on-demand, UN clip alla volta, solo quando si
    #    preme Play (o quando "Play All" raggiunge quel brano), tramite l'endpoint TTS
    #    locale (vedi core/tts_server.py e render_studio_component). Il client del
    #    browser scarica e mette in cache l'audio appena prima della riproduzione.

    return {"prompt": prompt, "tracks": enriched, "summary": summary, "moods": moods}


STUDIO_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:ital,wght@0,400;0,500;1,400&family=JetBrains+Mono:wght@400;600&display=swap');
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { font-family: 'Inter', 'Segoe UI', sans-serif; color: #e8e6f5; background: transparent; }

  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(249,115,22,.35); border-radius: 8px; }

  .bar {
    display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
  }
  .bar button {
    font-family: 'Space Grotesk', sans-serif; font-weight: 700;
    border: 0; border-radius: 12px; padding: 9px 18px; cursor: pointer;
    color: #fff; background: linear-gradient(100deg, #ff2d78, #f97316);
    box-shadow: 0 0 18px rgba(255,45,120,.35); font-size: .95rem;
    transition: transform .15s ease, filter .15s ease, box-shadow .15s ease;
  }
  .bar button:hover { transform: translateY(-1px); filter: brightness(1.08); box-shadow: 0 0 26px rgba(249,115,22,.5); }
  .bar button.ghost {
    background: rgba(249,115,22,.10); color: #ffd9b0; border: 1px solid rgba(249,115,22,.4);
    box-shadow: none;
  }
  .bar button.ghost.on {
    background: linear-gradient(100deg, #22d3ee, #c2410c); color: #fff; border: 0;
    box-shadow: 0 0 18px rgba(34,211,238,.4);
  }
  #status { margin-left: auto; font-family: 'JetBrains Mono', monospace; color: #8f8aa8; font-size: .8rem; }

  .cols {
    display: grid; grid-template-columns: 0.95fr 1.55fr 1.05fr; gap: 16px;
    height: 720px;
  }
  .col {
    background: linear-gradient(165deg, rgba(255,255,255,.05), rgba(255,255,255,.02));
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px; padding: 14px; overflow-y: auto;
    box-shadow: 0 10px 30px rgba(0,0,0,0.35);
    backdrop-filter: blur(10px);
  }
  .col-h {
    font-family: 'JetBrains Mono', monospace; font-weight: 600;
    margin-bottom: 10px; color: #22d3ee;
    text-transform: uppercase; letter-spacing: .22em; font-size: .68rem;
    border-bottom: 1px solid rgba(255,255,255,.08); padding-bottom: 8px;
  }

  .ti {
    display: flex; align-items: center; gap: 10px; padding: 9px 10px;
    border-radius: 12px; margin-bottom: 8px; cursor: pointer;
    border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,.03);
    transition: transform .12s ease, box-shadow .12s ease, border-color .12s ease;
  }
  .ti:hover { transform: translateY(-1px); border-color: rgba(249,115,22,.4); box-shadow: 0 8px 18px rgba(249,115,22,.15); }
  .ti.active {
    background: rgba(249,115,22,.12); border-color: rgba(249,115,22,.55);
    box-shadow: 0 0 18px rgba(249,115,22,.25);
  }
  .ti-play {
    flex: 0 0 auto; width: 30px; height: 30px; border-radius: 50%; border: 0;
    cursor: pointer; color: #fff; font-size: .8rem; line-height: 30px;
    box-shadow: 0 0 10px rgba(0,0,0,.4);
  }
  .ti-body { overflow: hidden; }
  .ti-title {
    font-family: 'Space Grotesk', sans-serif; font-weight: 600; color: #f3f1ff;
    font-size: .92rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .ti-artist { color: #8f8aa8; font-size: .8rem; }
  .ti-open {
    flex: 0 0 auto; margin-left: auto; color: #1db954; text-decoration: none;
    font-size: 1rem; font-weight: 700; padding: 2px 7px; border-radius: 8px;
    opacity: .7; transition: opacity .12s ease, background .12s ease;
  }
  .ti-open:hover { opacity: 1; background: rgba(29,185,84,.14); }

  #center-empty {
    height: 100%; display: flex; align-items: center; justify-content: center;
    text-align: center; color: #8f8aa8; font-size: 1.05rem; padding: 0 24px;
  }
  #c-img {
    width: 100%; max-height: 230px; object-fit: cover; border-radius: 14px;
    margin-bottom: 14px; box-shadow: 0 10px 26px rgba(0,0,0,.45);
    border: 1px solid rgba(255,255,255,.08);
  }
  #c-title {
    font-family: 'Space Grotesk', sans-serif; font-weight: 700;
    font-size: 1.7rem; line-height: 1.1; margin-bottom: 4px;
    background: linear-gradient(95deg, #ff2d78, #f97316 60%, #22d3ee); -webkit-background-clip: text;
    background-clip: text; -webkit-text-fill-color: transparent;
  }
  #c-meta { color: #8f8aa8; font-family: 'JetBrains Mono', monospace; font-size: .8rem; margin-bottom: 14px; }
  #c-speech { font-size: 1.05rem; line-height: 1.75; color: #c9c5dd; }

  #player { text-align: center; }
  #p-msg { color: #8f8aa8; font-size: .78rem; margin-top: 10px; }
  #sp-embed {
    width: 100%; height: 152px; border: 0; border-radius: 12px; margin-top: 12px;
    background: rgba(255,255,255,.04);
  }
  #p-open {
    display: none; margin-top: 8px; color: #1db954; font-size: .82rem;
    text-decoration: none; font-weight: 600;
  }
  #need-login { color: #8f8aa8; font-size: .9rem; padding: 12px 4px; }

  /* ---- Player column + Lyrics panel ---- */
  #player-col { display: flex; flex-direction: column; overflow: hidden; }
  #lyrics-section { margin-top: 14px; display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }
  #lyrics-box {
    flex: 1 1 auto; min-height: 160px; overflow-y: auto; padding: 10px 14px;
    background: rgba(255,255,255,.03); border-radius: 12px;
    border: 1px solid rgba(255,255,255,.08); scroll-behavior: smooth;
  }
  .lyr-empty { color: #6f6a85; font-size: .82rem; font-style: italic; padding: 6px; }
  .lyr-line {
    font-size: .86rem; line-height: 1.55; color: #8f8aa8;
    padding: 7px 8px; border-radius: 8px; margin-bottom: 4px;
    transition: color .35s ease, background .35s ease;
  }
  .lyr-line.active { color: #f3f1ff; font-weight: 600; background: rgba(249,115,22,.12); }
  .lyr-translated { color: #f3f1ff; font-size: .92rem; line-height: 1.45; }
  .lyr-original { color: #8f8aa8; font-size: .72rem; line-height: 1.35; margin-top: 2px; opacity: .82; }
  .lyr-line.active .lyr-original { color: #b6b0ca; }
  .lyr-word.active { color: #facc15; text-shadow: 0 0 10px rgba(250,204,21,.35); }
</style>
</head>
<body>
  <div class="bar">
    <button id="playAll">&#9654; Play</button>
    <button id="shuffle" class="ghost">&#128256; Shuffle</button>
    <span id="status">Ready</span>
  </div>
  <div class="cols">
    <div class="col">
      <div class="col-h">Tracks found</div>
      <div id="list"></div>
    </div>
    <div class="col">
      <div id="center-empty">Press &#9654; Play, or choose a track on the left.<br>Click on the title to read the speech without voice.</div>
      <div id="center-content" style="display:none">
        <img id="c-img"/>
        <div id="c-title"></div>
        <div id="c-meta"></div>
        <div id="c-speech"></div>
      </div>
    </div>
    <div class="col" id="player-col">
      <div class="col-h">Player</div>
      <div id="need-login" style="display:none">Log in to your Spotify in the sidebar to enable the player and playback.</div>
      <div id="player" style="display:none">
        <div id="p-msg">Starting player&hellip;</div>
                <div id="sp-embed"></div>
        <a id="p-open" target="_blank" rel="noopener">Open this track on Spotify</a>
      </div>
      <div id="lyrics-section" style="display:none;">
        <div class="col-h" style="margin-top:12px;">Lyrics</div>
        <div id="lyrics-box"></div>
      </div>
    </div>
  </div>

<script>
  const TRACKS = __TRACKS__;
  const TTSLANG = __TTSLANG__;
  const TOKEN = __TOKEN__;
  const PLAYLIST_NAME = __PLAYLIST__;
  // Task 1: endpoint TTS locale per generare la narrazione ElevenLabs ON-DEMAND,
  // un clip alla volta. Vuoto => fallback alla Web Speech API del browser.
  const TTS_ENDPOINT = __TTS_ENDPOINT__;
  const TTS_TOKEN = __TTS_TOKEN__;
  // Task 2: tolleranza (secondi) per l'allineamento del richsync (anticipo highlight).
  const LYRIC_OFFSET = 0.18;
  const PALETTE = ["#ff2d78","#f97316","#22d3ee","#facc15","#c2410c","#34d399"];

    let embedController = null;
    let pendingUri = '';
    let embedReady = false;
    let embedPlayed = false;
    let embedPosition = 0;
    let embedDuration = 0;
    let embedPaused = true;
    let lastPlaybackUpdateTs = Date.now();
  let currentAudio = null;
  let shuffleOn = false;
  let autoSeq = false;
  let awaitingEnd = false;
  let order = [];
  let seqPos = 0;
  let current = -1;

  const statusEl = document.getElementById('status');
  const listEl = document.getElementById('list');
  const emptyEl = document.getElementById('center-empty');
  const contentEl = document.getElementById('center-content');
  const cImg = document.getElementById('c-img');
  const cTitle = document.getElementById('c-title');
  const cMeta = document.getElementById('c-meta');
  const cSpeech = document.getElementById('c-speech');
  const pMsg = document.getElementById('p-msg');

  function setStatus(s) { statusEl.textContent = s; }
  function setPMsg(s) { pMsg.textContent = s; }

  function esc(s) {
    const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML;
  }

  function spotifyTrackId(uri) {
    const m = String(uri || '').match(/spotify:track:([A-Za-z0-9]+)/);
    return m ? m[1] : '';
  }

  function trackSpotifyLink(t) {
    const id = spotifyTrackId(t.uri);
    if (id) return 'https://open.spotify.com/track/' + id;
    return 'https://open.spotify.com/search/' + encodeURIComponent(((t.title || '') + ' ' + (t.artist || '')).trim());
  }

  function showSpotifyEmbed(uri) {
    const id = spotifyTrackId(uri);
    if (!id) return;
    const open = document.getElementById('p-open');
        const trackUri = 'spotify:track:' + id;
        pendingUri = trackUri;
        if (embedController && embedReady) {
            embedController.loadUri(trackUri);
        }
    open.href = 'https://open.spotify.com/track/' + id;
    open.style.display = 'inline-block';
  }

  async function prepareTrackPlayer(i) {
    const t = TRACKS[i];
        if (t.uri) {
            showSpotifyEmbed(t.uri);
            setPMsg(embedReady ? 'Spotify player ready ✓' : 'Loading Spotify player…');
            return;
        }
        if (!TOKEN) {
            setPMsg('Spotify URI not available for this track. Log in to resolve it automatically.');
            return;
        }
        const uri = await resolveUri(t);
        if (current !== i) return;
        if (uri) {
            showSpotifyEmbed(uri);
            setPMsg(embedReady ? 'Spotify player ready ✓' : 'Loading Spotify player…');
        } else {
            setPMsg('Track not found on Spotify.');
        }
  }

  // ---- Lista brani ----
  TRACKS.forEach((t, i) => {
    const color = PALETTE[i % PALETTE.length];
    const row = document.createElement('div');
    row.className = 'ti'; row.dataset.i = i;
    row.innerHTML =
      '<button class="ti-play" style="background:' + color + '">&#9654;</button>' +
      '<div class="ti-body">' +
        '<div class="ti-title">' + (i+1) + '. ' + esc(t.title) + '</div>' +
        '<div class="ti-artist">' + esc(t.artist) + (t.mood ? ' &middot; ' + esc(t.mood) : '') + '</div>' +
      '</div>' +
      '<a class="ti-open" href="' + trackSpotifyLink(t) + '" target="_blank" rel="noopener" title="Open on Spotify">&#8599;</a>';
    row.querySelector('.ti-play').addEventListener('click', (e) => {
      e.stopPropagation(); autoSeq = false; runTrack(i, true, false);
    });
    row.querySelector('.ti-body').addEventListener('click', () => {
      autoSeq = false; stopAudio(); runTrack(i, false, false);
    });
    row.querySelector('.ti-open').addEventListener('click', (e) => { e.stopPropagation(); });
    listEl.appendChild(row);
  });

  function highlight(i) {
    document.querySelectorAll('.ti').forEach(el => {
      el.classList.toggle('active', parseInt(el.dataset.i) === i);
    });
  }

  function showCenter(i) {
    const t = TRACKS[i];
    emptyEl.style.display = 'none';
    contentEl.style.display = 'block';
    if (t.image) { cImg.src = t.image; cImg.style.display = 'block'; }
    else { cImg.style.display = 'none'; }
    cTitle.textContent = t.title;
    const bits = [t.artist];
    if (t.origin) bits.push('📍 ' + t.origin);
    if (t.mood) bits.push(t.mood);
    cMeta.textContent = bits.filter(Boolean).join('  ·  ');
    cSpeech.textContent = t.speech || (t.reason || 'No speech available for this track.');
    showLyrics(i);
    prepareTrackPlayer(i);
  }

  // ---- Lyrics ----
  function richsyncLineText(item) {
    const line = item && (item.l || item.line || item.text || '');
    if (Array.isArray(line)) {
      return line.map(token => {
        if (token && typeof token === 'object') return token.c || token.text || '';
        return String(token || '');
      }).join('').trim();
    }
    return String(line || '').trim();
  }

  function cleanLyricLines(text) {
    return String(text || '').split('\\n')
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('****') && !l.toLowerCase().includes('commercial use'));
  }

  // Task 2: nessun player di testi sincronizzati ufficiale è esposto dalle API
  // pubbliche (lo Spotify Embed riproduce il brano ufficiale ma NON fornisce i
  // testi sincronizzati; Musixmatch non offre un player embeddabile pubblico).
  // Quindi NON si finge la sincronia: si usa il richsync Musixmatch SOLO se i
  // suoi tempi sono affidabili, altrimenti si ripiega su testo riga-per-riga.
  function richsyncTimingOk(richsync) {
    let prev = -1, valid = 0, monotonic = true, maxTs = 0;
    for (const item of richsync) {
      const rawTs = (item && (item.ts != null ? item.ts : item.start));
      const ts = Number(rawTs);
      if (rawTs == null || !Number.isFinite(ts)) continue;
      valid++;
      if (ts + 0.001 < prev) monotonic = false;
      prev = ts;
      if (ts > maxTs) maxTs = ts;
    }
    // Servono abbastanza righe temporizzate, in ordine, su un arco > 1s.
    return valid >= 4 && monotonic && maxTs > 1;
  }

  function showLyrics(i) {
    const t = TRACKS[i];
    const section = document.getElementById('lyrics-section');
    const box = document.getElementById('lyrics-box');
    section.style.display = 'flex';
    const richsync = Array.isArray(t.richsync) ? t.richsync : [];
    const translatedLines = cleanLyricLines(t.translated_lyrics);

    // 1) Richsync di buona qualità -> sincronia parola/riga.
    if (richsync.length && richsyncTimingOk(richsync)) {
      box.innerHTML = richsync.map((item, idx) => {
        const originalText = richsyncLineText(item);
        if (!originalText) return '';
        const translatedText = translatedLines[idx] || originalText;
        const start = Number(item.ts != null ? item.ts : (item.start || 0));
        const end = Number(item.te != null ? item.te : (item.end || 0));
        const line = item.l || item.line || item.text || '';
        let originalHtml = esc(originalText);
        if (Array.isArray(line)) {
          originalHtml = line.map((token, wordIdx) => {
            const raw = token && typeof token === 'object' ? (token.c || token.text || '') : String(token || '');
            const offset = token && typeof token === 'object' ? Number(token.o || token.offset || 0) : 0;
            return '<span class="lyr-word" data-offset="' + offset + '" data-word="' + wordIdx + '">' + esc(raw) + '</span>';
          }).join('');
        }
        return '<div class="lyr-line" data-idx="' + idx + '" data-start="' + start + '" data-end="' + end + '">' +
          '<div class="lyr-translated">' + esc(translatedText) + '</div>' +
          '<div class="lyr-original">' + originalHtml + '</div>' +
        '</div>';
      }).join('');
      return;
    }

    // 2) Richsync presente ma con tempi inaffidabili -> righe senza timestamp
    //    (sincronia proporzionale, niente highlight di parole fasullo).
    if (richsync.length) {
      const lines = richsync.map(it => richsyncLineText(it)).filter(Boolean);
      if (lines.length) {
        box.innerHTML = lines.map((l, idx) =>
          '<div class="lyr-line" data-idx="' + idx + '">' +
            '<div class="lyr-translated">' + esc(translatedLines[idx] || l) + '</div>' +
            '<div class="lyr-original">' + esc(l) + '</div>' +
          '</div>'
        ).join('');
        return;
      }
    }

    // 3) Solo testo semplice (line-level / plain).
    if (!t.lyrics || !t.lyrics.trim()) {
      box.innerHTML = '<div class="lyr-empty">Synced lyrics unavailable for this track. Open it on Spotify for official synced lyrics.</div>';
      return;
    }
    const originalLines = cleanLyricLines(t.lyrics);
    box.innerHTML = originalLines.map((l, idx) =>
      '<div class="lyr-line" data-idx="' + idx + '">' +
        '<div class="lyr-translated">' + esc(translatedLines[idx] || l) + '</div>' +
        '<div class="lyr-original">' + esc(l) + '</div>' +
      '</div>'
    ).join('');
  }

  function syncLyrics(position, duration) {
    const box = document.getElementById('lyrics-box');
    const lines = box.querySelectorAll('.lyr-line');
    if (!lines.length || !duration) return;
    const pos = position > 1000 ? position / 1000 : position;
    const dur = duration > 1000 ? duration / 1000 : duration;
    // Anticipa leggermente l'highlight per compensare la latenza del playback_update.
    const adj = pos + LYRIC_OFFSET;
    let idx = -1;
    let latestTimedIdx = -1;
    let hasTimedLines = false;
    lines.forEach((el, i) => {
      const start = Number(el.dataset.start);
      const end = Number(el.dataset.end);
      const hasStart = el.dataset.start !== undefined && el.dataset.start !== '' && !Number.isNaN(start);
      const hasEnd = el.dataset.end !== undefined && !Number.isNaN(end) && end > start;
      if (hasStart) {
        hasTimedLines = true;
        if (adj >= start) latestTimedIdx = i;
        // Finestra con tolleranza per assorbire piccoli disallineamenti del richsync.
        if (adj >= start && (!hasEnd || adj <= end + LYRIC_OFFSET)) idx = i;
      }
    });
    if (idx < 0 && latestTimedIdx >= 0) idx = latestTimedIdx;
    if (idx < 0 && !hasTimedLines) idx = Math.min(Math.floor((pos / dur) * lines.length), lines.length - 1);
    if (idx < 0) return;
    let changed = false;
    lines.forEach((el, i) => {
      const was = el.classList.contains('active');
      el.classList.toggle('active', i === idx);
      if (i === idx) {
        const start = Number(el.dataset.start) || 0;
        el.querySelectorAll('.lyr-word').forEach(word => {
          const offset = Number(word.dataset.offset || 0);
          word.classList.toggle('active', adj >= start + offset);
        });
      } else {
        el.querySelectorAll('.lyr-word').forEach(word => word.classList.remove('active'));
      }
      if (!was && i === idx) changed = true;
    });
    if (changed && lines[idx]) lines[idx].scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  // ---- Spotify Web API helpers (token personale dell'utente) ----
  function api(path, opts) {
    return fetch('https://api.spotify.com/v1' + path, Object.assign({
      headers: { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' }
    }, opts || {}));
  }

  function normalizeMeta(s) {
    return String(s || '')
      .toLowerCase()
      .replace(/[\\(\\[].*?[\\)\\]]/g, ' ')
      .replace(/\\s-\\s.*$/, ' ')
      .replace(/\\b(feat|ft|featuring|with)\\b.*$/, ' ')
      .replace(/[^\\w\\s]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
  }

  function scoreCandidate(it, title, artist) {
    const wantT = normalizeMeta(title);
    const wantA = normalizeMeta(artist);
    const candT = normalizeMeta(it.name);
    const candA = normalizeMeta((it.artists || []).map(a => a.name).join(' '));
    let s = 0;
    if (wantT && wantT === candT) s += 0.6;
    else if (wantT && (candT.indexOf(wantT) >= 0 || wantT.indexOf(candT) >= 0)) s += 0.4;
    if (wantA) {
      if (wantA === candA) s += 0.4;
      else if (candA.indexOf(wantA) >= 0 || wantA.indexOf(candA) >= 0) s += 0.25;
    } else { s += 0.2; }
    s += Math.min(it.popularity || 0, 100) / 1000.0;
    return s;
  }

  // Task 4: risolve l'URI Spotify usando i metadati canonici (titolo/artista corretti
  // da Musixmatch) con più tentativi e scelta del candidato più simile, per ridurre i
  // brani "non trovati".
  async function resolveUri(t) {
    if (t.uri) return t.uri;
    if (!TOKEN) return '';
    const title = (t.title || '').trim();
    const artist = (t.artist || '').trim();
    if (!title) return '';
    const queries = [];
    if (artist) {
      queries.push('track:"' + title + '" artist:"' + artist + '"');
      queries.push(title + ' ' + artist);
    }
    queries.push('track:"' + title + '"');
    queries.push(title);
    let best = null, bestScore = 0;
    for (const query of queries) {
      try {
        const r = await api('/search?type=track&limit=5&q=' + encodeURIComponent(query));
        if (!r.ok) continue;
        const d = await r.json();
        const items = (d.tracks && d.tracks.items) || [];
        for (const it of items) {
          if (!it.uri) continue;
          const sc = scoreCandidate(it, title, artist);
          if (sc > bestScore) { best = it; bestScore = sc; }
        }
        if (bestScore >= 0.9) break;
      } catch (e) {}
    }
    if (best && bestScore >= 0.4) {
      t.uri = best.uri;
      const img = best.album && best.album.images && best.album.images[0];
      if (img) { t.art = img.url; if (!t.image) t.image = img.url; }
      return t.uri;
    }
    return '';
  }

  // ---- Audio: voce (ElevenLabs MP3 o Web Speech fallback) + Spotify ----
  function stopAudio() {
    try { window.speechSynthesis.cancel(); } catch (e) {}
    if (currentAudio) {
      try { currentAudio.pause(); currentAudio.currentTime = 0; } catch (e) {}
      currentAudio = null;
    }
    awaitingEnd = false;
        if (embedController && embedReady) {
            try { embedController.pause(); } catch (e) {}
        }
  }

  function arrayBufferToB64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  // Task 1: genera (lazy) l'audio di narrazione per UN brano chiamando l'endpoint
  // TTS locale ElevenLabs. Il server mette in cache per hash del testo, quindi il
  // riascolto non rigenera. Ritorna base64 oppure '' (fallback Web Speech).
  async function fetchTtsB64(text) {
    if (!TTS_ENDPOINT || !text) return '';
    try {
      const r = await fetch(TTS_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Sonder-TTS-Token': TTS_TOKEN },
        body: JSON.stringify({ text: text })
      });
      if (!r.ok) return '';
      const buf = await r.arrayBuffer();
      return arrayBufferToB64(buf);
    } catch (e) { return ''; }
  }

  // speak(track, onend): genera/riproduce la narrazione del brano UNA alla volta.
  // L'audio è prodotto SOLO ora (lazy) e messo in cache su track.audio_b64.
  async function speak(track, onend) {
    // Stop anything currently playing.
    try { window.speechSynthesis.cancel(); } catch (e) {}
    if (currentAudio) { try { currentAudio.pause(); } catch (e) {} currentAudio = null; }

    const text = (track && track.speech) || '';
    let audioB64 = (track && track.audio_b64) || '';

    // Genera l'audio ElevenLabs appena prima della riproduzione (lazy, on-demand).
    if (!audioB64 && text && TTS_ENDPOINT) {
      setStatus('🗣️ Generating narration…');
      audioB64 = await fetchTtsB64(text);
      if (audioB64 && track) track.audio_b64 = audioB64;  // cache per non rigenerare
    }

    if (audioB64) {
      const audio = new Audio('data:audio/mpeg;base64,' + audioB64);
      currentAudio = audio;
      audio.onended = () => { currentAudio = null; onend && onend(); };
      audio.onerror = () => { currentAudio = null; onend && onend(); };
      audio.play().catch(() => { currentAudio = null; onend && onend(); });
      return;
    }

    // Fallback: browser Web Speech API (anch'esso lazy, nessuna pre-generazione).
    if (!text) { onend && onend(); return; }
    const u = new SpeechSynthesisUtterance(text);
    if (TTSLANG) u.lang = TTSLANG;
    u.rate = 0.98; u.pitch = 1.0;
    u.onend = () => onend && onend();
    u.onerror = () => onend && onend();
    window.speechSynthesis.speak(u);
  }

  async function startSong(i, seq) {
        const t = TRACKS[i];
        let uri = t.uri || '';
        if (!uri && TOKEN) {
            setStatus('🔎 Searching for track on Spotify…');
            uri = await resolveUri(t);
        }
    if (!uri) { setStatus('Track not found on Spotify'); if (seq) setTimeout(advance, 1500); return; }
        showSpotifyEmbed(uri);
        if (embedController && embedReady) {
            embedPlayed = false;
            embedPosition = 0;
            embedDuration = 0;
            embedPaused = true;
            try {
                embedController.play();
                setStatus('🎧 Playing on Spotify embed…');
                if (seq) awaitingEnd = true;
            } catch (e) {
                setStatus('Track loaded in Spotify player');
                if (seq) setTimeout(advance, 2500);
            }
        } else {
            setStatus('Track loaded in Spotify player');
            if (seq) setTimeout(advance, 2500);
    }
  }

  function runTrack(i, withVoice, seq) {
    current = i;
    highlight(i);
    showCenter(i);
    if (withVoice) {
      setStatus('🗣️ Narrating…');
      speak(TRACKS[i], () => startSong(i, seq));
    }
  }

  function advance() {
    awaitingEnd = false;
    seqPos += 1;
    if (autoSeq && seqPos < order.length) {
      runTrack(order[seqPos], true, true);
    } else {
      autoSeq = false;
      setStatus('✦ End of playlist');
    }
  }

  function shuffleArray(a) {
    for (let k = a.length - 1; k > 0; k--) {
      const j = Math.floor(Math.random() * (k + 1));
      [a[k], a[j]] = [a[j], a[k]];
    }
    return a;
  }

  document.getElementById('playAll').addEventListener('click', () => {
    if (!TRACKS.length) return;
    stopAudio();
    order = TRACKS.map((_, i) => i);
    if (shuffleOn) shuffleArray(order);
    autoSeq = true; seqPos = 0;
    runTrack(order[0], true, true);
  });

  document.getElementById('shuffle').addEventListener('click', (e) => {
    shuffleOn = !shuffleOn;
    e.currentTarget.classList.toggle('on', shuffleOn);
    setStatus(shuffleOn ? '🔀 Shuffle on' : 'Ready');
  });

    // ---- Spotify Embed IFrame API (player ufficiale Spotify) ----
    window.onSpotifyIframeApiReady = (IFrameAPI) => {
        const host = document.getElementById('sp-embed');
        if (!host) return;
        IFrameAPI.createController(host, {
            width: '100%',
            height: '152',
            uri: pendingUri || 'spotify:track:4uLU6hMCjMI75M1A2tKUQC'
        }, (controller) => {
            embedController = controller;
            embedReady = true;
            setPMsg('Spotify player ready ✓');
            controller.addListener('playback_update', onState);
            if (pendingUri) {
                try { controller.loadUri(pendingUri); } catch (e) {}
            }
        });
    };

  function onState(state) {
        if (!state || !state.data) return;
        const d = state.data;
        embedPosition = typeof d.position === 'number' ? d.position : embedPosition;
        embedDuration = typeof d.duration === 'number' ? d.duration : embedDuration;
        embedPaused = !!d.isPaused;
        lastPlaybackUpdateTs = Date.now();
        if (!embedPaused && embedPosition > 0) embedPlayed = true;

        if (current >= 0) syncLyrics(embedPosition, embedDuration);
        if (autoSeq && awaitingEnd && embedPlayed && embedPaused && embedPosition === 0) {
            awaitingEnd = false;
            advance();
        }
  }

  setInterval(() => {
        if (current < 0 || embedPaused || !embedDuration) return;
        const elapsedMs = Date.now() - lastPlaybackUpdateTs;
        const estimatedPosition = embedPosition > 1000
            ? embedPosition + elapsedMs
            : embedPosition + (elapsedMs / 1000);
        syncLyrics(estimatedPosition, embedDuration);
  }, 250);

    // Stato iniziale dell'area player.
    document.getElementById('player').style.display = 'block';
    if (!TOKEN) {
        document.getElementById('need-login').style.display = 'block';
        document.getElementById('need-login').textContent = 'Log in to your Spotify in the sidebar to resolve missing track URIs and enable the player.';
    }
    if (TRACKS.length) {
        current = 0;
        highlight(0);
        showCenter(0);
  }
</script>
<script src="https://open.spotify.com/embed/iframe-api/v1" async></script>
</body>
</html>
"""


def render_studio_component(studio: dict, tts_lang: str) -> None:
    """Renderizza la regia a 3 colonne con sintesi vocale e player Spotify per-utente."""
    tracks = studio.get("tracks", [])
    payload = [
        {
            "title": t.get("title", ""),
            "artist": t.get("artist", ""),
            "speech": t.get("speech", ""),
            "mood": t.get("mood", ""),
            "origin": t.get("origin", ""),
            "reason": t.get("reason", ""),
            "image": t.get("image", ""),
            "uri": t.get("uri", ""),
            "audio_b64": t.get("audio_b64", ""),
            "lyrics": t.get("lyrics", ""),
            "translated_lyrics": t.get("translated_lyrics", ""),
            "translation_lang": t.get("translation_lang", ""),
            "richsync": t.get("richsync", []),
            "track_id": t.get("track_id", ""),
            "album": t.get("album", ""),
        }
        for t in tracks
    ]
    tracks_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    playlist_name = json.dumps(
        f"Sonder · {studio.get('prompt', '')[:60]}", ensure_ascii=False
    )
    token_json = json.dumps(spotify_token())
    # Task 1: avvia l'endpoint TTS locale (loopback) e passa endpoint+token al
    # componente, così il browser può generare la narrazione ElevenLabs on-demand,
    # un clip alla volta. In modalità "embedded" (hosting) o senza chiave restano
    # vuoti e si usa la Web Speech API del browser.
    tts_endpoint = ""
    tts_token = ""
    mode = (getattr(settings, "sonder_tts_mode", "auto") or "auto").lower()
    if settings.elevenlabs_ready and mode != "embedded":
        try:
            info = tts_server.ensure_tts_server()
            tts_endpoint = info.endpoint
            tts_token = info.token
        except tts_server.TTSServerError:
            tts_endpoint = ""
            tts_token = ""
    # I valori sono inseriti come letterali JS: vanno serializzati con json.dumps.
    rendered = (
        STUDIO_HTML.replace("__TRACKS__", tracks_json)
        .replace("__TTSLANG__", json.dumps(tts_lang or ""))
        .replace("__PLAYLIST__", playlist_name)
        .replace("__TOKEN__", token_json)
        .replace("__TTS_ENDPOINT__", json.dumps(tts_endpoint))
        .replace("__TTS_TOKEN__", json.dumps(tts_token))
    )
    components.html(rendered, height=860, scrolling=False)


def render_studio_title(prompt: str) -> None:
    """Mostra, in piccolo sotto il logo, esattamente cio' che l'utente ha scritto in chat."""
    st.markdown(
        f'<div class="studio-prompt">{html.escape(prompt.strip() or "Senza titolo")}</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)


def render_studio_sections(studio: dict) -> None:
    """Sezioni informative sotto la regia: mappa, dettagli, resoconto mood."""
    tracks = studio.get("tracks", [])

    st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)
    st.markdown("### 🗺️ Playlist geography")
    geo = [
        {"lat": t["lat"], "lon": t["lng"]}
        for t in tracks
        if t.get("lat") is not None and t.get("lng") is not None
    ]
    if geo:
        st.map(pd.DataFrame(geo), zoom=1)
        st.caption("Geographic origin of the playlist's artists.")
    else:
        st.caption("Geographic positions not available (requires LLM to be configured).")

    st.markdown("### 🎚️ Track by track details")
    if not tracks:
        st.caption("No tracks yet: details will appear here once the playlist is populated.")
    parts = [
        '<div style="display:grid;'
        'grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;">'
    ]
    for i, t in enumerate(tracks):
        color = PALETTE[i % len(PALETTE)]
        img = (
            f'<img src="{html.escape(t["image"])}" '
            'style="width:100%;height:130px;object-fit:cover;'
            'border-radius:10px;margin-bottom:8px;'
            'border:1px solid rgba(255,255,255,.08);"/>'
            if t.get("image")
            else ""
        )
        origin = (
            f'<div style="color:#8f8aa8;font-size:.85rem;">'
            f'📍 {html.escape(t["origin"])}</div>'
            if t.get("origin")
            else ""
        )
        mood = (
            f'<span class="pill" style="background:{color}1f;'
            f'border:1px solid {color};color:{color};">{html.escape(t["mood"])}</span>'
            if t.get("mood")
            else ""
        )
        reason = (
            f'<div style="color:#c9c5dd;font-size:.9rem;margin-top:6px;">'
            f'{html.escape(t["reason"])}</div>'
            if t.get("reason")
            else ""
        )
        parts.append(
            f'<div class="track-card" style="border-top:4px solid {color};">'
            f'{img}<b>{i + 1}. {html.escape(t.get("title", ""))}</b><br>'
            f'<span>{html.escape(t.get("artist", ""))}</span>'
            f'{origin}<div style="margin-top:6px;">{mood}</div>{reason}</div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)

    st.markdown("### 🌌 Mood summary")
    if studio.get("moods"):
        render_pills(studio["moods"])
    if studio.get("summary"):
        st.markdown(studio["summary"])
    elif not studio.get("moods"):
        st.caption("Summary not available (requires LLM to be configured).")


def _human_number(value: float) -> str:
    """Formatta un numero grande in forma compatta (es. 1.2M, 34K)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"
    for unit, threshold in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= threshold:
            return f"{value / threshold:.1f}{unit}".replace(".0", "")
    return str(int(value))


def render_songstats_section(studio: dict) -> None:
    """Task 8: grafici e statistiche Songstats per i brani/artisti risolti.

    Mostrato a fondo pagina. Gestisce in modo grazioso la mancanza di chiave o gli
    errori (modalità demo). I lookup sono in cache di processo e parallelizzati.
    """
    tracks = studio.get("tracks", [])
    if not tracks:
        return

    st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)
    st.markdown("### 📊 Streaming stats — Songstats")

    if not settings.songstats_ready:
        st.caption(
            "Set `SONGSTATS_API_KEY` in `.env` to show real streaming/popularity "
            "stats here (streams, followers, playlists…)."
        )
        return

    if not settings.spotify_ready:
        st.caption(
            "Songstats stats are looked up by ISRC, resolved via Spotify. "
            "Set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env` to enable them."
        )
        return

    # Riusa le statistiche già allegate dal filtro popolarità; altrimenti recupera
    # in parallelo (cache di processo => nessuna doppia chiamata tra i rerun).
    def get_stats(t: dict) -> dict[str, Any] | None:
        return t.get("songstats") or _songstats_track_stats(
            t.get("title", ""), t.get("artist", "")
        )

    with st.spinner("Loading Songstats…"):
        with ThreadPoolExecutor(max_workers=min(8, len(tracks))) as executor:
            stats_list = list(executor.map(get_stats, tracks))

    rows: list[dict[str, Any]] = []
    any_stats = False
    for t, stats in zip(tracks, stats_list):
        label = f'{t.get("title", "")} — {t.get("artist", "")}'
        if not stats:
            continue
        any_stats = True
        rows.append(
            {
                "Track": label,
                "Streams": int(stats.get("total_streams", 0) or 0),
            }
        )

    if not any_stats:
        st.caption("No Songstats data available for these tracks.")
        return

    # 1) Grafico a barre: stream totali per brano (metrica comparabile).
    df = pd.DataFrame(rows).set_index("Track")
    if not df.empty and df["Streams"].sum() > 0:
        st.markdown("**Total streams per track**")
        st.bar_chart(df, height=320)

    # 2) Dettaglio per brano: metriche principali (streams, followers, playlist…).
    for t, stats in zip(tracks, stats_list):
        if not stats:
            continue
        headline = stats.get("headline") or []
        label = f'{t.get("title", "")} — {t.get("artist", "")}'
        with st.expander(f'📈 {label}  ·  {_human_number(stats.get("total_streams", 0))} streams'):
            if headline:
                cols = st.columns(min(4, len(headline)))
                for idx, (metric_label, metric_value) in enumerate(headline[:8]):
                    with cols[idx % len(cols)]:
                        st.metric(metric_label, _human_number(metric_value))
            else:
                st.caption("No detailed metrics available for this track.")


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
def render_message(index: int, msg: dict) -> None:
    """Renderizza un singolo messaggio della chat (con eventuale playlist)."""
    avatar = "💕" if msg["role"] == "assistant" else None
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

        if msg.get("reasoning"):
            with st.expander("🧠 Model reasoning chain", expanded=False):
                st.markdown(msg["reasoning"])

        tracks = msg.get("tracks") or []
        if tracks:
            st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)
            st.markdown("##### 🎧 Musixmatch tracks")
            render_track_cards(tracks)
            if settings.spotify_ready:
                if st.button(
                    "Create this playlist on Spotify",
                    key=f"spotify_{index}",
                    use_container_width=True,
                ):
                    create_spotify_playlist(tracks, name="Conversation")
            else:
                st.caption("Set `SPOTIFY_CLIENT_ID`/`SECRET` in `.env` to create it on Spotify.")


def init_chat(ui_language: str) -> None:
    """Inizializza (o resetta) la cronologia con il saluto nella lingua scelta."""
    lang_name = LANGUAGES[ui_language][0]
    greeting = GREETINGS.get(lang_name, GREETINGS["Italiano"])
    st.session_state["messages"] = [{"role": "assistant", "content": greeting}]
    st.session_state.pop("studio", None)


def handle_user_input(
    prompt: str,
    lang_name: str,
    lang_code: str,
    search_languages: list[str] | None = None,
) -> None:
    """Elabora il messaggio utente: conversazione + eventuale costruzione dello studio.

    ``search_languages`` (codici EN/IT/FR/...) limita le lingue delle query Musixmatch
    (task 6). Vuoto/None => tutte le lingue.
    """
    st.session_state["messages"].append({"role": "user", "content": prompt})

    # Senza LLM mostriamo comunque la struttura della regia con tab/sezioni vuote.
    if not settings.llm_ready:
        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": "LLM not configured: set `LLM_API_KEY` (and "
                "`LLM_BASE_URL`/`LLM_MODEL`) in `.env` to populate the studio. "
                "Showing empty structure for now.",
            }
        )
        st.session_state["studio"] = empty_studio(prompt)
        return

    teller = Storyteller(model=selected_llm_model())

    with st.spinner("Searching Musixmatch..."):
        try:
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["messages"]
            ]
            plan = teller.plan_musixmatch_search(
                messages=history,
                language=lang_name,
                context=st.session_state.get("context", ""),
                search_languages=search_languages or None,
            )
        except StorytellerError as exc:
            st.session_state["messages"].append(
                {"role": "assistant", "content": user_facing_llm_error(exc)}
            )
            st.session_state["studio"] = empty_studio(prompt)
            return

    if not plan.get("music_related", True):
        key = lang_name if lang_name in REFUSALS else "Italiano"
        st.session_state["messages"].append({"role": "assistant", "content": REFUSALS[key]})
        return

    if not plan.get("needs_search", True):
        with st.spinner("Thinking..."):
            try:
                content, reasoning = teller.converse(
                    messages=[
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state["messages"]
                    ],
                    language=lang_name,
                    context=st.session_state.get("context", ""),
                )
                text, _ = Storyteller.extract_playlist(content)
            except StorytellerError as exc:
                st.session_state["messages"].append(
                    {"role": "assistant", "content": user_facing_llm_error(exc)}
                )
                st.session_state["studio"] = empty_studio(prompt)
                return
        if "[NON_MUSICALE]" in text:
            key = lang_name if lang_name in REFUSALS else "Italiano"
            text = text.replace("[NON_MUSICALE]", "").strip() or REFUSALS[key]
        st.session_state["messages"].append(
            {"role": "assistant", "content": text, "reasoning": reasoning, "tracks": []}
        )
        st.session_state["studio"] = empty_studio(prompt)
        return

    tracks, notes = search_musixmatch_from_plan(plan, lang_name)

    with st.spinner("Rewriting from Musixmatch lyrics..."):
        try:
            text, reasoning = teller.compose_musixmatch_response(
                prompt=prompt,
                tracks=tracks,
                language=lang_name,
                context=st.session_state.get("context", ""),
            )
        except StorytellerError as exc:
            st.session_state["messages"].append(
                {"role": "assistant", "content": user_facing_llm_error(exc), "tracks": tracks}
            )
            st.session_state["studio"] = build_studio(prompt, tracks, lang_name, lang_code) if tracks else empty_studio(prompt)
            return

    if notes:
        text = text + "\n\n" + "\n".join(f"> {note}" for note in notes)

    st.session_state["messages"].append(
        {"role": "assistant", "content": text, "reasoning": reasoning, "tracks": tracks}
    )

    if tracks:
        with st.spinner("Building the narrated studio (speeches, photos, geography)…"):
            st.session_state["studio"] = build_studio(
                prompt, tracks, lang_name, lang_code
            )
    else:
        # Nessun brano suggerito: mostriamo comunque la struttura vuota.
        st.session_state["studio"] = empty_studio(prompt)


def render_example_prompts(lang_name: str = "Auto") -> None:
    """Renders clickable example prompt cards on the startup page."""
    prompts = EXAMPLE_PROMPTS.get(lang_name, EXAMPLE_PROMPTS["Auto"])[:3]
    for i, (icon, text) in enumerate(prompts):
        if st.button(f"{icon}  {text}", key=f"_ex_{i}", use_container_width=True):
            st.session_state["_pending_example"] = text
            st.rerun()


# --------------------------------------------------------------------------- #
# Task 10: consigli di esplorazione basati sugli ascolti reali Spotify
# --------------------------------------------------------------------------- #
def fetch_spotify_top_listening() -> dict[str, Any] | None:
    """Legge i top artisti/brani/generi dell'utente dalla Spotify Web API.

    Richiede lo scope ``user-top-read``. Ritorna ``None`` se non connesso o in caso
    di errore; ritorna ``{"_no_scope": True}`` se il token non ha lo scope (l'utente
    deve rifare il login per concederlo).
    """
    token = spotify_token()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    artists: list[str] = []
    genres: list[str] = []
    tracks: list[str] = []
    try:
        ra = requests.get(
            "https://api.spotify.com/v1/me/top/artists?limit=20&time_range=medium_term",
            headers=headers,
            timeout=10,
        )
        if ra.status_code in (401, 403):
            return {"_no_scope": True}
        if ra.ok:
            for a in ra.json().get("items", []):
                if a.get("name"):
                    artists.append(a["name"])
                genres.extend(a.get("genres", []) or [])
        rt = requests.get(
            "https://api.spotify.com/v1/me/top/tracks?limit=20&time_range=medium_term",
            headers=headers,
            timeout=10,
        )
        if rt.ok:
            for t in rt.json().get("items", []):
                name = t.get("name", "")
                performers = ", ".join(a.get("name", "") for a in t.get("artists", []))
                if name:
                    tracks.append(f"{name} — {performers}".strip(" —"))
    except requests.RequestException:
        return None
    # Dedup generi mantenendo l'ordine.
    seen: set[str] = set()
    genres = [g for g in genres if g and not (g in seen or seen.add(g))]
    if not (artists or tracks or genres):
        return None
    return {"artists": artists, "genres": genres, "tracks": tracks}


def get_spotify_theme_recs(lang_name: str) -> list[str]:
    """Deriva (e mette in cache di sessione) temi narrativi dagli ascolti Spotify."""
    if not settings.llm_ready or not spotify_token():
        return []
    if "sp_theme_recs" in st.session_state:
        return st.session_state["sp_theme_recs"]
    data = fetch_spotify_top_listening()
    if not data or data.get("_no_scope"):
        st.session_state["sp_theme_recs"] = []
        st.session_state["sp_theme_recs_no_scope"] = bool(data and data.get("_no_scope"))
        return []
    try:
        themes = Storyteller(model=selected_llm_model()).suggest_listening_themes(
            artists=data.get("artists", []),
            tracks=data.get("tracks", []),
            genres=data.get("genres", []),
            language=lang_name,
        )
    except StorytellerError:
        themes = []
    st.session_state["sp_theme_recs"] = themes
    return themes


def render_spotify_theme_recs(lang_name: str) -> None:
    """Mostra pulsanti-tema costruiti sugli ascolti reali dell'utente (task 10)."""
    if not spotify_token() or not settings.llm_ready:
        return
    with st.spinner("Reading your Spotify listening…"):
        themes = get_spotify_theme_recs(lang_name)
    if st.session_state.get("sp_theme_recs_no_scope"):
        st.caption(
            "Reconnect Spotify (Disconnect → Login) to grant *top listening* access "
            "and get recommendations based on what you actually listen to."
        )
        return
    if not themes:
        return
    st.markdown("##### 🎧 Inspired by your Spotify listening")
    for i, theme in enumerate(themes):
        if st.button(f"✨  {theme}", key=f"_sprec_{i}", use_container_width=True):
            st.session_state["_pending_example"] = theme
            st.rerun()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:

    logo_icon_solo = _logo_b64("logo_iconsolo.png")

    st.set_page_config(
        page_title="Sonder",
        page_icon=f"data:image/png;base64,{logo_icon_solo}",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Gestisci l'eventuale ritorno dal login Spotify (?code&state) prima di tutto.
    handle_spotify_callback()



    # Sidebar: logo illustrazione
    icon_b64 = _logo_b64("logo_icon.png")
    if icon_b64:
        st.sidebar.markdown(
            f'<div style="text-align:center;padding:6px 0 4px 0;">'  
            f'<img src="data:image/png;base64,{icon_b64}" '
            'style="width:80%;max-width:180px;border-radius:14px;'
            'opacity:.92;"></div>',
            unsafe_allow_html=True,
        )
        st.sidebar.markdown('<hr style="border-color:rgba(255,255,255,.08);margin:6px 0 10px 0;">', unsafe_allow_html=True)

    # Task 5: la lingua di narrazione è SEMPRE auto-rilevata dal modello dalla
    # conversazione. Nessun selettore manuale: usiamo sempre il comportamento "Auto".
    ui_language = "🌐 Auto"
    lang_name, lang_code = LANGUAGES[ui_language]
    st.sidebar.caption(
        "🌍 Narration language: **Auto** — I'll narrate in the language of your message."
    )

    if st.sidebar.button("➕ New chat", use_container_width=True):
        init_chat(ui_language)

    # Sidebar
    render_status_sidebar()
    render_spotify_login(st.sidebar)
    st.sidebar.markdown("---")

    # Contesto musicale opzionale (tool)
    with st.sidebar.expander("🎵 Add song context (optional)"):
        ctx_title = st.text_input("Title", key="ctx_title", placeholder="e.g. Sympathy for the Devil")
        ctx_artist = st.text_input("Artist", key="ctx_artist", placeholder="e.g. The Rolling Stones")
        if st.button("Load context", use_container_width=True):
            ctx, notes = fetch_song_context(ctx_title, ctx_artist, lang_code)
            st.session_state["context"] = ctx
            for n in notes:
                st.warning(n)
            if ctx:
                st.success("Context loaded: I'll use it in upcoming responses.")
        if st.session_state.get("context"):
            st.caption("✅ Context active")
            if st.button("Remove context", use_container_width=True):
                st.session_state["context"] = ""

    render_llm_model_selector()

    # Stato chat
    if "messages" not in st.session_state:
        init_chat(ui_language)

    # Input utente: visibile finche' lo studio non ha brani.
    # Se il modello risponde senza playlist (es. Gemma), la chat rimane aperta.
    studio_has_tracks = bool(
        st.session_state.get("studio") and st.session_state["studio"].get("tracks")
    )

    studio = st.session_state.get("studio")
    has_tracks = bool(studio and studio.get("tracks"))

    # --- Barra superiore: solo il titolo del progetto ---
    logo_b64 = _logo_b64("logo_text.png")
    if logo_b64:
        st.markdown(
            f'<img src="data:image/png;base64,{logo_b64}" '
            'style="height:54px;margin-bottom:2px;display:block;">',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="hero-title">Sonder</div>', unsafe_allow_html=True)

    # --- Intestazione + vista conversazione o regia ---
    if has_tracks:
        # Studio pieno: mostra solo il titolo del prompt e la regia.
        render_studio_title(studio["prompt"])
    else:
        st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)

        # Input + consigli subito dopo il logo, prima dei messaggi.
        if not studio_has_tracks:
            # Task 6: lingue in cui cercare i brani (default = tutte). La selezione
            # persiste tra i rerun tramite la key di sessione.
            label_to_code = dict(SEARCH_LANGUAGE_OPTIONS)
            selected_labels = st.session_state.get("search_lang_labels", [])
            search_languages = [
                label_to_code[label]
                for label in selected_labels
                if label in label_to_code
            ]

            if st.session_state.get("_pending_example"):
                pending = st.session_state.pop("_pending_example")
                handle_user_input(pending, lang_name, lang_code, search_languages)
                if st.session_state.get("studio", {}).get("tracks"):
                    st.rerun()

            typed = st.text_input(
                "",
                placeholder="Type here… what would you like to talk about?",
                key="_main_input",
                label_visibility="collapsed",
            )
            st.multiselect(
                "🌐 Search songs in these languages",
                options=[label for label, _ in SEARCH_LANGUAGE_OPTIONS],
                key="search_lang_labels",
                placeholder="All languages (default)",
                help="Limit the languages used when searching lyrics on Musixmatch. "
                "Leave empty to search in every language.",
            )
            if typed:
                st.session_state.pop("_main_input", None)
                handle_user_input(typed, lang_name, lang_code, search_languages)
                if st.session_state.get("studio", {}).get("tracks"):
                    st.rerun()

            if len(st.session_state.get("messages", [])) <= 1:
                render_spotify_theme_recs(lang_name)
                render_example_prompts(lang_name)

        # Mostra i messaggi della conversazione (indice 0 = saluto iniziale, nascosto).
        for i, msg in enumerate(st.session_state.get("messages", [])):
            if i == 0:
                continue  # saluto iniziale: rimane nel contesto LLM ma non viene mostrato
            render_message(i, msg)

    # --- Regia a 3 colonne (occupa tutta la schermata) ---
    # Mostrata solo quando il modello ha restituito una playlist con brani.
    if has_tracks:
        if not spotify_token():
            st.caption(
                "Log in to your Spotify in the sidebar to enable the player "
                "and add the playlist to your profile."
            )
        render_studio_component(studio, TTS_LANG.get(ui_language, ""))
        # Sezioni informative (scorrendo verso il basso)
        render_studio_sections(studio)
        # Task 8: statistiche e grafici di streaming reali (Songstats) a fondo pagina.
        render_songstats_section(studio)


if __name__ == "__main__":
    main()
