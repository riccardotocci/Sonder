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
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core.config import settings
from core.musixmatch_client import MusixmatchClient, MusixmatchError
from core.audiodb_client import AudioDBClient, AudioDBError
from core.lastfm_client import LastFMClient, LastFMError
from core.storyteller import Storyteller, StorytellerError
from core.spotify_client import SpotifyClient, SpotifyError
from core.elevenlabs_client import ElevenLabsClient, ElevenLabsError
from core import spotify_pkce

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


# Store temporaneo (per processo) state->code_verifier per il flusso PKCE.
# Necessario perche' il redirect a Spotify ricarica la pagina e azzera session_state.
_PKCE_STORE: dict[str, str] = {}

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

# Saluto iniziale della chat per ciascuna lingua (per "Auto" usiamo un saluto bilingue).
GREETINGS: dict[str, str] = {
    "Auto": "Hi, I'm **Sonder**. What would you like to talk about? "
            "Feel free to write in any language and I'll reply in the same. 😈",
    "Italiano": "Ciao, sono **Sonder**. Di cosa vuoi parlare oggi? 😈",
    "English": "Hi, I'm **Sonder**. What would you like to talk about? 😈",
    "Français": "Salut, je suis **Sonder**. De quoi veux-tu parler ? 😈",
    "Español": "Hola, soy **Sonder**. ¿De qué quieres hablar? 😈",
    "Deutsch": "Hallo, ich bin **Sonder**. Worüber möchtest du sprechen? 😈",
    "Português": "Olá, sou **Sonder**. Sobre o que queres falar? 😈",
    "Nederlands": "Hoi, ik ben **Sonder**. Waarover wil je praten? 😈",
    "Polski": "Cześć, jestem **Sonder**. O czym chcesz porozmawiać? 😈",
    "Русский": "Привет, я **Sonder**. О чём хочешь поговорить? 😈",
    "日本語": "こんにちは、**Sonder** です。何について話したいですか？ 😈",
    "中文": "你好，我是 **Sonder**。你想聊些什么？ 😈",
    "한국어": "안녕하세요, 저는 **Sonder** 입니다. 무엇에 대해 이야기하고 싶으신가요? 😈",
    "العربية": "مرحبًا، أنا **Sonder**. عن ماذا تريد أن نتحدث؟ 😈",
}

# Messaggi di rifiuto in-character per argomenti fuori ambito musicale.
REFUSALS: dict[str, str] = {
    "Auto":     "*Questo non è il mio territorio.* Sono fatto di note, versi e ombre sonore — parlami di musica e ti seguirò ovunque. 😈",
    "Italiano": "*Questo non è il mio territorio.* Sono fatto di note, versi e ombre sonore — parlami di musica e ti seguirò ovunque. 😈",
    "English":  "*That's outside my domain.* I'm made of notes, lyrics and sonic shadows — bring me music and I'll follow you anywhere. 😈",
    "Français": "*Ce n'est pas mon domaine.* Je suis fait de notes, de paroles et d'ombres sonores — parle-moi de musique et je te suivrai partout. 😈",
    "Español":  "*Eso está fuera de mi territorio.* Estoy hecho de notas, letras y sombras sonoras — háblame de música y te seguiré a donde sea. 😈",
    "Deutsch":  "*Das liegt außerhalb meines Gebiets.* Ich bin aus Noten, Texten und klanglichen Schatten gemacht — sprich über Musik und ich folge dir überallhin. 😈",
    "Português":"*Isso está fora do meu território.* Sou feito de notas, letras e sombras sonoras — fala-me de música e te seguirei para onde quiseres. 😈",
    "Nederlands":"*Dit valt buiten mijn domein.* Ik ben gemaakt van noten, teksten en klanksschaduwen — praat met me over muziek en ik volg je overal. 😈",
    "Polski":   "*To poza moim terenem.* Jestem zbudowany z nut, tekstów i dźwiękowych cieni — porozmawiaj ze mną o muzyce, a pójdę za tobą wszędzie. 😈",
    "Русский":  "*Это не моя территория.* Я соткан из нот, слов и звуковых теней — говори со мной о музыке, и я последую за тобой куда угодно. 😈",
    "日本語":    "*それは私の領域外です。* 私は音符、歌詞、音の影から生まれました — 音楽について話せば、どこまでもついていきます。😈",
    "中文":     "*这超出了我的领域。* 我由音符、歌词和声音的阴影构成——跟我谈音乐，我会陪你走遍任何地方。😈",
    "한국어":   "*그건 제 영역 밖입니다.* 저는 음표, 가사, 음향의 그림자로 만들어졌습니다 — 음악에 대해 이야기하면 어디든 따라가겠습니다. 😈",
    "العربية":  "*هذا خارج نطاق تخصصي.* أنا مصنوع من نوتات موسيقية وكلمات وظلال صوتية — تحدّث إليّ عن الموسيقى وسأتبعك أينما ذهبت. 😈",
}

