"""Sonder - interfaccia Streamlit.

Entry point dell'applicazione. Orchestra il flusso:
    Musixmatch -> TheAudioDB -> LLM (Thinking) -> Spotify -> UI

L'app si avvia anche senza chiavi API: ogni sezione entra in "modalita' demo"
e indica quale variabile inserire nel file .env.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core.config import LLM_MODEL_OPTIONS, settings
from core.musixmatch_client import MusixmatchClient, MusixmatchError
from core.audiodb_client import AudioDBClient, AudioDBError
from core.lastfm_client import LastFMClient, LastFMError
from core.storyteller import Storyteller, StorytellerError
from core.spotify_client import SpotifyClient, SpotifyError
from core.tts_server import TTSServerError, ensure_tts_server
from core import spotify_pkce

logger = logging.getLogger("sonder.llm")

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

LLM_MODEL_LABELS = {value: label for label, value in LLM_MODEL_OPTIONS}

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


def reset_llm_log() -> None:
    st.session_state["llm_log"] = []


def add_llm_log(step: str, detail: str = "") -> None:
    entries = st.session_state.setdefault("llm_log", [])
    entries.append({"step": step, "detail": detail})
    logger.info("LLM step: %s%s", step, f" | {detail}" if detail else "")


def current_llm_log() -> list[dict[str, str]]:
    return list(st.session_state.get("llm_log") or [])


def llm_model_values() -> list[str]:
    values = [value for _, value in LLM_MODEL_OPTIONS]
    if settings.llm_model and settings.llm_model not in values:
        values.insert(0, settings.llm_model)
    return values


def selected_llm_model() -> str:
    values = llm_model_values()
    selected = st.session_state.get("llm_model") or settings.llm_model
    if selected not in values:
        selected = values[0] if values else settings.llm_model
    st.session_state["llm_model"] = selected
    return selected


def storyteller_for_session() -> Storyteller:
    return Storyteller(model=selected_llm_model())


def render_llm_model_selector() -> None:
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


def render_llm_log(entries: list[dict[str, str]] | None = None) -> None:
    logs = entries if entries is not None else current_llm_log()
    if not logs:
        return
    with st.expander("LLM execution log", expanded=False):
        for index, item in enumerate(logs, start=1):
            step = html.escape(str(item.get("step", "Step")))
            detail = html.escape(str(item.get("detail", ""))).replace("\n", "<br>")
            body = f"<b>{index}. {step}</b>"
            if detail:
                body += f"<br><span style=\"color:#8f8aa8;\">{detail}</span>"
            st.markdown(body, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Tool musicali (contesto + playlist)
# --------------------------------------------------------------------------- #
def fetch_audiodb_track_text(
    client: AudioDBClient,
    *,
    artist: str,
    title: str = "",
    album: str = "",
    lang_code: str = "EN",
) -> str:
    """Recupera contesto TheAudioDB anche con versioni vecchie del client."""
    def clean(text: str, limit: int = 360) -> str:
        text = " ".join((text or "").split())
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."

    def unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = " ".join((value or "").split()).strip(" -–—")
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
        return result

    def artist_variants(value: str) -> list[str]:
        base = " ".join((value or "").split())
        stripped = re.split(r"\s+(?:feat\.?|ft\.?|featuring)\s+", base, maxsplit=1, flags=re.IGNORECASE)[0]
        return unique([base, stripped])

    def title_variants(value: str) -> list[str]:
        base = " ".join((value or "").split())
        no_brackets = re.sub(r"\s*[\(\[].*?[\)\]]", "", base).strip()
        no_dash_suffix = re.sub(
            r"\s+[-–—]\s+(?:remaster(?:ed)?|live|radio edit|single version|album version|explicit|clean|mono|stereo).*$",
            "",
            base,
            flags=re.IGNORECASE,
        ).strip()
        return unique([base, no_brackets, no_dash_suffix])

    def first_present(data: dict[str, Any], fields: tuple[str, ...]) -> str:
        for field_name in fields:
            value = (data.get(field_name) or "").strip()
            if value:
                return value
        return ""

    def localized_description(data: dict[str, Any]) -> str:
        lang = lang_code.upper()
        fields = (
            f"strDescription{lang}",
            "strDescriptionEN",
            "strDescriptionIT",
            "strDescriptionES",
            "strDescriptionFR",
            "strDescriptionDE",
            "strDescriptionPT",
            "strDescriptionNL",
            "strDescriptionRU",
            "strDescriptionJP",
        )
        return first_present(data, fields)

    get_ordered_context = getattr(client, "get_ordered_context", None)
    if callable(get_ordered_context):
        sections = get_ordered_context(
            artist=artist,
            title=title,
            album=album,
            language=lang_code,
        )
        if isinstance(sections, dict) and sections.get("combined"):
            return clean(str(sections["combined"]), 900)

    get_track_text = getattr(client, "get_track_text", None)
    if callable(get_track_text):
        try:
            text = get_track_text(
                artist=artist,
                title=title,
                album=album,
                language=lang_code,
            )
        except TypeError:
            text = get_track_text(
                artist=artist,
                title=title,
                language=lang_code,
            )
        if text:
            return clean(text)

    track = None
    for artist_candidate in artist_variants(artist):
        for title_candidate in title_variants(title):
            track = client.search_track(artist_candidate, title_candidate)
            if track:
                break
        if track:
            break
    if track:
        lyrics = first_present(
            track,
            ("strTrackLyrics", "strLyrics", "strLyric", "strTrackLyric"),
        )
        if lyrics:
            return clean(lyrics)
        description = localized_description(track)
        if description:
            return clean(description)
        pieces = []
        if track.get("strMood"):
            pieces.append(f"mood: {track['strMood']}")
        if track.get("strTheme"):
            pieces.append(f"theme: {track['strTheme']}")
        if track.get("strGenre"):
            pieces.append(f"genre: {track['strGenre']}")
        if track.get("strAlbum"):
            pieces.append(f"album: {track['strAlbum']}")
        if pieces:
            return clean("TheAudioDB associa il brano a " + ", ".join(pieces) + ".")

    album_data = None
    for artist_candidate in artist_variants(artist):
        album_data = client.search_album(artist_candidate, album) if album.strip() else None
        if album_data:
            break
    if album_data:
        description = localized_description(album_data)
        if description:
            return clean(description)

    return client.get_music_fact(
        artist=artist,
        title=title,
        album=album,
        language=lang_code,
    )


def fetch_song_context(title: str, artist: str, lang_code: str) -> tuple[str, list[str]]:
    """Recupera testo (Musixmatch) e contesto TheAudioDB per la chat."""
    parts: list[str] = []
    notes: list[str] = []

    if title and settings.musixmatch_ready:
        try:
            mx_client = MusixmatchClient()
            matches = mx_client.search_tracks(track=title, artist=artist, has_lyrics=True, limit=1)
            if matches:
                track = matches[0]
                lyrics_text, richsync_body = fetch_musixmatch_text(
                    mx_client,
                    track.track_id,
                    track.has_lyrics,
                    track.has_richsync,
                )
                parts.append(f"Brano: «{track.track_name or title}» di {track.artist_name or artist or 'artista sconosciuto'}")
                if richsync_body:
                    parts.append("Richsync word-level (Musixmatch): disponibile")
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
            adb_client = AudioDBClient()
            audiodb_text = fetch_audiodb_track_text(
                adb_client,
                artist=artist,
                title=title,
                lang_code=lang_code,
            )
            if audiodb_text:
                parts.append(f"Testo/contesto brano (TheAudioDB):\n{audiodb_text}")
            artist_obj = adb_client.get_artist(artist)
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


def fallback_track_response(prompt: str, tracks: list[dict[str, Any]], language: str) -> str:
    if not tracks:
        return "Non ho trovato risultati solidi. Prova con un tema, un artista o una lingua piu' precisa."

    intro = "Ecco una selezione essenziale basata sui risultati trovati:" if language == "Italiano" else "Here is a concise selection from the results found:"
    lines = [intro]
    for t in tracks:
        title = str(t.get("title", "")).strip() or "Untitled"
        artist = str(t.get("artist", "")).strip() or "Unknown artist"
        reason = str(t.get("reason", "")).strip()
        audiodb_text = str(t.get("audio_db_text") or t.get("audio_db_fact") or "").strip()
        lyrics = str(t.get("lyrics", "")).strip()
        source = audiodb_text or lyrics or reason
        source = " ".join(source.split())
        if len(source) > 180:
            source = source[:180].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
        detail = source or reason or prompt
        lines.append(f'- **{artist} - {title}**: {detail}')
    return "\n".join(lines)


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
) -> tuple[str, list[dict[str, Any]]]:
    lyrics_text = ""
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
    return lyrics_text, richsync_body


def musixmatch_track_payload(
    mx_client: MusixmatchClient,
    track: Any,
    reason: str = "",
) -> dict[str, Any]:
    lyrics_text, richsync_body = fetch_musixmatch_text(
        mx_client,
        track.track_id,
        track.has_lyrics,
        track.has_richsync,
    )
    return {
        "title": track.track_name,
        "artist": track.artist_name,
        "album": track.album_name,
        "track_id": str(track.track_id),
        "reason": reason,
        "lyrics": lyrics_text,
        "richsync": richsync_body,
        "has_lyrics": track.has_lyrics,
        "has_richsync": track.has_richsync,
        "audio_db_text": "",
        "audio_db_fact": "",
    }


def strip_narration_source_label(text: str) -> str:
    return re.sub(r"^\s*(?:\*\*)?\s*(?:musixmatch|theaudiodb|audio\s*db)\s*(?:\*\*)?\s*[:\-–—]?\s*", "", text or "", flags=re.IGNORECASE).strip()


def compact_text(text: str, limit: int = 360) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def search_musixmatch_from_plan(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    if not settings.musixmatch_ready:
        return [], ["Musixmatch not configured: set `MUSIXMATCH_API_KEY` or `MXM_KEY`."]

    notes: list[str] = []
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    mx_client = MusixmatchClient()
    try:
        limit = int(plan.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 10))

    queries = plan.get("queries") or []
    if not isinstance(queries, list):
        queries = []
    for query in queries:
        if len(results) >= limit or not isinstance(query, dict):
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
                limit=1,
            )
        except MusixmatchError as exc:
            notes.append(f"Musixmatch: {exc}")
            continue
        for match in matches:
            if match.track_id in seen:
                continue
            seen.add(match.track_id)
            results.append(musixmatch_track_payload(mx_client, match, reason=reason))
            break
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
    return {
        "prompt": prompt,
        "tracks": [],
        "summary": "",
        "moods": [],
        "llm_log": current_llm_log(),
    }


def enrich_tracks_with_audiodb_facts(
    tracks: list[dict[str, Any]],
    lang_code: str,
) -> list[str]:
    """Aggiunge a ogni brano testo/contesto e curiosita' TheAudioDB best-effort."""
    if not settings.audiodb_ready:
        return ["TheAudioDB not configured: text context and curiosities were not fetched."]
    notes: list[str] = []
    client = AudioDBClient()
    for t in tracks:
        if t.get("audio_db_fact") and t.get("audio_db_text"):
            continue
        artist = str(t.get("artist", "")).strip()
        title = str(t.get("title", "")).strip()
        album = str(t.get("album", "")).strip()
        if not artist:
            continue
        try:
            ordered_context = client.get_ordered_context(
                artist=artist,
                title=title,
                album=album,
                language=lang_code,
            )
            if ordered_context.get("song_news"):
                t["audio_db_song_news"] = ordered_context["song_news"]
            if ordered_context.get("album_news"):
                t["audio_db_album_news"] = ordered_context["album_news"]
            if ordered_context.get("artist_description"):
                t["audio_db_artist_description"] = ordered_context["artist_description"]
            if ordered_context.get("combined"):
                t["audio_db_text"] = ordered_context["combined"]
            if title and not t.get("audio_db_text"):
                text = fetch_audiodb_track_text(
                    client,
                    artist=artist,
                    title=title,
                    album=album,
                    lang_code=lang_code,
                )
                if text:
                    t["audio_db_text"] = text
            fact = client.get_music_fact(
                artist=artist,
                title=title,
                album=album,
                language=lang_code,
            )
            if fact:
                t["audio_db_fact"] = fact
        except AudioDBError as exc:
            notes.append(f"TheAudioDB: {exc}")
            break
    return notes


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

    # 1) Pre-fetch bio (AudioDB / Last.fm), immagine e testo (Musixmatch) per ogni brano,
    #    PRIMA della chiamata LLM, così il modello può usare questi dati per generare
    #    narrations più ricche e specifiche.
    image_cache: dict[str, str] = {}
    adb_client = AudioDBClient() if settings.audiodb_ready else None
    mx_client = MusixmatchClient() if settings.musixmatch_ready else None

    for t in enriched:
        artist = t.get("artist", "")
        title = t.get("title", "")

        # 1a) Musixmatch: valida e corregge titolo+artista con i dati canonici,
        #     poi recupera il testo. Va PRIMA di AudioDB così usiamo il nome
        #     artista corretto anche per la bio.
        if mx_client and title:
            try:
                track_id = t.get("track_id")
                best = mx_client.get_track(int(track_id)) if track_id else None
                if not best:
                    matches = mx_client.search_tracks(track=title, artist=artist, has_lyrics=True, limit=1)
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
                        lyrics_text, richsync_body = fetch_musixmatch_text(
                            mx_client,
                            best.track_id,
                            best.has_lyrics,
                            best.has_richsync,
                        )
                        t["lyrics"] = lyrics_text
                        t["richsync"] = richsync_body
                else:
                    t.setdefault("lyrics", "")
                    t.setdefault("richsync", [])
            except MusixmatchError:
                t.setdefault("lyrics", "")
                t.setdefault("richsync", [])

        # 1b) Bio + immagine da AudioDB (usa il nome artista già corretto da Musixmatch)
        bio = ""
        if adb_client and artist:
            try:
                a = adb_client.get_artist(artist)
                if a:
                    bio = a.biography(lang_code) or ""
                    image_cache[artist] = a.image_url
                    t["image"] = a.image_url
                ordered_context = adb_client.get_ordered_context(
                    artist=artist,
                    title=title,
                    album=str(t.get("album", "")),
                    language=lang_code,
                )
                if ordered_context.get("song_news"):
                    t["audio_db_song_news"] = ordered_context["song_news"]
                if ordered_context.get("album_news"):
                    t["audio_db_album_news"] = ordered_context["album_news"]
                if ordered_context.get("artist_description"):
                    t["audio_db_artist_description"] = ordered_context["artist_description"]
                if ordered_context.get("combined"):
                    t["audio_db_text"] = ordered_context["combined"]
                if not t.get("audio_db_text"):
                    text = fetch_audiodb_track_text(
                        adb_client,
                        artist=artist,
                        title=title,
                        album=str(t.get("album", "")),
                        lang_code=lang_code,
                    )
                    if text:
                        t["audio_db_text"] = text
                if not t.get("audio_db_fact"):
                    fact = adb_client.get_music_fact(
                        artist=artist,
                        title=title,
                        album=str(t.get("album", "")),
                        language=lang_code,
                    )
                    if fact:
                        t["audio_db_fact"] = fact
            except AudioDBError:
                pass

        # 1c) Fallback bio da Last.fm
        if not bio and settings.lastfm_ready and artist:
            try:
                bio = LastFMClient().get_biography(name=artist, lang=lang_code) or ""
            except LastFMError:
                pass

        t.setdefault("audio_db_fact", "")
        t.setdefault("audio_db_text", "")
        t.setdefault("audio_db_song_news", "")
        t.setdefault("audio_db_album_news", "")
        t.setdefault("audio_db_artist_description", "")
        t["_bio"] = bio  # campo temporaneo letto da studio_brief(), rimosso dopo

    # 2) Discorsi parlati + mood + origine geografica + riassunto (una sola chiamata LLM).
    #    I track dict includono ora _bio e lyrics, usati da studio_brief().
    if settings.llm_ready:
        add_llm_log(
            "Studio brief",
            f"Generating narrated speeches, moods and artist origins for {len(enriched)} tracks.",
        )
        try:
            brief = storyteller_for_session().studio_brief(
                title=prompt, tracks=enriched, language=lang_name
            )
            add_llm_log(
                "Studio brief parsed",
                f"Received {len(brief.get('narrations') or [])} narrations and {len(brief.get('moods') or [])} mood labels.",
            )
        except StorytellerError:
            brief = {}
            add_llm_log(
                "Studio brief failed",
                "The app will keep the playlist and skip generated narration metadata.",
            )
        narrations = brief.get("narrations") or []
        for i, t in enumerate(enriched):
            n = narrations[i] if i < len(narrations) else {}
            musixmatch_speech = strip_narration_source_label(str(n.get("musixmatch_speech", "")).strip())
            audiodb_speech = strip_narration_source_label(str(n.get("audiodb_speech", "")).strip())
            if not musixmatch_speech:
                musixmatch_source = str(t.get("lyrics") or t.get("reason") or "").strip()
                if musixmatch_source:
                    musixmatch_speech = compact_text(musixmatch_source, 220)
            if not audiodb_speech:
                audiodb_source = str(
                    t.get("audio_db_song_news")
                    or t.get("audio_db_album_news")
                    or t.get("audio_db_artist_description")
                    or t.get("audio_db_text")
                    or t.get("audio_db_fact")
                    or t.get("_bio")
                    or ""
                ).strip()
                if audiodb_source:
                    audiodb_speech = compact_text(audiodb_source, 220)
            combined_speech = " ".join(part for part in (musixmatch_speech, audiodb_speech) if part).strip()
            t["musixmatch_speech"] = musixmatch_speech
            t["audiodb_speech"] = audiodb_speech
            t["speech"] = combined_speech
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
        t.setdefault("image", image_cache.get(t.get("artist", ""), ""))
        t.setdefault("audio_b64", "")
        t.setdefault("lyrics", "")
        t.setdefault("richsync", [])
        t.setdefault("audio_db_text", "")
        t.setdefault("musixmatch_speech", "")
        t.setdefault("audiodb_speech", "")

    if getattr(settings, "elevenlabs_ready", False):
        add_llm_log(
            "ElevenLabs TTS",
            "Narration audio will be generated on demand when playback starts.",
        )
    else:
        add_llm_log(
            "ElevenLabs TTS",
            "ELEVENLABS_API_KEY is missing: narration audio is disabled.",
        )

    return {
        "prompt": prompt,
        "tracks": enriched,
        "summary": summary,
        "moods": moods,
        "llm_log": current_llm_log(),
    }