# Palette neon "studio tecnologico", ciclata per indice su pill e card.
PALETTE = ["#ff2d78", "#f97316", "#22d3ee", "#facc15", "#c2410c", "#34d399"]

EXAMPLE_PROMPTS: list[tuple[str, str]] = [
    ("🌧️", "Songs for a rainy Sunday morning"),
    ("🌙", "Music that sounds like 3am loneliness"),
    ("🎸", "Rock albums that changed everything"),
    ("🚗", "Jazz for a late-night drive"),
    ("💔", "Emotional songs about heartbreak and loss"),
    ("🎬", "The most cinematic soundtracks ever made"),
]

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
    .block-container { max-width: 1180px; }

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


# --------------------------------------------------------------------------- #
# Tool musicali (contesto + playlist)
# --------------------------------------------------------------------------- #
def fetch_song_context(title: str, artist: str, lang_code: str) -> tuple[str, list[str]]:
    """Recupera testo (Musixmatch) e biografia (TheAudioDB) come contesto per la chat."""
    parts: list[str] = []
    notes: list[str] = []

    if title and settings.musixmatch_ready:
        try:
            track, lyrics = MusixmatchClient().find_lyrics(title, artist)
            real_artist = artist or (track.artist_name if track else "")
            parts.append(f"Brano: «{title}» di {real_artist or 'artista sconosciuto'}")
            if lyrics.body:
                parts.append("Testo (Musixmatch):\n" + lyrics.body)
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
    verifier = _PKCE_STORE.pop(state, None)
    if verifier:
        try:
            token = spotify_pkce.exchange_code(
                client_id=settings.spotify_client_id,
                redirect_uri=settings.spotify_redirect_uri,
                code=code,
                verifier=verifier,
            )
            st.session_state["sp_token"] = {
                "access_token": token.get("access_token", ""),
                "refresh_token": token.get("refresh_token", ""),
                "expires_at": time.time() + int(token.get("expires_in", 3600)),
            }
            st.session_state.pop("sp_auth_error", None)
        except spotify_pkce.SpotifyPKCEError as exc:
            st.session_state["sp_auth_error"] = str(exc)
    st.query_params.clear()
    st.rerun()