STUDIO_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:ital,wght@0,400;0,500;1,400&family=JetBrains+Mono:wght@400;600&display=swap');
  * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; }
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
        overscroll-behavior: contain;
  }
  .lyr-empty { color: #6f6a85; font-size: .82rem; font-style: italic; padding: 6px; }
  .lyr-line {
    font-size: .86rem; line-height: 1.85; color: #8f8aa8;
    padding: 2px 6px; border-radius: 6px;
    transition: color .35s ease, background .35s ease;
  }
  .lyr-line.active { color: #f3f1ff; font-weight: 600; background: rgba(249,115,22,.12); }
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
  const TOKEN = __TOKEN__;
    const TTS_ENDPOINT = __TTS_ENDPOINT__;
    const TTS_TOKEN = __TTS_TOKEN__;
  const PLAYLIST_NAME = __PLAYLIST__;
  const PALETTE = ["#ff2d78","#f97316","#22d3ee","#facc15","#c2410c","#34d399"];

    let embedController = null;
    let pendingUri = '';
    let embedReady = false;
    let embedPlayed = false;
    let embedPosition = 0;
    let embedDuration = 0;
    let embedPaused = true;
  let currentAudio = null;
  let shuffleOn = false;
  let autoSeq = false;
  let awaitingEnd = false;
  let order = [];
  let seqPos = 0;
  let current = -1;
    const audioObjectUrls = new Map();

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

    function normalizeSearchText(s) {
        return String(s || '')
            .replace(/\\s*[\\(\\[].*?[\\)\\]]/g, ' ')
            .replace(/\\s+[-–—]\\s+(remaster(ed)?|live|radio edit|single version|album version|explicit|clean|mono|stereo).*$/i, ' ')
            .replace(/\\s+/g, ' ')
            .trim();
    }

    function spotifyQueries(t) {
        const title = normalizeSearchText(t.title || '');
        const artist = normalizeSearchText(t.artist || '').replace(/\\s+(feat\\.?|ft\\.?|featuring)\\s+.*$/i, '').trim();
        const album = normalizeSearchText(t.album || '');
        const queries = [];
        if (title && artist && album) queries.push('track:' + title + ' artist:' + artist + ' album:' + album);
        if (title && artist) queries.push('track:' + title + ' artist:' + artist);
        if (title && album) queries.push('track:' + title + ' album:' + album);
        if (title) queries.push((title + ' ' + artist).trim());
        return [...new Set(queries.filter(Boolean))];
    }

    function spotifyMatchScore(item, t) {
        const title = normalizeSearchText(t.title || '').toLowerCase();
        const artist = normalizeSearchText(t.artist || '').toLowerCase().replace(/\\s+(feat\\.?|ft\\.?|featuring)\\s+.*$/i, '').trim();
        const album = normalizeSearchText(t.album || '').toLowerCase();
        const itemTitle = normalizeSearchText(item.name || '').toLowerCase();
        const itemAlbum = normalizeSearchText(item.album && item.album.name || '').toLowerCase();
        const itemArtists = (item.artists || []).map(a => normalizeSearchText(a.name || '').toLowerCase()).join(' ');
        let score = 0;
        if (itemTitle === title) score += 60;
        else if (itemTitle.includes(title) || title.includes(itemTitle)) score += 35;
        if (artist && itemArtists.includes(artist)) score += 30;
        if (album && itemAlbum && (itemAlbum === album || itemAlbum.includes(album) || album.includes(itemAlbum))) score += 10;
        return score;
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
        const musix = (t.musixmatch_speech || '').trim();
        const adb = (t.audiodb_speech || '').trim();
        if (musix || adb) {
            cSpeech.innerHTML =
                (musix ? '<div>' + esc(musix) + '</div>' : '') +
                (adb ? '<div style="margin-top:12px;">' + esc(adb) + '</div>' : '');
        } else {
            cSpeech.textContent = t.speech || (t.reason || 'No speech available for this track.');
        }
    showLyrics(i);
    prepareTrackPlayer(i);
  }

  // ---- Lyrics ----
    function numericTime(value) {
        const n = Number(value);
        if (!Number.isFinite(n)) return null;
        return n > 1000 ? n / 1000 : n;
    }

    function datasetTime(value) {
        if (value === undefined || value === null || value === '') return null;
        return numericTime(value);
    }

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

  function showLyrics(i) {
    const t = TRACKS[i];
    const section = document.getElementById('lyrics-section');
    const box = document.getElementById('lyrics-box');
    section.style.display = 'flex';
    const richsync = Array.isArray(t.richsync) ? t.richsync : [];
    if (richsync.length) {
      box.innerHTML = richsync.map((item, idx) => {
        const text = richsyncLineText(item);
        if (!text) return '';
                const startRaw = item.ts ?? item.start ?? item.time ?? 0;
                const endRaw = item.te ?? item.end ?? item.endTime ?? '';
                const start = numericTime(startRaw) ?? 0;
                const end = numericTime(endRaw);
        const line = item.l || item.line || item.text || '';
        let htmlText = esc(text);
        if (Array.isArray(line)) {
          htmlText = line.map((token, wordIdx) => {
            const raw = token && typeof token === 'object' ? (token.c || token.text || '') : String(token || '');
                        const offset = token && typeof token === 'object' ? (numericTime(token.o ?? token.offset ?? 0) ?? 0) : 0;
            return '<span class="lyr-word" data-offset="' + offset + '" data-word="' + wordIdx + '">' + esc(raw) + '</span>';
          }).join('');
        }
                                const endAttr = end === null ? '' : end;
                return '<div class="lyr-line" data-idx="' + idx + '" data-start="' + start + '" data-end="' + endAttr + '">' + htmlText + '</div>';
      }).join('');
            box.scrollTop = 0;
            syncLyrics(embedPosition, embedDuration);
      return;
    }
    if (!t.lyrics || !t.lyrics.trim()) {
      box.innerHTML = '<div class="lyr-empty">Synced lyrics unavailable for this track.</div>';
      return;
    }
    const lines = t.lyrics.split('\\n')
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('****') && !l.toLowerCase().includes('commercial use'));
    box.innerHTML = lines.map((l, idx) =>
      '<div class="lyr-line" data-idx="' + idx + '">' + esc(l) + '</div>'
    ).join('');
        box.scrollTop = 0;
        syncLyrics(embedPosition, embedDuration);
  }

  function syncLyrics(position, duration) {
    const box = document.getElementById('lyrics-box');
    const lines = box.querySelectorAll('.lyr-line');
        if (!lines.length) return;
        const pos = numericTime(position) ?? 0;
        const dur = numericTime(duration) ?? 0;
        const hasTimedLines = Array.from(lines).some(el => datasetTime(el.dataset.start) !== null);
    let idx = -1;
        if (hasTimedLines) {
            lines.forEach((el, i) => {
                const start = datasetTime(el.dataset.start);
                if (start === null || pos < start) return;
                const explicitEnd = datasetTime(el.dataset.end);
                const next = lines[i + 1];
                const nextStart = next ? datasetTime(next.dataset.start) : null;
                const end = explicitEnd !== null
                    ? explicitEnd
                    : (nextStart !== null ? nextStart : Number.POSITIVE_INFINITY);
                if (pos < end + 0.08) idx = i;
            });
        }
        if (idx < 0 && dur > 0) idx = Math.min(Math.floor((pos / dur) * lines.length), lines.length - 1);
        if (idx < 0) return;
    let changed = false;
    lines.forEach((el, i) => {
      const was = el.classList.contains('active');
      el.classList.toggle('active', i === idx);
      if (i === idx) {
                const start = datasetTime(el.dataset.start) || 0;
        el.querySelectorAll('.lyr-word').forEach(word => {
                    const offset = datasetTime(word.dataset.offset) || 0;
          word.classList.toggle('active', pos >= start + offset);
        });
      } else {
        el.querySelectorAll('.lyr-word').forEach(word => word.classList.remove('active'));
      }
      if (!was && i === idx) changed = true;
    });
        if (changed && lines[idx]) {
            const target = lines[idx];
            const targetTop = target.offsetTop - box.offsetTop;
            const centeredTop = targetTop - (box.clientHeight / 2) + (target.clientHeight / 2);
            box.scrollTo({ top: Math.max(0, centeredTop), behavior: 'smooth' });
        }
  }

  // ---- Spotify Web API helpers (token personale dell'utente) ----
  function api(path, opts) {
    return fetch('https://api.spotify.com/v1' + path, Object.assign({
      headers: { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' }
    }, opts || {}));
  }

  async function resolveUri(t) {
    if (t.uri) return t.uri;
    if (!TOKEN) return '';
    try {
            for (const query of spotifyQueries(t)) {
                const r = await api('/search?type=track&limit=5&q=' + encodeURIComponent(query));
                if (r.ok) {
                    const d = await r.json();
                    const items = d.tracks && d.tracks.items ? d.tracks.items : [];
                    const ranked = items
                        .map(item => ({ item, score: spotifyMatchScore(item, t) }))
                        .sort((a, b) => b.score - a.score);
                    const best = ranked[0];
                    if (best && best.item && best.score >= 45) {
                        const it = best.item;
                        t.uri = it.uri;
                        t.spotify_match = { name: it.name, artist: (it.artists || []).map(a => a.name).join(', '), score: best.score };
                        const img = it.album && it.album.images && it.album.images[0];
                        if (img) { t.art = img.url; if (!t.image) t.image = img.url; }
                        return t.uri;
                    }
        }
      }
    } catch (e) {}
    return '';
  }

    // ---- Audio: voce ElevenLabs MP3 + Spotify ----
  function stopAudio() {
    if (currentAudio) {
      try { currentAudio.pause(); currentAudio.currentTime = 0; } catch (e) {}
      currentAudio = null;
    }
    awaitingEnd = false;
        if (embedController && embedReady) {
            try { embedController.pause(); } catch (e) {}
        }
  }

    async function narrationAudioUrl(i) {
        const t = TRACKS[i];
        if (t.audio_url) return t.audio_url;
        if (audioObjectUrls.has(i)) return audioObjectUrls.get(i);
        if (t.audio_b64) {
            t.audio_url = 'data:audio/mpeg;base64,' + t.audio_b64;
            return t.audio_url;
        }
        const text = (t.speech || [t.musixmatch_speech, t.audiodb_speech].filter(Boolean).join(' ') || '').trim();
        if (!text || !TTS_ENDPOINT || !TTS_TOKEN) return '';

        const response = await fetch(TTS_ENDPOINT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Sonder-TTS-Token': TTS_TOKEN
            },
            body: JSON.stringify({ text })
        });
        if (!response.ok) throw new Error('tts_' + response.status);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        audioObjectUrls.set(i, url);
        return url;
    }

    async function speak(i, onend) {
    // Stop anything currently playing.
    if (currentAudio) { try { currentAudio.pause(); } catch (e) {} currentAudio = null; }

        try {
            const audioUrl = await narrationAudioUrl(i);
            if (current !== i) return;
            if (!audioUrl) {
                setStatus('ElevenLabs audio unavailable');
                onend && onend();
                return;
            }
            setStatus('🗣️ Narrating…');
            const audio = new Audio(audioUrl);
      currentAudio = audio;
      audio.onended = () => { currentAudio = null; onend && onend(); };
      audio.onerror = () => { currentAudio = null; onend && onend(); };
      audio.play().catch(() => { currentAudio = null; onend && onend(); });
      return;
        } catch (e) {
            currentAudio = null;
            setStatus('ElevenLabs audio unavailable');
            onend && onend();
    }
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

    async function runTrack(i, withVoice, seq) {
    current = i;
    highlight(i);
    showCenter(i);
    if (withVoice) {
            setStatus('🗣️ Preparing narration…');
            await speak(i, () => startSong(i, seq));
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

    let lastPlaybackUpdate = 0;

    function onState(state) {
        if (!state || !state.data) return;
        const d = state.data;
        embedPosition = typeof d.position === 'number' ? (numericTime(d.position) ?? embedPosition) : embedPosition;
        embedDuration = typeof d.duration === 'number' ? (numericTime(d.duration) ?? embedDuration) : embedDuration;
        embedPaused = !!d.isPaused;
        if (!embedPaused) lastPlaybackUpdate = performance.now();
        if (!embedPaused && embedPosition > 0) embedPlayed = true;

        if (current >= 0) syncLyrics(embedPosition, embedDuration);
        if (autoSeq && awaitingEnd && embedPlayed && embedPaused && embedPosition === 0) {
            awaitingEnd = false;
            advance();
        }
  }

    setInterval(() => {
        if (current < 0 || embedPaused) return;
        const elapsed = lastPlaybackUpdate ? ((performance.now() - lastPlaybackUpdate) / 1000) : 0;
        syncLyrics(embedPosition + elapsed, embedDuration);
    }, 180);

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


def render_studio_component(studio: dict) -> None:
    """Renderizza la regia a 3 colonne con voce ElevenLabs e player Spotify per-utente."""
    tracks = studio.get("tracks", [])
    tts_endpoint = ""
    tts_token = ""
    if getattr(settings, "elevenlabs_ready", False):
        try:
            tts_info = ensure_tts_server()
            tts_endpoint = tts_info.endpoint
            tts_token = tts_info.token
        except TTSServerError as exc:
            add_llm_log("ElevenLabs TTS endpoint failed", str(exc))
    payload = [
        {
            "title": t.get("title", ""),
            "artist": t.get("artist", ""),
            "speech": t.get("speech", ""),
            "musixmatch_speech": t.get("musixmatch_speech", ""),
            "audiodb_speech": t.get("audiodb_speech", ""),
            "mood": t.get("mood", ""),
            "origin": t.get("origin", ""),
            "reason": t.get("reason", ""),
            "image": t.get("image", ""),
            "uri": t.get("uri", ""),
            "audio_b64": t.get("audio_b64", ""),
            "lyrics": t.get("lyrics", ""),
            "richsync": t.get("richsync", []),
            "track_id": t.get("track_id", ""),
            "album": t.get("album", ""),
            "audio_db_fact": t.get("audio_db_fact", ""),
            "audio_db_text": t.get("audio_db_text", ""),
        }
        for t in tracks
    ]
    tracks_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    playlist_name = json.dumps(
        f"Sonder · {studio.get('prompt', '')[:60]}", ensure_ascii=False
    )
    token_json = json.dumps(spotify_token())
    rendered = (
        STUDIO_HTML.replace("__TRACKS__", tracks_json)
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


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
def render_message(index: int, msg: dict) -> None:
    """Renderizza un singolo messaggio della chat (con eventuale playlist)."""
    avatar = "💕" if msg["role"] == "assistant" else None
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

        render_llm_log(msg.get("llm_log"))

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
    reset_llm_log()


def handle_user_input(prompt: str, lang_name: str, lang_code: str) -> None:
    """Elabora il messaggio utente: conversazione + eventuale costruzione dello studio."""
    reset_llm_log()
    add_llm_log("User request", prompt)
    st.session_state["messages"].append({"role": "user", "content": prompt})

    # Senza LLM mostriamo comunque la struttura della regia con tab/sezioni vuote.
    if not settings.llm_ready:
        add_llm_log("LLM skipped", "LLM_API_KEY is missing; the reasoning pipeline cannot run.")
        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": "LLM not configured: set `LLM_API_KEY` (and "
                "`LLM_BASE_URL`/`LLM_MODEL`) in `.env` to populate the studio. "
                "Showing empty structure for now.",
                "llm_log": current_llm_log(),
            }
        )
        st.session_state["studio"] = empty_studio(prompt)
        return

    teller = storyteller_for_session()
    add_llm_log("LLM model", selected_llm_model())

    with st.spinner("Planning Musixmatch search..."):
        try:
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["messages"]
            ]
            plan = teller.plan_musixmatch_search(
                messages=history,
                language=lang_name,
                context=st.session_state.get("context", ""),
            )
            queries = plan.get("queries") or []
            query_details: list[str] = []
            for query in queries:
                if not isinstance(query, dict):
                    continue
                bits = [
                    str(query.get("q", "")).strip(),
                    str(query.get("q_track", "")).strip(),
                    str(query.get("q_artist", "")).strip(),
                    str(query.get("q_lyrics", "")).strip(),
                ]
                compact = " | ".join(bit for bit in bits if bit)
                if compact:
                    query_details.append(compact)
            add_llm_log(
                "Search router",
                f"music_related={plan.get('music_related', True)}, "
                f"needs_search={plan.get('needs_search', True)}, "
                f"limit={plan.get('limit', 8)}, "
                f"query_count={len(query_details)}"
                + ("\nQueries: " + "; ".join(query_details) if query_details else "")
                + ("\nFallback: " + str(plan.get("_router_fallback")) if plan.get("_router_fallback") else ""),
            )
        except StorytellerError as exc:
            add_llm_log("Search router failed", user_facing_llm_error(exc))
            st.session_state["messages"].append(
                {"role": "assistant", "content": user_facing_llm_error(exc), "llm_log": current_llm_log()}
            )
            st.session_state["studio"] = empty_studio(prompt)
            return

    if not plan.get("music_related", True):
        key = lang_name if lang_name in REFUSALS else "Italiano"
        add_llm_log("Scope check", "The request was classified as outside the music domain.")
        st.session_state["messages"].append({"role": "assistant", "content": REFUSALS[key], "llm_log": current_llm_log()})
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
                add_llm_log(
                    "Conversation response",
                    "Generated a direct music-domain answer without a Musixmatch search.",
                )
            except StorytellerError as exc:
                add_llm_log("Conversation response failed", user_facing_llm_error(exc))
                st.session_state["messages"].append(
                    {"role": "assistant", "content": user_facing_llm_error(exc), "llm_log": current_llm_log()}
                )
                st.session_state["studio"] = empty_studio(prompt)
                return
        if "[NON_MUSICALE]" in text:
            key = lang_name if lang_name in REFUSALS else "Italiano"
            text = text.replace("[NON_MUSICALE]", "").strip() or REFUSALS[key]
        st.session_state["messages"].append(
            {"role": "assistant", "content": text, "reasoning": reasoning, "tracks": [], "llm_log": current_llm_log()}
        )
        st.session_state["studio"] = empty_studio(prompt)
        return

    with st.spinner("Searching Musixmatch..."):
        tracks, notes = search_musixmatch_from_plan(plan)
    add_llm_log(
        "Musixmatch search",
        f"Found {len(tracks)} tracks." + ("\n" + "\n".join(notes) if notes else ""),
    )
    if tracks:
        notes.extend(enrich_tracks_with_audiodb_facts(tracks, lang_code))
        add_llm_log(
            "TheAudioDB enrichment",
            f"Processed text context and curiosities for {len(tracks)} tracks."
            + ("\n" + "\n".join(notes) if notes else ""),
        )

    with st.spinner("Rewriting from verified music text..."):
        try:
            text, reasoning = teller.compose_musixmatch_response(
                prompt=prompt,
                tracks=tracks,
                language=lang_name,
                context=st.session_state.get("context", ""),
            )
            add_llm_log(
                "Response writer",
                "Composed the assistant answer using Musixmatch results and TheAudioDB text context.",
            )
        except StorytellerError as exc:
            add_llm_log("Response writer failed", user_facing_llm_error(exc))
            text = fallback_track_response(prompt, tracks, lang_name)
            reasoning = "Fallback response generated from verified search results after LLM writer failure."
            add_llm_log(
                "Response fallback",
                "Used a concise local response built from Musixmatch and TheAudioDB results.",
            )

    if notes:
        text = text + "\n\n" + "\n".join(f"> {note}" for note in notes)

    st.session_state["messages"].append(
        {"role": "assistant", "content": text, "reasoning": reasoning, "tracks": tracks, "llm_log": current_llm_log()}
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
    st.markdown(
        '<p class="hero-sub">Music curation &amp; emotional storytelling powered by AI. '
        'Type a prompt below or pick one of these to get started.</p>',
        unsafe_allow_html=True,
    )
    st.markdown("")
    prompts = EXAMPLE_PROMPTS.get(lang_name, EXAMPLE_PROMPTS["Auto"])
    cols = st.columns(3)
    for i, (icon, text) in enumerate(prompts):
        with cols[i % 3]:
            if st.button(f"{icon}  {text}", key=f"_ex_{i}", use_container_width=True):
                st.session_state["_pending_example"] = text
                st.rerun()
    st.markdown("")


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

    ui_language = st.sidebar.selectbox("🌍 Narration language", list(LANGUAGES.keys()), index=0)
    lang_name, lang_code = LANGUAGES[ui_language]
    if lang_name == "Auto":
        st.sidebar.caption("Auto mode: I'll reply in the language of your message.")

    if st.sidebar.button("➕ New chat", use_container_width=True):
        init_chat(ui_language)

    # Sidebar
    render_status_sidebar()
    render_llm_model_selector()
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

    st.sidebar.caption(f"LLM model: `{selected_llm_model()}`")

    # Stato chat
    if "messages" not in st.session_state:
        init_chat(ui_language)

    # Input utente: visibile finche' lo studio non ha brani.
    # Se il modello risponde senza playlist (es. Gemma), la chat rimane aperta.
    studio_has_tracks = bool(
        st.session_state.get("studio") and st.session_state["studio"].get("tracks")
    )
    if not studio_has_tracks:
        # Handle example prompt clicked on previous run.
        if st.session_state.get("_pending_example"):
            pending = st.session_state.pop("_pending_example")
            handle_user_input(pending, lang_name, lang_code)
            if st.session_state.get("studio", {}).get("tracks"):
                st.rerun()
        prompt = st.chat_input("Type here… what would you like to talk about?")
        if prompt:
            handle_user_input(prompt, lang_name, lang_code)
            # Rerun immediato cosi' la barra della chat sparisce davvero.
            if st.session_state.get("studio", {}).get("tracks"):
                st.rerun()

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
        render_llm_log(studio.get("llm_log"))
    else:
        st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)
        # Mostra i messaggi della conversazione (indice 0 = saluto iniziale, nascosto).
        for i, msg in enumerate(st.session_state.get("messages", [])):
            if i == 0:
                continue  # saluto iniziale: rimane nel contesto LLM ma non viene mostrato
            render_message(i, msg)
        if len(st.session_state.get("messages", [])) <= 1:
            render_example_prompts(lang_name)

    # --- Regia a 3 colonne (occupa tutta la schermata) ---
    # Mostrata solo quando il modello ha restituito una playlist con brani.
    if has_tracks:
        if not spotify_token():
            st.caption(
                "Log in to your Spotify in the sidebar to enable the player "
                "and add the playlist to your profile."
            )
        render_studio_component(studio)
        # Sezioni informative (scorrendo verso il basso)
        render_studio_sections(studio)


if __name__ == "__main__":
    main()