def spotify_token() -> str:
    """Restituisce un access token valido, rinnovandolo se scaduto."""
    tok = st.session_state.get("sp_token")
    if not tok:
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
            st.session_state["sp_token"] = tok
        except spotify_pkce.SpotifyPKCEError:
            st.session_state.pop("sp_token", None)
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

    if "localhost" in settings.spotify_redirect_uri:
        container.warning(
            "Spotify no longer accepts `localhost` as Redirect URI: use "
            "`http://127.0.0.1:8501` in `SPOTIFY_REDIRECT_URI` (and in the "
            "Spotify dashboard), then open the app from that address."
        )

    if spotify_token():
        container.success("🟢 Connected to your Spotify")
        if container.button("Disconnect Spotify", use_container_width=True):
            st.session_state.pop("sp_token", None)
            st.rerun()
        return

    # Prepara un nuovo tentativo di login (verifier/state freschi).
    verifier = spotify_pkce.make_verifier()
    challenge = spotify_pkce.make_challenge(verifier)
    state = spotify_pkce.make_state()
    _PKCE_STORE[state] = verifier
    auth_url = spotify_pkce.build_auth_url(
        client_id=settings.spotify_client_id,
        redirect_uri=settings.spotify_redirect_uri,
        state=state,
        challenge=challenge,
    )
    container.link_button(
        "🔑 Log in with your Spotify account", auth_url, use_container_width=True
    )
    container.caption("Full playback requires Spotify Premium.")


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
                matches = mx_client.search_tracks(track=title, artist=artist, limit=1)
                if matches:
                    best = matches[0]
                    t["title"] = best.track_name or title
                    t["artist"] = best.artist_name or artist
                    artist = t["artist"]  # nome canonico per AudioDB / Last.fm
                    title = t["title"]
                    if best.has_lyrics:
                        try:
                            lyr = mx_client.get_lyrics(best.track_id)
                            t["lyrics"] = lyr.body if lyr and not lyr.is_empty else ""
                        except MusixmatchError:
                            t["lyrics"] = ""
                    else:
                        t["lyrics"] = ""
                else:
                    t.setdefault("lyrics", "")
            except MusixmatchError:
                t.setdefault("lyrics", "")

        # 1b) Bio + immagine da AudioDB (usa il nome artista già corretto da Musixmatch)
        bio = ""
        if adb_client and artist:
            try:
                a = adb_client.get_artist(artist)
                if a:
                    bio = a.biography(lang_code) or ""
                    image_cache[artist] = a.image_url
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

    # 2) Discorsi parlati + mood + origine geografica + riassunto (una sola chiamata LLM).
    #    I track dict includono ora _bio e lyrics, usati da studio_brief().
    if settings.llm_ready:
        try:
            brief = Storyteller().studio_brief(
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
        t.setdefault("image", image_cache.get(t.get("artist", ""), ""))
        t.setdefault("audio_b64", "")
        t.setdefault("lyrics", "")

    # 4) ElevenLabs TTS — pre-generate speech audio for each track (best effort).
    # Uses getattr so the block is skipped safely if the module cache is stale.
    try:
        if getattr(settings, "elevenlabs_ready", False):
            el = ElevenLabsClient()
            for t in enriched:
                speech = t.get("speech", "").strip()
                if speech:
                    try:
                        audio_bytes = el.text_to_speech(speech)
                        t["audio_b64"] = base64.b64encode(audio_bytes).decode()
                    except Exception:
                        t["audio_b64"] = ""
    except Exception:
        pass

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
    height: 690px;
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

  .addbar {
    width: 100%; border: 0; border-radius: 12px; cursor: pointer;
    font-family: 'Space Grotesk', sans-serif; font-weight: 700;
    color: #04150b; background: linear-gradient(100deg, #1db954, #2de26d); padding: 10px 12px; font-size: .92rem;
    box-shadow: 0 0 18px rgba(29,185,84,.40); margin-bottom: 8px;
    transition: transform .15s ease, filter .15s ease;
  }
  .addbar:hover { transform: translateY(-1px); filter: brightness(1.06); }
  .addbar:disabled { opacity: .6; cursor: default; transform: none; }
  .sp-hint { color: #8f8aa8; font-size: .8rem; margin-bottom: 10px; }
  #player { text-align: center; }
  #p-art {
    width: 150px; height: 150px; object-fit: cover; border-radius: 14px;
    box-shadow: 0 10px 26px rgba(0,0,0,.5); border: 1px solid rgba(255,255,255,.10);
    margin: 6px auto 10px auto; display: none;
  }
  #p-title { font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 1rem; color: #f3f1ff; }
  #p-artist { color: #8f8aa8; font-size: .85rem; margin-bottom: 8px; }
  .p-controls { display: flex; align-items: center; justify-content: center; gap: 12px; }
  #p-toggle {
    width: 46px; height: 46px; border-radius: 50%; border: 0; cursor: pointer;
    color: #fff; font-size: 1.1rem; background: linear-gradient(100deg, #ff2d78, #f97316);
    box-shadow: 0 0 18px rgba(255,45,120,.4);
  }
  #p-time { color: #8f8aa8; font-family: 'JetBrains Mono', monospace; font-size: .78rem; }
  #p-msg { color: #8f8aa8; font-size: .78rem; margin-top: 10px; }
  #need-login { color: #8f8aa8; font-size: .9rem; padding: 12px 4px; }

  /* ---- Lyrics panel ---- */
  #lyrics-section { margin-top: 14px; }
  #lyrics-box {
    height: 200px; overflow-y: auto; padding: 10px 14px;
    background: rgba(255,255,255,.03); border-radius: 12px;
    border: 1px solid rgba(255,255,255,.08); scroll-behavior: smooth;
  }
  .lyr-line {
    font-size: .86rem; line-height: 1.85; color: #8f8aa8;
    padding: 2px 6px; border-radius: 6px;
    transition: color .35s ease, background .35s ease;
  }
  .lyr-line.active { color: #f3f1ff; font-weight: 600; background: rgba(249,115,22,.12); }
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
    <div class="col">
      <div class="col-h">Player</div>
      <button id="addPlaylist" class="addbar" style="display:none">&#43; Add this playlist to your profile</button>
      <div id="add-status" class="sp-hint"></div>
      <div id="need-login" style="display:none">Log in to your Spotify in the sidebar to enable the player and playback.</div>
      <div id="player" style="display:none">
        <img id="p-art"/>
        <div id="p-title">&mdash;</div>
        <div id="p-artist"></div>
        <div class="p-controls">
          <button id="p-toggle">&#9654;</button>
          <span id="p-time">0:00</span>
        </div>
        <div id="p-msg">Starting player&hellip;</div>
      </div>
      <div id="lyrics-section" style="display:none;">
        <div class="col-h" style="margin-top:12px;">Lyrics</div>
        <div id="lyrics-box"></div>
      </div>
    </div>
  </div>

<script>
  const TRACKS = __TRACKS__;
  const TTSLANG = "__TTSLANG__";
  const TOKEN = "__TOKEN__";
  const PLAYLIST_NAME = "__PLAYLIST__";
  const PALETTE = ["#ff2d78","#f97316","#22d3ee","#facc15","#c2410c","#34d399"];

  let player = null;
  let deviceId = null;
  let currentAudio = null;
  let shuffleOn = false;
  let autoSeq = false;
  let awaitingEnd = false;
  let playingConfirmed = false;
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
  const pArt = document.getElementById('p-art');
  const pTitle = document.getElementById('p-title');
  const pArtist = document.getElementById('p-artist');
  const pMsg = document.getElementById('p-msg');

  function setStatus(s) { statusEl.textContent = s; }
  function setAddStatus(s) { document.getElementById('add-status').textContent = s; }
  function setPMsg(s) { pMsg.textContent = s; }

  function esc(s) {
    const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML;
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
      '</div>';
    row.querySelector('.ti-play').addEventListener('click', (e) => {
      e.stopPropagation(); autoSeq = false; runTrack(i, true, false);
    });
    row.querySelector('.ti-body').addEventListener('click', () => {
      autoSeq = false; stopAudio(); runTrack(i, false, false);
    });
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
  }

  // ---- Lyrics ----
  function showLyrics(i) {
    const t = TRACKS[i];
    const section = document.getElementById('lyrics-section');
    const box = document.getElementById('lyrics-box');
    if (!t.lyrics || !t.lyrics.trim()) { section.style.display = 'none'; return; }
    section.style.display = 'block';
    const lines = t.lyrics.split('\n')
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('****') && !l.toLowerCase().includes('commercial use'));
    box.innerHTML = lines.map((l, idx) =>
      '<div class="lyr-line" data-idx="' + idx + '">' + esc(l) + '</div>'
    ).join('');
  }

  function syncLyrics(position, duration) {
    const box = document.getElementById('lyrics-box');
    const lines = box.querySelectorAll('.lyr-line');
    if (!lines.length || !duration) return;
    const idx = Math.min(Math.floor((position / duration) * lines.length), lines.length - 1);
    let changed = false;
    lines.forEach((el, i) => {
      const was = el.classList.contains('active');
      el.classList.toggle('active', i === idx);
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

  async function resolveUri(t) {
    if (t.uri) return t.uri;
    if (!TOKEN) return '';
    try {
      const q = encodeURIComponent('track:' + t.title + ' artist:' + t.artist);
      const r = await api('/search?type=track&limit=1&q=' + q);
      if (r.ok) {
        const d = await r.json();
        const it = d.tracks && d.tracks.items && d.tracks.items[0];
        if (it) {
          t.uri = it.uri;
          const img = it.album && it.album.images && it.album.images[0];
          if (img) { t.art = img.url; if (!t.image) t.image = img.url; }
          return t.uri;
        }
      }
    } catch (e) {}
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
    try { if (player) player.pause(); } catch (e) {}
  }

  function speak(text, audioB64, onend) {
    // Stop anything currently playing.
    try { window.speechSynthesis.cancel(); } catch (e) {}
    if (currentAudio) { try { currentAudio.pause(); } catch (e) {} currentAudio = null; }

    if (audioB64) {
      // ElevenLabs pre-rendered MP3.
      const audio = new Audio('data:audio/mpeg;base64,' + audioB64);
      currentAudio = audio;
      audio.onended = () => { currentAudio = null; onend && onend(); };
      audio.onerror = () => { currentAudio = null; onend && onend(); };
      audio.play().catch(() => { currentAudio = null; onend && onend(); });
      return;
    }

    // Fallback: browser Web Speech API.
    if (!text) { onend && onend(); return; }
    const u = new SpeechSynthesisUtterance(text);
    if (TTSLANG) u.lang = TTSLANG;
    u.rate = 0.98; u.pitch = 1.0;
    u.onend = () => onend && onend();
    u.onerror = () => onend && onend();
    window.speechSynthesis.speak(u);
  }

  async function startSong(i, seq) {
    if (!TOKEN) { setStatus('Log in to Spotify to listen'); if (seq) setTimeout(advance, 1500); return; }
    setStatus('🔎 Searching for track on Spotify…');
    const uri = await resolveUri(TRACKS[i]);
    if (!uri) { setStatus('Track not found on Spotify'); if (seq) setTimeout(advance, 1500); return; }
    if (!deviceId) { setPMsg('Player not ready yet: try again in a moment.'); setStatus('Player not ready'); if (seq) setTimeout(advance, 2500); return; }
    playingConfirmed = false;
    try {
      const r = await api('/me/player/play?device_id=' + deviceId, { method: 'PUT', body: JSON.stringify({ uris: [uri] }) });
      if (!r.ok && r.status !== 204) { setPMsg('Playback: ' + r.status + ' (Premium required?)'); }
      setStatus('🎧 Now playing…');
      if (seq) awaitingEnd = true;
    } catch (e) {
      setStatus('Playback error'); if (seq) setTimeout(advance, 1500);
    }
  }

  function runTrack(i, withVoice, seq) {
    current = i;
    highlight(i);
    showCenter(i);
    if (withVoice) {
      setStatus('🗣️ Narrating…');
      speak(TRACKS[i].speech, TRACKS[i].audio_b64 || '', () => startSong(i, seq));
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

  document.getElementById('p-toggle').addEventListener('click', () => {
    if (player) { try { player.togglePlay(); } catch (e) {} }
  });

  // ---- Aggiungi la playlist al profilo dell'utente ----
  document.getElementById('addPlaylist').addEventListener('click', async () => {
    if (!TOKEN || !TRACKS.length) return;
    const btn = document.getElementById('addPlaylist');
    btn.disabled = true; setAddStatus('Creating playlist on your profile…');
    try {
      const me = await (await api('/me')).json();
      const created = await (await api('/users/' + me.id + '/playlists', {
        method: 'POST',
        body: JSON.stringify({ name: PLAYLIST_NAME || 'Sonder', public: false,
          description: 'Curated by Sonder' })
      })).json();
      const uris = [];
      for (const t of TRACKS) { const u = await resolveUri(t); if (u) uris.push(u); }
      for (let k = 0; k < uris.length; k += 100) {
        await api('/playlists/' + created.id + '/tracks', {
          method: 'POST', body: JSON.stringify({ uris: uris.slice(k, k + 100) })
        });
      }
      setAddStatus('✓ Added to your profile (' + uris.length + ' tracks.');
    } catch (e) {
      setAddStatus('Error while adding: ' + e);
    }
    btn.disabled = false;
  });

  // ---- Web Playback SDK (riproduzione col proprio account, Premium) ----
  window.onSpotifyWebPlaybackSDKReady = () => {
    if (!TOKEN) return;
    player = new Spotify.Player({
      name: 'Sonder',
      getOAuthToken: cb => cb(TOKEN),
      volume: 0.8
    });
    player.addListener('ready', ({ device_id }) => { deviceId = device_id; setPMsg('Player ready ✓'); });
    player.addListener('not_ready', () => { deviceId = null; setPMsg('Player not available.'); });
    player.addListener('initialization_error', ({ message }) => setPMsg('Init: ' + message));
    player.addListener('authentication_error', ({ message }) => setPMsg('Authentication: ' + message));
    player.addListener('account_error', ({ message }) => setPMsg('Account: Spotify Premium required.'));
    player.addListener('playback_error', ({ message }) => setPMsg('Playback: ' + message));
    player.addListener('player_state_changed', onState);
    player.connect();
  };

  function fmt(ms) {
    const s = Math.floor((ms || 0) / 1000);
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  function onState(state) {
    if (!state) return;
    const cur = state.track_window.current_track;
    if (cur) {
      pTitle.textContent = cur.name;
      pArtist.textContent = (cur.artists || []).map(a => a.name).join(', ');
      const img = cur.album && cur.album.images && cur.album.images[0];
      if (img) { pArt.src = img.url; pArt.style.display = 'block'; }
    }
    document.getElementById('p-toggle').innerHTML = state.paused ? '&#9654;' : '&#10073;&#10073;';
    document.getElementById('p-time').textContent = fmt(state.position) + ' / ' + fmt(state.duration);

    if (current >= 0) syncLyrics(state.position, state.duration);
    if (!state.paused && state.position > 0) playingConfirmed = true;
    const prev = state.track_window.previous_tracks;
    if (autoSeq && awaitingEnd && playingConfirmed && state.paused && state.position === 0 &&
        prev && prev[0] && cur && prev[0].id === cur.id) {
      awaitingEnd = false; advance();
    }
  }

  // Stato iniziale dell'area player a seconda del login.
  if (TOKEN) {
    document.getElementById('player').style.display = 'block';
    document.getElementById('addPlaylist').style.display = 'block';
  } else {
    document.getElementById('need-login').style.display = 'block';
  }
</script>
<script src="https://sdk.scdn.co/spotify-player.js"></script>
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
            "audio_b64": t.get("audio_b64", ""),
            "lyrics": t.get("lyrics", ""),
        }
        for t in tracks
    ]
    tracks_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    playlist_name = json.dumps(
        f"Sonder · {studio.get('prompt', '')[:60]}", ensure_ascii=False
    ).strip('"')
    rendered = (
        STUDIO_HTML.replace("__TRACKS__", tracks_json)
        .replace("__TTSLANG__", tts_lang or "")
        .replace("__PLAYLIST__", playlist_name)
        .replace("__TOKEN__", spotify_token())
    )
    components.html(rendered, height=820, scrolling=False)


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
    avatar = "😈" if msg["role"] == "assistant" else None
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

        if msg.get("reasoning"):
            with st.expander("🧠 Model reasoning chain", expanded=False):
                st.markdown(msg["reasoning"])

        tracks = msg.get("tracks") or []
        if tracks:
            st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)
            st.markdown("##### 🎧 Suggested tracks")
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


def handle_user_input(prompt: str, lang_name: str, lang_code: str) -> None:
    """Elabora il messaggio utente: conversazione + eventuale costruzione dello studio."""
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

    teller = Storyteller()

    with st.spinner("Thinking..."):
        try:
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["messages"]
            ]
            content, reasoning = teller.converse(
                messages=history,
                language=lang_name,
                context=st.session_state.get("context", ""),
            )
            text, tracks = Storyteller.extract_playlist(content)
        except StorytellerError as exc:
            st.session_state["messages"].append(
                {"role": "assistant", "content": f"⚠️ LLM: {exc}"}
            )
            st.session_state["studio"] = empty_studio(prompt)
            return

    # Rileva rifiuto off-topic: il modello emette [NON_MUSICALE] se l'argomento
    # non riguarda la musica (istruzione nel CHAT_SYSTEM_PROMPT).
    if "[NON_MUSICALE]" in text:
        clean = text.replace("[NON_MUSICALE]", "").strip()
        if not clean:
            key = lang_name if lang_name in REFUSALS else "Italiano"
            clean = REFUSALS[key]
        st.session_state["messages"].append({"role": "assistant", "content": clean})
        return

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


def render_example_prompts() -> None:
    """Renders clickable example prompt cards on the startup page."""
    st.markdown(
        '<p class="hero-sub">Music curation &amp; emotional storytelling powered by AI. '
        'Type a prompt below — or pick one of these to get started.</p>',
        unsafe_allow_html=True,
    )
    st.markdown("")
    cols = st.columns(3)
    for i, (icon, text) in enumerate(EXAMPLE_PROMPTS):
        with cols[i % 3]:
            if st.button(f"{icon}  {text}", key=f"_ex_{i}", use_container_width=True):
                st.session_state["_pending_example"] = text
                st.rerun()
    st.markdown("")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(
        page_title="Sonder",
        page_icon="😈",
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

    # Sidebar
    render_status_sidebar()
    render_spotify_login(st.sidebar)
    st.sidebar.markdown("---")
    ui_language = st.sidebar.selectbox("🌍 Narration language", list(LANGUAGES.keys()), index=0)
    lang_name, lang_code = LANGUAGES[ui_language]
    if lang_name == "Auto":
        st.sidebar.caption("Auto mode: I'll reply in the language of your message.")

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

    st.sidebar.markdown("---")
    if st.sidebar.button("➕ New chat", use_container_width=True):
        init_chat(ui_language)
    st.sidebar.caption(f"LLM model: `{settings.llm_model}`")

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
    else:
        st.markdown('<hr class="hr-glow">', unsafe_allow_html=True)
        # Mostra i messaggi della conversazione (indice 0 = saluto iniziale, nascosto).
        for i, msg in enumerate(st.session_state.get("messages", [])):
            if i == 0:
                continue  # saluto iniziale: rimane nel contesto LLM ma non viene mostrato
            render_message(i, msg)
        if len(st.session_state.get("messages", [])) <= 1:
            render_example_prompts()

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


if __name__ == "__main__":
    main()
