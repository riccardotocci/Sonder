"""Sonder orchestration pipeline, ported from the Streamlit ``app.py``.

The functions here are the same Musixmatch -> TheAudioDB -> LLM -> Songstats flow
the original app ran, but rewritten as PURE functions: no ``st.session_state``,
no ``st.cache_data``, no spinners. The per-user Spotify token is passed in
explicitly so the process-wide ``lru_cache`` helpers stay thread-safe inside the
FastAPI worker threadpool.
"""
from __future__ import annotations

import base64
import functools
import random
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core import (
    settings,
    MusixmatchClient,
    MusixmatchError,
    AudioDBClient,
    AudioDBError,
    Storyteller,
    StorytellerError,
    SpotifyClient,
    SpotifyError,
    SongstatsClient,
    ReccoBeatsClient,
)
from core.elevenlabs_client import ElevenLabsClient
from core.config import SONGSTATS_MIN_STREAMS
from .geo_coords import resolve_coordinates, country_name, to_iso2

from .constants import (
    REFUSALS,
    GREETINGS,
    musixmatch_translation_code,
    _plan_translation_lang,
    resolve_narration_lang,
    strip_narration_source_label,
    compact_text,
    user_facing_llm_error,
)


# --------------------------------------------------------------------------- #
# Step-by-step processing log (router, search, writer, studio…)
# --------------------------------------------------------------------------- #
class PipelineLog:
    """Mutable list of {step, detail} entries, replacing the Streamlit llm_log."""

    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []

    def add(self, step: str, detail: str = "") -> None:
        self.entries.append({"step": step, "detail": detail})

    def snapshot(self) -> list[dict[str, str]]:
        return list(self.entries)


# --------------------------------------------------------------------------- #
# Musixmatch lyric/richsync/translation fetch
# --------------------------------------------------------------------------- #
def fetch_musixmatch_text(
    mx_client: MusixmatchClient,
    track_id: int,
    has_lyrics: bool,
    has_richsync: bool,
    translation_lang: str = "",
    need_language: bool = False,
    prefer_plain_lyrics: bool = False,
) -> tuple[str, list[dict[str, Any]], str, str]:
    lyrics_text = ""
    translated_text = ""
    lyrics_language = ""
    richsync_body: list[dict[str, Any]] = []
    # Senza Spotify i testi SINCRONIZZATI (richsync) non vengono mai mostrati: lo
    # Studio usa solo la vista statica con testo ORIGINALE + TRADUZIONE. In quel
    # caso (``prefer_plain_lyrics``) preferiamo il testo PIATTO e PULITO di
    # ``track.lyrics.get`` invece di ricostruirlo dalle righe del richsync (che
    # possono essere spezzate per parola). Saltiamo il richsync solo se esiste
    # comunque il testo piatto a cui ripiegare (``has_lyrics``); altrimenti lo
    # teniamo per ricavare le righe come fallback.
    fetch_richsync = has_richsync and not (prefer_plain_lyrics and has_lyrics)
    if fetch_richsync:
        try:
            richsync = mx_client.get_richsync(track_id)
            if richsync and not richsync.is_empty:
                richsync_body = richsync.body
                lyrics_text = richsync.text
        except MusixmatchError:
            pass
    # Recupera i testi quando manca il corpo (il richsync non c'e' o e' stato
    # saltato), quando serve la LINGUA del testo per il filtro lingua
    # (``need_language``) oppure quando vogliamo il testo piatto pulito
    # (``prefer_plain_lyrics``). Se il richsync ha gia' dato il testo e nulla di
    # tutto cio' serve, evitiamo la chiamata extra a Musixmatch (rate limit).
    if has_lyrics and (not lyrics_text or need_language or prefer_plain_lyrics):
        try:
            lyrics = mx_client.get_lyrics(track_id)
            if lyrics:
                lyrics_language = (lyrics.language or "").strip().lower()
                if not lyrics_text and not lyrics.is_empty:
                    lyrics_text = lyrics.body
        except MusixmatchError:
            pass
    if translation_lang:
        try:
            translation = mx_client.get_lyrics_translation(track_id, translation_lang)
            translated_text = (
                translation.body if translation and not translation.is_empty else ""
            )
        except MusixmatchError:
            translated_text = ""
    return lyrics_text, richsync_body, translated_text, lyrics_language


def musixmatch_track_payload(
    mx_client: MusixmatchClient,
    track: Any,
    reason: str = "",
    translation_lang: str = "",
    analysis: dict[str, Any] | None = None,
    need_language: bool = False,
    prefer_plain_lyrics: bool = False,
) -> dict[str, Any]:
    lyrics_text, richsync_body, translated_text, lyrics_language = fetch_musixmatch_text(
        mx_client,
        track.track_id,
        track.has_lyrics,
        track.has_richsync,
        translation_lang=translation_lang,
        need_language=need_language,
        prefer_plain_lyrics=prefer_plain_lyrics,
    )
    payload = {
        "title": track.track_name,
        "artist": track.artist_name,
        "album": track.album_name,
        "track_id": str(track.track_id),
        "reason": reason,
        "lyrics": lyrics_text,
        "lyrics_language": lyrics_language,
        "translated_lyrics": translated_text,
        "translation_lang": translation_lang,
        "richsync": richsync_body,
        "has_lyrics": track.has_lyrics,
        "has_richsync": track.has_richsync,
    }
    # Copertina album dal catalogo Musixmatch (track.search/track.get espongono
    # album_coverart_*). La impostiamo SUBITO dal risultato di ricerca, cosi' la
    # card "Dettagli brano per brano" ha l'artwork REALE di Musixmatch anche se
    # l'enrichment (get_track) non viene rieseguito o non la ritrova. Solo se non
    # vuota, per non disabilitare il fallback di build_studio
    # (``t.setdefault("cover", best.cover_art)``). Niente foto-artista TheAudioDB:
    # la card legge esclusivamente ``cover``.
    cover_art = str(getattr(track, "cover_art", "") or "").strip()
    if cover_art:
        payload["cover"] = cover_art
    # Genere rinforzato da Musixmatch (generi primari della traccia).
    genres = [str(g).strip() for g in (getattr(track, "genres", None) or []) if str(g).strip()]
    if genres:
        payload["mx_genres"] = genres
        payload["genre"] = genres[0]
    # Mood/temi testuali dall'analisi dei testi. Se non e' gia' disponibile
    # (es. dalla ricerca per significato), la si recupera per track_id.
    if analysis is None:
        analysis = mx_client.get_lyrics_analysis(track.track_id)
    moods = MusixmatchClient.analysis_moods(analysis)
    themes = MusixmatchClient.analysis_themes(analysis)
    if moods:
        payload["mx_moods"] = moods
    if themes:
        payload["mx_themes"] = themes
    # Marker: l'analisi e' gia' stata tentata qui, cosi' l'enrichment in
    # build_studio non rifa' la stessa chiamata quando i mood sono vuoti.
    payload["mx_analysis_done"] = True
    return payload


# --------------------------------------------------------------------------- #
# ISRC -> country (fallback per la nazione del brano)
# --------------------------------------------------------------------------- #
def isrc_country(isrc: str | None) -> str | None:
    """Estrae il country code (2 lettere) dal prefisso di un ISRC.

    Il primo gruppo di un ISRC (es. ``IT-B00-25-00020`` / ``ITB002500020`` -> ``IT``)
    e' il codice del paese del *registrant* dell'ISRC: e' il paese di REGISTRAZIONE
    del codice, NON necessariamente il paese di pubblicazione del brano: e' l'unica
    fonte usata per la nazione del brano nello Studio (l'ISRC arriva da Musixmatch
    ``track.get`` o, in fallback, da Spotify).

    Funzione pura e tollerante: input vuoti/``None``/malformati restituiscono
    ``None`` senza sollevare eccezioni. Ritorna il prefisso a 2 lettere in
    maiuscolo solo per un ISRC strutturalmente valido (12 caratteri alfanumerici:
    2 lettere paese + 3 alfanumerici registrant + 2 cifre anno + 5 cifre seriale).
    """
    if not isrc:
        return None
    # Normalizza la forma "leggibile" rimuovendo trattini/spazi di separazione.
    cleaned = "".join(ch for ch in str(isrc) if ch.isalnum()).upper()
    if len(cleaned) != 12:
        return None
    country, registrant, year_serial = cleaned[:2], cleaned[2:5], cleaned[5:]
    if not (country.isalpha() and registrant.isalnum() and year_serial.isdigit()):
        return None
    return country


# --------------------------------------------------------------------------- #
# Songstats (real stats + popularity floor)
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=512)
def _resolve_isrc(title: str, artist: str, user_token: str = "") -> str:
    if not title:
        return ""
    if not (user_token or settings.spotify_ready):
        return ""
    try:
        client = SpotifyClient(access_token=user_token) if user_token else SpotifyClient()
        track = client.search_track(title, artist or None)
    except Exception:  # noqa: BLE001
        return ""
    return (track.isrc if track else "") or ""


@functools.lru_cache(maxsize=512)
def _musixmatch_isrc(track_id: str) -> str:
    """ISRC di una traccia dal catalogo Musixmatch (``track.get``).

    ``track.search`` restituisce un oggetto traccia ridotto SENZA ISRC, mentre
    ``track.get`` espone ``track_isrc`` (+ ``commontrack_isrcs``). E' la fonte
    primaria della nazione del brano: cosi' la geografia funziona anche senza
    Spotify. Cache di processo (lo stesso track_id ricorre tra build) e tollerante:
    ritorna "" quando Musixmatch non e' configurato, manca il track_id o la
    chiamata fallisce.
    """
    if not settings.musixmatch_ready or not track_id:
        return ""
    try:
        tid = int(track_id)
    except (TypeError, ValueError):
        return ""
    if tid <= 0:
        return ""
    try:
        track = MusixmatchClient().get_track(tid)
    except Exception:  # noqa: BLE001
        return ""
    return (getattr(track, "isrc", "") if track else "") or ""


@functools.lru_cache(maxsize=512)
def _songstats_track_stats(
    title: str, artist: str, user_token: str = ""
) -> dict[str, Any] | None:
    if not settings.songstats_ready or not (title or artist):
        return None
    isrc = _resolve_isrc(title, artist, user_token)
    if not isrc:
        return None
    try:
        stats = SongstatsClient().track_stats_by_isrc(isrc, title, artist)
    except Exception:  # noqa: BLE001
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


@functools.lru_cache(maxsize=512)
def _reccobeats_features(
    title: str, artist: str, user_token: str = ""
) -> dict[str, Any] | None:
    """Audio features (valence/energy/...) di una traccia via ReccoBeats.

    ReccoBeats e' gratuito e senza key, ma richiede un identificatore: riusiamo
    l'ISRC gia' risolto da Spotify (vedi ``_resolve_isrc``). Ritorna un dict
    serializzabile con le features + un'etichetta ``mood``, oppure ``None`` se
    l'ISRC non e' risolvibile o ReccoBeats non ha dati (degrada con grazia).
    """
    if not (title or artist):
        return None
    isrc = _resolve_isrc(title, artist, user_token)
    if not isrc:
        return None
    feats = ReccoBeatsClient().audio_features(isrc=isrc)
    if not feats or feats.is_empty:
        return None
    return {
        "valence": feats.valence,
        "energy": feats.energy,
        "danceability": feats.danceability,
        "acousticness": feats.acousticness,
        "instrumentalness": feats.instrumentalness,
        "liveness": feats.liveness,
        "loudness": feats.loudness,
        "speechiness": feats.speechiness,
        "tempo": feats.tempo,
        "key": feats.key,
        "mode": feats.mode,
        "mood": feats.mood,
        "isrc": isrc,
    }


# Songstats rejects bursts of more than ~8 simultaneous requests (they fail with
# rate/limit errors), so every batch of Songstats lookups is processed in
# sequential chunks of at most SONGSTATS_MAX_CONCURRENCY: each chunk runs its
# requests concurrently, but the next chunk only starts once the current one is
# done. See AGENTS.md "Songstats" for the rationale.
SONGSTATS_MAX_CONCURRENCY = 2


def _map_in_chunks(func, items, chunk_size: int = SONGSTATS_MAX_CONCURRENCY):
    """Map ``func`` over ``items`` in sequential batches of at most ``chunk_size``.

    Within a batch the calls run concurrently (one thread each), but no more than
    ``chunk_size`` run at the same time and the next batch waits for the current
    one to finish — keeping Songstats under its burst limit.
    """
    results: list[Any] = []
    for start in range(0, len(items), chunk_size):
        batch = items[start : start + chunk_size]
        if not batch:
            continue
        with ThreadPoolExecutor(max_workers=min(chunk_size, len(batch))) as executor:
            results.extend(executor.map(func, batch))
    return results


def select_known_candidates(
    candidates: list[tuple[Any, str]],
    limit: int,
    user_token: str = "",
    max_select: int | None = None,
) -> tuple[list[tuple[Any, str, dict[str, Any] | None]], list[str]]:
    """Pick well-known tracks, replacing obscure ones (task 4).

    Returns up to ``max_select`` candidates (default ``limit``). When the caller
    needs a larger pool to backfill after a later filter (e.g. the language
    filter), it passes a higher ``max_select`` so extra qualifying tracks are
    available without re-querying Songstats.
    """
    cap = limit if max_select is None else max_select
    notes: list[str] = []
    if not candidates:
        return [], notes
    if not settings.songstats_ready:
        return [(match, reason, None) for match, reason in candidates[:cap]], notes

    def lookup(item: tuple[Any, str]) -> dict[str, Any] | None:
        match, _reason = item
        return _songstats_track_stats(
            getattr(match, "track_name", ""), getattr(match, "artist_name", ""), user_token
        )

    # Songstats can't handle more than ~8 concurrent requests, so process the
    # candidate lookups in sequential chunks of SONGSTATS_MAX_CONCURRENCY.
    stats_list = _map_in_chunks(lookup, candidates)

    selected: list[tuple[Any, str, dict[str, Any] | None]] = []
    dropped = 0
    for (match, reason), stats in zip(candidates, stats_list):
        if len(selected) >= cap:
            break
        if stats:
            streams = int(stats.get("total_streams", 0) or 0)
            if streams and streams < SONGSTATS_MIN_STREAMS:
                dropped += 1
                continue
        selected.append((match, reason, stats))
    if dropped:
        notes.append(
            f"Songstats: {dropped} brano/i poco noto/i sostituito/i "
            f"(sotto {SONGSTATS_MIN_STREAMS:,} stream)."
        )
    if not selected and candidates:
        return [(match, reason, None) for match, reason in candidates[:cap]], notes
    return selected, notes


# Soglia minima di "track_rating" Musixmatch (0-100, indice di popolarita'/qualita'
# del match): le tracce sotto questa soglia vengono scartate dalle ricerche tematiche
# perche' di solito sono match deboli o brani molto marginali. Non si applica alle
# query con titolo/artista ESPLICITO, dove va rispettato il brano richiesto.
MUSIXMATCH_MIN_TRACK_RATING = 35


def _track_rating(track: Any) -> int | None:
    """Estrae il ``track_rating`` (0-100) dal payload grezzo Musixmatch.

    Ritorna ``None`` quando il campo non e' presente o non e' numerico.
    """
    raw = getattr(track, "raw", {}) or {}
    if raw.get("track_rating") is None:
        return None
    try:
        return int(raw.get("track_rating"))
    except (TypeError, ValueError):
        return None


def _below_rating_threshold(track: Any) -> bool:
    """True se la traccia va scartata per qualita' insufficiente.

    Scarta sia i brani con ``track_rating`` PRESENTE e sotto la soglia, sia quelli
    SENZA ``track_rating``: un rating mancante e' trattato come brano sconosciuto e
    di poco valore, quindi va escluso dalle ricerche tematiche.
    """
    rating = _track_rating(track)
    return rating is None or rating < MUSIXMATCH_MIN_TRACK_RATING


def search_musixmatch_from_plan(
    plan: dict[str, Any],
    lang_name: str,
    user_token: str = "",
    translation_lang: str = "",
    search_languages: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not settings.musixmatch_ready:
        return [], ["Musixmatch not configured: set `MUSIXMATCH_API_KEY` or `MXM_KEY`."]

    notes: list[str] = []
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    mx_client = MusixmatchClient()
    # The caller passes the single resolved narration language so the translated
    # lyrics stay aligned with the generated narration; fall back only if omitted.
    translation_lang = translation_lang or _plan_translation_lang(plan, lang_name)
    try:
        limit = int(plan.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 10))

    queries = plan.get("queries") or []
    if not isinstance(queries, list):
        queries = []

    # Filtro per lingua (rinforzo della scelta lingua): se l'utente ha scelto
    # delle lingue di ricerca, scarteremo i brani la cui LINGUA DEL TESTO rilevata
    # (Musixmatch ``lyrics_language``) non e' tra quelle selezionate. I brani con
    # lingua sconosciuta vengono mantenuti (non si puo' provarne l'errore), e il
    # filtro NON si applica alle ricerche per titolo/artista esplicito, dove il
    # brano richiesto va rispettato anche se in altra lingua. Calcoliamo tutto qui
    # perche' quando il filtro e' attivo serve un POOL piu' ampio di candidati per
    # ripescare brani sostitutivi e arrivare comunque a ``limit``.
    allowed = {str(code).strip().upper() for code in (search_languages or []) if str(code).strip()}
    # L'override "brano esplicito" (che spegne il filtro lingua) vale solo se la
    # sorgente TESTI e' attiva: con i testi disattivati le query esplicite vengono
    # ignorate, quindi non devono nemmeno alterare il filtro lingua dei risultati
    # per significato. Cosi' le due sorgenti restano davvero indipendenti.
    has_explicit_track = settings.musixmatch_use_lyrics and any(
        isinstance(q, dict) and (str(q.get("q_track", "")).strip() or str(q.get("q_artist", "")).strip())
        for q in queries
    )
    # La lingua del testo si recupera solo quando serve davvero filtrare, cosi'
    # le tracce con richsync non pagano una chiamata Musixmatch extra inutile.
    need_language = bool(allowed and not has_explicit_track)
    # Pool piu' ampio quando filtriamo, cosi' c'e' materiale per il ripescaggio.
    query_cap = limit * 3 if need_language else limit * 2

    candidates: list[tuple[Any, str]] = []
    # Riserva: le ALTRE tracce trovate da ogni query (oltre a quella scelta) restano
    # qui da parte. Se i filtri successivi (lingua/Songstats) ci lasciano sotto
    # ``limit``, ripeschiamo A CASO da questa riserva per arrivare comunque al numero
    # richiesto, invece di fermarci ai primi candidati scartati.
    reserve: list[tuple[Any, str]] = []
    # Sorgente 1: query basate sui TESTI (q/q_track/q_artist/q_lyrics). Disattivabile
    # con MUSIXMATCH_USE_LYRICS senza toccare il piano dell'LLM ne' il check successivo.
    for query in queries if settings.musixmatch_use_lyrics else []:
        if not isinstance(query, dict):
            continue
        if len(candidates) >= query_cap:
            break
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
                limit=5,
            )
        except MusixmatchError as exc:
            notes.append(f"Musixmatch: {exc}")
            continue
        # Invece di prendere SEMPRE il primo risultato (rating piu' alto), scegliamo
        # a caso una traccia NON ancora vista tra quelle restituite dalla query, cosi'
        # ricerche ripetute variano i brani proposti e non tornano sempre i soliti
        # popolari. Eccezione: per le query con titolo/artista ESPLICITO teniamo il
        # match migliore, perche' li' l'utente vuole proprio quel brano specifico.
        is_explicit = bool(q_track or q_artist)
        fresh = [m for m in matches if m.track_id not in seen]
        # Soglia di qualita': sulle ricerche tematiche scartiamo i match con
        # track_rating sotto la soglia. Sulle query esplicite NON filtriamo, per
        # rispettare il brano specifico richiesto (anche se poco popolare).
        if not is_explicit:
            fresh = [m for m in fresh if not _below_rating_threshold(m)]
        if not fresh:
            continue
        match = fresh[0] if is_explicit else random.choice(fresh)
        seen.add(match.track_id)
        candidates.append((match, reason))
        # Le ALTRE tracce fresh di questa query (che hanno gia' passato la soglia di
        # rating) vanno in riserva per un eventuale ripescaggio. Solo per le query
        # tematiche: sulle query esplicite l'utente vuole un brano preciso, non altri.
        if not is_explicit:
            for other in fresh:
                if other.track_id in seen:
                    continue
                seen.add(other.track_id)
                reserve.append((other, reason))

    # Fonte EXTRA: ricerca semantica per "significato" (analysis.search). Le query
    # q_lyrics restano prioritarie (vanno in testa ai candidati, soprattutto per
    # eventi/nomi propri); il meaning aggiunge candidati per i significati profondi
    # e astratti. Ogni traccia porta gia' la sua analisi, quindi la riusiamo senza
    # un secondo round-trip. Le chiamate sono lente (~5s) quindi vanno in parallelo.
    analysis_by_id: dict[int, dict[str, Any]] = {}
    meanings = plan.get("meanings") or []
    phrases = [
        str(m.get("meaning", "")).strip() if isinstance(m, dict) else str(m).strip()
        for m in (meanings if isinstance(meanings, list) else [])
    ]
    phrases = [p for p in phrases if p][:6]
    # Sorgente 2: ricerca per SIGNIFICATO (endpoint track.lyrics.analysis.search).
    # Disattivabile con MUSIXMATCH_USE_MEANING; indipendente dalla sorgente 1.
    if phrases and settings.musixmatch_use_meaning:
        def run_meaning(meaning: str) -> list[tuple[Any, dict[str, Any]]]:
            try:
                return MusixmatchClient().search_lyrics_analysis(meaning, limit=6)
            except MusixmatchError as exc:
                notes.append(f"Musixmatch (significato): {exc}")
                return []

        with ThreadPoolExecutor(max_workers=min(6, len(phrases))) as executor:
            meaning_results = list(executor.map(run_meaning, phrases))
        # Cap totale dei candidati per limitare le lookup Songstats (che girano in
        # chunk sequenziali). Le query restano prioritarie (sono gia' in testa).
        # Pool piu' ampio quando filtriamo per lingua, per avere riserve da ripescare.
        candidate_cap = limit * 4 if need_language else limit * 3
        for res in meaning_results:
            if len(candidates) >= candidate_cap:
                break
            for track, analysis in res:
                if len(candidates) >= candidate_cap:
                    break
                if track.track_id in seen:
                    continue
                # Stessa soglia di qualita' applicata alla ricerca per significato
                # (rating sotto soglia O assente -> scartato).
                if _below_rating_threshold(track):
                    continue
                seen.add(track.track_id)
                analysis_by_id[track.track_id] = analysis
                candidates.append((track, "ricerca per significato"))

    # Quando filtriamo per lingua chiediamo l'INTERO pool qualificato (non solo i
    # primi ``limit``), cosi' restano riserve da cui ripescare i sostituti.
    max_select = len(candidates) if need_language else limit
    selected, floor_notes = select_known_candidates(
        candidates, limit, user_token, max_select=max_select
    )
    notes.extend(floor_notes)

    def build_payload(item: tuple[Any, str, dict[str, Any] | None]) -> dict[str, Any]:
        match, reason, stats = item
        payload = musixmatch_track_payload(
            MusixmatchClient(),
            match,
            reason=reason,
            translation_lang=translation_lang,
            analysis=analysis_by_id.get(match.track_id),
            need_language=need_language,
            prefer_plain_lyrics=not user_token,
        )
        if stats:
            payload["songstats"] = stats
        return payload

    def build_batch(items: list[tuple[Any, str, dict[str, Any] | None]]) -> list[dict[str, Any]]:
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(items))) as executor:
            return list(executor.map(build_payload, items))

    # Costruiamo i payload a lotti e li accumuliamo in ``kept`` fino a ``limit``.
    # Quando il filtro lingua e' attivo scartiamo i brani la cui lingua del testo non
    # e' tra quelle selezionate (i brani con lingua sconosciuta restano: non si puo'
    # provarne l'errore).
    kept: list[dict[str, Any]] = []
    dropped_lang = 0

    def absorb(pool: list[tuple[Any, str, dict[str, Any] | None]]) -> None:
        nonlocal dropped_lang
        idx = 0
        while idx < len(pool) and len(kept) < limit:
            batch = pool[idx : idx + (limit - len(kept))]
            idx += len(batch)
            for payload in build_batch(batch):
                if need_language:
                    lang = str(payload.get("lyrics_language") or "").strip().upper()
                    if lang and lang not in allowed:
                        dropped_lang += 1
                        continue
                kept.append(payload)
                if len(kept) >= limit:
                    break

    absorb(selected)

    # RIPESCAGGIO: finche' siamo sotto ``limit`` e c'e' riserva, peschiamo A CASO un
    # blocco di tracce extra (mai scelte) dalla riserva, le passiamo per il filtro
    # Songstats e poi per lo stesso filtro lingua, e le aggiungiamo. Cosi' arriviamo
    # sempre a ``limit`` quando il materiale c'e', invece di fermarci ai primi scarti.
    # Il blocco e' sovradimensionato (needed * 3) per assorbire gli scarti del filtro.
    while len(kept) < limit and reserve:
        needed = limit - len(kept)
        random.shuffle(reserve)
        chunk = reserve[: needed * 3]
        reserve = reserve[needed * 3 :]
        extra_selected, extra_notes = select_known_candidates(
            chunk, limit, user_token, max_select=len(chunk)
        )
        notes.extend(extra_notes)
        absorb(extra_selected)

    if dropped_lang:
        note = (
            f"Lingua: {dropped_lang} brano/i scartato/i perche' non "
            f"nelle lingue selezionate ({', '.join(sorted(allowed))})."
        )
        if len(kept) < limit:
            note += " Candidati esauriti: non e' stato possibile rimpiazzarli tutti."
        else:
            note += " Rimpiazzati con altri brani nelle lingue scelte."
        notes.append(note)
    results = kept

    return results, notes


# --------------------------------------------------------------------------- #
# TheAudioDB ordered context
# --------------------------------------------------------------------------- #
def fetch_audiodb_ordered_context(
    client: AudioDBClient, *, artist: str, title: str = "", album: str = "", lang_code: str = "EN"
) -> dict[str, str]:
    empty = {"song_news": "", "album_news": "", "artist_description": "", "combined": ""}
    get_ordered_context = getattr(client, "get_ordered_context", None)
    if not callable(get_ordered_context):
        return empty
    try:
        sections = get_ordered_context(artist=artist, title=title, album=album, language=lang_code)
    except TypeError:
        sections = get_ordered_context(artist=artist, title=title, language=lang_code)
    if not isinstance(sections, dict):
        return empty
    return {key: str(sections.get(key) or "").strip() for key in empty}


def fetch_audiodb_music_fact(
    client: AudioDBClient, *, artist: str, title: str = "", album: str = "", lang_code: str = "EN"
) -> str:
    get_music_fact = getattr(client, "get_music_fact", None)
    if not callable(get_music_fact):
        return ""
    try:
        fact = get_music_fact(artist=artist, title=title, album=album, language=lang_code)
    except TypeError:
        fact = get_music_fact(artist=artist, title=title, language=lang_code)
    return str(fact or "").strip()


def fetch_audiodb_track_text(
    client: AudioDBClient, *, artist: str, title: str = "", album: str = "", lang_code: str = "EN"
) -> str:
    get_track_text = getattr(client, "get_track_text", None)
    if not callable(get_track_text):
        return ""
    try:
        text = get_track_text(artist=artist, title=title, album=album, language=lang_code)
    except TypeError:
        text = get_track_text(artist=artist, title=title, language=lang_code)
    return str(text or "").strip()


# --------------------------------------------------------------------------- #
# ElevenLabs narration (on-demand, one track at a time)
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=256)
def _persisted_voice_id() -> str:
    return settings.elevenlabs_voice_id or ElevenLabsClient.DEFAULT_VOICE


@functools.lru_cache(maxsize=256)
def elevenlabs_narration(
    text: str,
    voice_id: str,
    model_id: str,
    output_format: str,
) -> dict:
    """Generate MP3 + per-word time marks for *text* (cached by content)."""
    audio, marks = ElevenLabsClient().text_to_speech_with_marks(
        text,
        voice_id=voice_id,
        model_id=model_id,
        output_format=output_format,
    )
    return {"audio_b64": base64.b64encode(audio).decode("ascii"), "marks": marks}


def generate_tts(text: str) -> dict:
    """Public TTS entrypoint used by the /api/tts endpoint. Returns {audio_b64, marks}."""
    text = (text or "").strip()[:3500]
    if not text or not settings.elevenlabs_ready:
        return {"audio_b64": "", "marks": []}
    return elevenlabs_narration(
        text,
        _persisted_voice_id(),
        ElevenLabsClient.DEFAULT_MODEL,
        ElevenLabsClient.DEFAULT_OUTPUT_FORMAT,
    )


# --------------------------------------------------------------------------- #
# Studio build
# --------------------------------------------------------------------------- #
def empty_studio(prompt: str) -> dict:
    return {"prompt": prompt, "tracks": [], "summary": "", "moods": []}


def _fallback_speech(t: dict) -> str:
    """Costruisce un testo narrato dalle fonti grezze (Musixmatch + TheAudioDB).

    Usato come ripiego (demo mode / LLM non disponibile / narrazione vuota) cosi'
    un brano ha sempre qualcosa da raccontare.
    """
    musixmatch_source = str(t.get("lyrics") or t.get("reason") or "").strip()
    audiodb_source = str(
        t.get("audio_db_song_news")
        or t.get("audio_db_album_news")
        or t.get("audio_db_artist_description")
        or t.get("audio_db_text")
        or t.get("audio_db_fact")
        or t.get("_bio")
        or ""
    ).strip()
    parts = [
        compact_text(src, 220)
        for src in (musixmatch_source, audiodb_source)
        if src
    ]
    return " ".join(parts).strip() if parts else ""


def generate_narration_speeches(
    prompt: str,
    tracks: list[dict[str, Any]],
    lang_name: str,
    llm_model: str = "",
) -> list[str]:
    """Fase 2: genera i testi narrati per ogni brano.

    E' la chiamata LLM lenta (studio_brief), scorporata da build_studio cosi' lo
    Studio puo' renderizzare subito (fase 1) e popolare la narrazione dopo. La
    narrazione mancante mostra una barra di caricamento e disabilita i comandi di
    narrazione finche' questa funzione non risponde. Ritorna una lista di testi
    allineata a ``tracks``.
    """
    speeches = ["" for _ in tracks]
    if settings.llm_ready:
        try:
            brief = Storyteller(model=llm_model or settings.llm_model).studio_brief(
                title=prompt, tracks=tracks, language=lang_name
            )
        except StorytellerError:
            brief = {}
        narrations = brief.get("narrations") or []
        for i in range(len(tracks)):
            n = narrations[i] if i < len(narrations) else {}
            # Single merged speech: the LLM intertwines Musixmatch + TheAudioDB.
            speeches[i] = strip_narration_source_label(str(n.get("speech", "")).strip())
    # Ripiego per ogni testo vuoto (demo / errore LLM / risposta incompleta).
    for i, t in enumerate(tracks):
        if not speeches[i].strip():
            speeches[i] = _fallback_speech(t)
    return speeches


def build_studio(
    prompt: str,
    tracks: list[dict[str, str]],
    lang_name: str,
    lang_code: str,
    translation_lang: str = "",
    llm_model: str = "",
    user_token: str = "",
    log: PipelineLog | None = None,
    with_narration: bool = True,
) -> dict:
    """Enrich tracks with speech, artist image, geo and mood (ported from app.py).

    ``with_narration=False`` salta la chiamata LLM studio_brief (fase 2): lo Studio
    si carica subito con tutte le info dei servizi e i testi narrati restano vuoti,
    da popolare via ``generate_narration_speeches`` / ``/api/narrate``.
    """
    log = log or PipelineLog()
    enriched: list[dict] = [dict(t) for t in tracks]
    summary = ""
    moods: list[str] = []

    translation_lang = translation_lang or musixmatch_translation_code(lang_name, lang_code)
    # valence/energy provengono dalle audio-features di Spotify: serve un token
    # utente (PKCE) oppure le credenziali client. L'endpoint e' deprecato, quindi
    # puo' non rispondere: in quel caso i valori restano vuoti e il grafico si nasconde.
    spotify_enabled = bool(user_token or settings.spotify_ready)

    def enrich_track(t: dict) -> None:
        artist = t.get("artist", "")
        title = t.get("title", "")
        mx = MusixmatchClient() if settings.musixmatch_ready else None

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
                    # Spotify ID dal catalogo Musixmatch (stesso dato che darebbe
                    # track.lyrics.fingerprint): costruisce l'URI esatto del player
                    # SENZA ricerca testuale fuzzy ne' login Spotify (l'embed e'
                    # pubblico) e fa puntare la freccia "apri su Spotify" al brano
                    # giusto. Spotify resta un fallback piu' sotto.
                    if best.spotify_id:
                        t.setdefault("spotify_id", best.spotify_id)
                        t.setdefault("uri", f"spotify:track:{best.spotify_id}")
                    # Copertina dell'album dal catalogo Musixmatch: da' a ogni brano
                    # un'artwork reale anche senza TheAudioDB/Spotify (l'hero e le card
                    # dello Studio leggono t["image"]; t["cover"] resta il campo
                    # dedicato). Durata ed explicit completano i metadati mostrati.
                    if best.cover_art:
                        t.setdefault("cover", best.cover_art)
                        if not t.get("image"):
                            t["image"] = best.cover_art
                    if best.duration:
                        t.setdefault("duration", best.duration)
                    t.setdefault("explicit", best.explicit)
                    # Mood comes from the real Musixmatch genre, not the LLM.
                    if best.genres and not t.get("mood"):
                        t["mood"] = best.genres[0]
                    # Genere rinforzato da Musixmatch (generi primari della traccia).
                    if best.genres:
                        t.setdefault("mx_genres", list(best.genres))
                        t.setdefault("genre", best.genres[0])
                    # Mood/temi testuali dall'analisi dei testi: si recuperano solo
                    # se non sono gia' arrivati dalla ricerca (query/significato),
                    # per non aggiungere round-trip inutili.
                    if not t.get("mx_moods") and not t.get("mx_analysis_done"):
                        analysis = mx.get_lyrics_analysis(best.track_id)
                        moods = MusixmatchClient.analysis_moods(analysis)
                        themes = MusixmatchClient.analysis_themes(analysis)
                        if moods:
                            t["mx_moods"] = moods
                        if themes and not t.get("mx_themes"):
                            t["mx_themes"] = themes
                        t["mx_analysis_done"] = True
                    artist = t["artist"]
                    title = t["title"]
                    if not t.get("lyrics") and not t.get("richsync"):
                        lyrics_text, richsync_body, translated_text, lyrics_language = fetch_musixmatch_text(
                            mx, best.track_id, best.has_lyrics, best.has_richsync,
                            translation_lang=translation_lang,
                            prefer_plain_lyrics=not user_token,
                        )
                        t["lyrics"] = lyrics_text
                        t["richsync"] = richsync_body
                        t["translated_lyrics"] = translated_text
                        t["translation_lang"] = translation_lang
                        if lyrics_language and not t.get("lyrics_language"):
                            t["lyrics_language"] = lyrics_language
                    elif not t.get("translated_lyrics"):
                        try:
                            translation = mx.get_lyrics_translation(best.track_id, translation_lang)
                            t["translated_lyrics"] = (
                                translation.body if translation and not translation.is_empty else ""
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

        bio = ""
        if settings.audiodb_ready and artist:
            try:
                adb = AudioDBClient()
                a = adb.get_artist(artist)
                if a:
                    bio = a.biography(lang_code) or ""
                    t["image"] = a.image_url
                    # La geografia NON usa piu' TheAudioDB: la nazione del brano
                    # arriva solo dal prefisso ISRC (vedi loop finale). Qui restano
                    # solo bio, immagine e mood reali dell'artista.
                    # Mood reale di TheAudioDB a livello artista (fallback).
                    if a.mood and not t.get("mood"):
                        t["mood"] = a.mood
                album = str(t.get("album", ""))
                # Mood a livello brano: piu' specifico del genere Musixmatch,
                # quindi ha la precedenza quando disponibile (cache condivisa).
                adb_track = adb.search_track(artist, title) if title else None
                if adb_track and adb_track.get("strMood"):
                    t["mood"] = adb_track["strMood"]
                ctx = fetch_audiodb_ordered_context(
                    adb, artist=artist, title=title, album=album, lang_code=lang_code
                )
                if ctx.get("song_news"):
                    t["audio_db_song_news"] = ctx["song_news"]
                if ctx.get("album_news"):
                    t["audio_db_album_news"] = ctx["album_news"]
                if ctx.get("artist_description"):
                    t["audio_db_artist_description"] = ctx["artist_description"]
                if ctx.get("combined"):
                    t["audio_db_text"] = ctx["combined"]
                if not t.get("audio_db_text"):
                    text = fetch_audiodb_track_text(
                        adb, artist=artist, title=title, album=album, lang_code=lang_code
                    )
                    if text:
                        t["audio_db_text"] = text
                if not t.get("audio_db_fact"):
                    fact = fetch_audiodb_music_fact(
                        adb, artist=artist, title=title, album=album, lang_code=lang_code
                    )
                    if fact:
                        t["audio_db_fact"] = fact
            except AudioDBError:
                pass

        # La nazione d'origine del brano viene derivata ESCLUSIVAMENTE dal prefisso
        # ISRC (primi 2 caratteri) nel loop finale: niente piu' TheAudioDB ne'
        # MusicBrainz per la geografia.

        t["_bio"] = bio

        # ISRC dal catalogo Musixmatch: track.get espone track_isrc/commontrack_isrcs
        # (track.search no). E' la fonte PRIMARIA della nazione del brano, cosi' la
        # geografia funziona anche senza Spotify; Spotify resta come fallback sotto.
        if not t.get("isrc"):
            mx_isrc = _musixmatch_isrc(str(t.get("track_id") or ""))
            if mx_isrc:
                t["isrc"] = mx_isrc

        # Lyric Fingerprint (track.lyrics.fingerprint.post, prodotto "Sentinel"):
        # "dove possibile" stabilizza l'identita' del brano partendo dal TESTO,
        # recuperando Spotify ID/ISRC/genere canonici quando la ricerca per
        # titolo/artista e' incerta. La risposta ha gli stessi campi di track.get.
        # OFF di default (settings.musixmatch_use_fingerprint): e' un endpoint
        # Enterprise e su piani inferiori risponde 403. Degrada in silenzio.
        if (
            mx
            and settings.musixmatch_use_fingerprint
            and not (t.get("spotify_id") and t.get("isrc"))
        ):
            try:
                fp_matches = mx.fingerprint_lyrics(str(t.get("lyrics") or ""), limit=1)
            except MusixmatchError:
                fp_matches = []
            if fp_matches:
                fp_track, fp_similarity = fp_matches[0]
                # Solo match molto forti possono correggere l'identita' del brano.
                if fp_similarity >= 80.0:
                    if fp_track.spotify_id and not t.get("spotify_id"):
                        t["spotify_id"] = fp_track.spotify_id
                        t.setdefault("uri", f"spotify:track:{fp_track.spotify_id}")
                    if fp_track.isrc and not t.get("isrc"):
                        t["isrc"] = fp_track.isrc
                    if fp_track.genres and not t.get("genre"):
                        t["genre"] = fp_track.genres[0]
                        t.setdefault("mx_genres", list(fp_track.genres))
                    if fp_track.cover_art and not t.get("cover"):
                        t["cover"] = fp_track.cover_art
                        if not t.get("image"):
                            t["image"] = fp_track.cover_art
                    if fp_track.duration and not t.get("duration"):
                        t["duration"] = fp_track.duration

        # Resolve the track on Spotify to get its URI (used by the studio player).
        # valence/energy NON arrivano piu' da Spotify (endpoint deprecato): vedi il
        # blocco ReccoBeats piu' sotto.
        if spotify_enabled and title:
            try:
                sp_client = (
                    SpotifyClient(access_token=user_token)
                    if user_token
                    else SpotifyClient()
                )
                found = sp_client.search_track(title, artist or None)
                if found and found.uri:
                    t.setdefault("uri", found.uri)
                # L'ISRC identifica univocamente il brano: lo esponiamo cosi' la
                # freccia "apri su Spotify" punta al brano esatto (search isrc:...)
                # invece di una ricerca testuale per titolo/artista (approssimativa).
                if found and found.isrc:
                    t.setdefault("isrc", found.isrc)
                # Copertina album da Spotify (found.album_image = album.images[0].url):
                # artwork REALE dell'album, NON una foto-artista. Musixmatch NON
                # fornisce le cover (l'API ufficiale non ha il campo e il vecchio
                # ws/1.1 ritorna solo "nocover.png"), quindi Spotify e' la fonte
                # delle copertine quando collegato. Riempie t["cover"] solo se
                # Musixmatch non ne ha gia' data una, cosi' la card "Dettagli brano
                # per brano" mostra l'artwork album senza mai ricorrere a TheAudioDB.
                if found and found.album_image and not t.get("cover"):
                    t["cover"] = found.album_image
            except SpotifyError:
                pass

    if enriched:
        # Keep concurrency low: TheAudioDB's shared free test key ("123") and
        # Musixmatch rate-limit bursts of simultaneous requests, which surfaced in
        # production as "reached a rate/request limit" errors mid-build.
        with ThreadPoolExecutor(max_workers=min(3, len(enriched))) as executor:
            list(executor.map(enrich_track, enriched))

    # Audio features (valence/energy/...) da ReccoBeats: gratuito, senza key, e
    # sostituisce le audio-features di Spotify (deprecate). Richiede l'ISRC, che
    # viene risolto da Spotify dentro _reccobeats_features.
    if spotify_enabled:
        def attach_features(t: dict[str, Any]) -> None:
            # Guardia locale: il fallimento di una traccia non deve abortire il
            # batch ne' la build dello studio (degradazione morbida).
            try:
                feats = _reccobeats_features(
                    str(t.get("title", "")), str(t.get("artist", "")), user_token
                )
            except Exception:  # noqa: BLE001
                return
            if not feats:
                return
            t["audio_features"] = feats
            t["valence"] = float(feats["valence"])
            t["energy"] = float(feats["energy"])

        targets = [t for t in enriched if t.get("title")]
        if targets:
            with ThreadPoolExecutor(max_workers=min(4, len(targets))) as executor:
                list(executor.map(attach_features, targets))
            log.add(
                "ReccoBeats audio-features",
                f"Resolved valence/energy for "
                f"{sum(1 for t in enriched if t.get('audio_features'))} "
                f"of {len(targets)} track(s).",
            )

    # Fase 2 (narrazione): la chiamata LLM lenta studio_brief genera ``t["speech"]``.
    # Quando with_narration=False i testi restano vuoti e vengono popolati piu' tardi
    # via generate_narration_speeches (/api/narrate), cosi' lo Studio appare subito.
    # mood (genere Musixmatch) e origin (TheAudioDB/MusicBrainz) provengono da dati
    # reali durante l'enrichment; valence/energy da ReccoBeats (vedi sopra).
    if with_narration:
        speeches = generate_narration_speeches(
            prompt, enriched, lang_name, llm_model=llm_model
        )
        for t, speech in zip(enriched, speeches):
            t["speech"] = speech

    for t in enriched:
        t.pop("_bio", None)
        t.pop("mx_analysis_done", None)
        t.setdefault("speech", "")
        t.setdefault("musixmatch_speech", "")
        t.setdefault("audiodb_speech", "")
        t.setdefault("mood", "")
        t.setdefault("genre", "")
        t.setdefault("spotify_id", "")
        t.setdefault("cover", "")
        t.setdefault("duration", 0)
        t.setdefault("explicit", False)
        t.setdefault("mx_genres", [])
        t.setdefault("mx_moods", [])
        t.setdefault("mx_themes", [])
        # Nazione del brano dal prefisso ISRC (primi 2 caratteri = paese del
        # registrant dell'ISRC). E' l'UNICA fonte per la geografia: niente
        # TheAudioDB/MusicBrainz. NB: e' il paese di REGISTRAZIONE, non garantito
        # uguale al paese di pubblicazione, e si applica solo quando il prefisso e'
        # un paese reale e mappabile (i prefissi non-paese come "QM"/"ZZ" restano
        # senza pin sulla mappa).
        if not t.get("origin_code"):
            isrc_cc = isrc_country(str(t.get("isrc") or ""))
            iso2 = to_iso2(isrc_cc) if isrc_cc else ""
            if iso2:
                t["origin_code"] = iso2
                t["origin"] = country_name(iso2)
        t.setdefault("origin", "")
        # Garantisce l'ISO2 anche quando arriva solo il nome del paese: la mappa
        # colora i poligoni confrontando l'ISO2, quindi senza codice lo stato non si
        # colorerebbe pur avendo l'etichetta.
        if not t.get("origin_code") and t.get("origin"):
            t["origin_code"] = to_iso2(str(t["origin"]))
        t.setdefault("origin_code", "")
        t.setdefault("valence", None)
        t.setdefault("energy", None)
        t.setdefault("audio_features", None)
        # Pin sulla mappa a livello PAESE: centroide del paese dalla tabella interna,
        # preferendo l'ISO2 (strCountryCode / MusicBrainz) che risolve anche quando
        # l'origine leggibile e' una stringa disordinata come "London, England".
        if t.get("lat") is None or t.get("lng") is None:
            lat, lng = resolve_coordinates(str(t.get("origin_code") or t.get("origin") or ""))
            t["lat"] = lat
            t["lng"] = lng
        t.setdefault("image", "")
        t.setdefault("audio_b64", "")
        t.setdefault("speech_marks", [])
        t.setdefault("lyrics", "")
        t.setdefault("translated_lyrics", "")
        t.setdefault("translation_lang", translation_lang)
        t.setdefault("richsync", [])
        t.setdefault("audio_db_song_news", "")
        t.setdefault("audio_db_album_news", "")
        t.setdefault("audio_db_artist_description", "")
        t.setdefault("audio_db_text", "")
        t.setdefault("audio_db_fact", "")

    if settings.elevenlabs_ready:
        log.add(
            "ElevenLabs TTS",
            "Narration audio is generated on demand through the TTS endpoint, one track at a time.",
        )
    else:
        log.add("ElevenLabs TTS", "ELEVENLABS_API_KEY is missing: narration audio is disabled.")

    return {"prompt": prompt, "tracks": enriched, "summary": summary, "moods": moods}


def compose_track_list_reply(tracks: list[dict[str, str]]) -> str:
    """Plain-text chat reply listing the tracks found.

    The chat bubble is a simple numbered list of the tracks, with no global
    summary (which has been removed from the studio brief), so no extra LLM call.
    """
    lines: list[str] = []
    for i, t in enumerate(tracks):
        title = str(t.get("title", "")).strip()
        artist = str(t.get("artist", "")).strip()
        if not title:
            continue
        lines.append(f"{i + 1}. {title}" + (f" — {artist}" if artist else ""))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Seed da artista/brano: testi + temi da Musixmatch -> prompt per il router LLM
# --------------------------------------------------------------------------- #
def _clean_lyrics_excerpt(text: str, limit: int = 600) -> str:
    """Pulisce un testo Musixmatch per usarlo come seed.

    Il piano gratuito accoda al testo (parziale) un disclaimer di copyright dopo
    una riga di asterischi (``*** ... ***``): tagliamo a quel marcatore e
    compattiamo gli spazi, troncando a ``limit`` caratteri.
    """
    raw = (text or "").split("***", 1)[0]
    return compact_text(raw, limit)


def fetch_seed_material(
    artist: str, song: str = "", *, max_tracks: int = 4
) -> dict[str, Any]:
    """Recupera da Musixmatch testi + temi/mood per un artista (e brano opzionale).

    Con un brano specifico cerca il match preciso (artista + titolo); col solo
    artista prende i suoi brani migliori. Ogni traccia porta temi, mood, generi e
    un estratto del testo. Funzione pura/thread-safe (istanzia il proprio client).
    Degrada con grazia: se Musixmatch non e' configurato, l'artista e' vuoto o non
    ci sono risultati, ``tracks`` resta una lista vuota.
    """
    artist = (artist or "").strip()
    song = (song or "").strip()
    material: dict[str, Any] = {
        "artist": artist,
        "song": song,
        "tracks": [],
        "themes": [],
        "moods": [],
    }
    if not settings.musixmatch_ready or not artist:
        return material
    mx = MusixmatchClient()
    try:
        tracks = mx.search_tracks(
            track=song or None,
            artist=artist,
            has_lyrics=True,
            limit=1 if song else max_tracks,
        )
    except MusixmatchError:
        return material
    tracks = tracks[: 1 if song else max_tracks]
    if not tracks:
        return material

    def describe(track: Any) -> dict[str, Any]:
        analysis = mx.get_lyrics_analysis(track.track_id)
        moods = MusixmatchClient.analysis_moods(analysis)
        themes = MusixmatchClient.analysis_themes(analysis)
        excerpt = ""
        if track.has_lyrics:
            try:
                lyrics = mx.get_lyrics(track.track_id)
                if lyrics and not lyrics.is_empty:
                    excerpt = _clean_lyrics_excerpt(lyrics.body)
            except MusixmatchError:
                excerpt = ""
        return {
            "title": track.track_name,
            "artist": track.artist_name,
            "themes": themes,
            "moods": moods,
            "excerpt": excerpt,
            "genres": [str(g).strip() for g in (track.genres or []) if str(g).strip()],
        }

    with ThreadPoolExecutor(max_workers=min(4, len(tracks))) as executor:
        described = list(executor.map(describe, tracks))

    all_themes: list[str] = []
    all_moods: list[str] = []
    for d in described:
        for theme in d["themes"]:
            if theme not in all_themes:
                all_themes.append(theme)
        for mood in d["moods"]:
            if mood not in all_moods:
                all_moods.append(mood)
    material["tracks"] = described
    material["themes"] = all_themes
    material["moods"] = all_moods
    return material


def build_seed_prompt(
    artist: str, song: str = "", *, material: dict[str, Any] | None = None
) -> str:
    """Compone il prompt seed (testi + temi) per il router ``plan_musixmatch_search``.

    Interroga Musixmatch per l'artista/brano scelto e impacchetta testi e temi in
    un messaggio utente in linguaggio naturale: e' lo stesso ingresso che il primo
    LLM (router) riformula nelle query, esattamente come per un prompt scritto a mano.
    Restituisce sempre una stringa non vuota (fallback coi soli nomi in demo mode).
    Il chiamante puo' passare ``material`` gia' recuperato per evitare una seconda
    chiamata a Musixmatch (es. dopo il check "brano non trovato" lato endpoint).
    """
    artist = (artist or "").strip()
    song = (song or "").strip()
    if material is None:
        material = fetch_seed_material(artist, song)
    tracks = material.get("tracks") or []

    head = (
        f'Voglio una playlist ispirata all\'artista "{artist}"'
        + (f' e in particolare al brano "{song}"' if song else "")
        + "."
    )
    # Fallback: senza materiale da Musixmatch lasciamo al router un seed minimo coi
    # soli nomi, cosi' la pipeline funziona comunque (demo mode / artista ignoto).
    if not tracks:
        return (
            head
            + " Proponi brani con atmosfere, temi e significati affini a quelli"
            " tipici di questo artista."
        )

    lines = [head, "", "Da Musixmatch ho raccolto questi testi e temi:"]
    for d in tracks:
        lines.append("")
        lines.append(f"- {d['artist']} — {d['title']}")
        if d.get("themes"):
            lines.append(f"  Temi: {', '.join(d['themes'][:8])}")
        if d.get("moods"):
            lines.append(f"  Mood: {', '.join(d['moods'][:8])}")
        if d.get("genres"):
            lines.append(f"  Generi: {', '.join(d['genres'][:4])}")
        if d.get("excerpt"):
            lines.append(f'  Estratto del testo: "{d["excerpt"]}"')

    themes = material.get("themes") or []
    moods = material.get("moods") or []
    if themes:
        lines.append("")
        lines.append(f"Temi ricorrenti: {', '.join(themes[:10])}.")
    if moods:
        lines.append(f"Mood ricorrenti: {', '.join(moods[:10])}.")
    lines.append("")
    lines.append(
        "Proponi una playlist di brani con atmosfere, temi e significati affini"
        " a questi testi."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Chat pipeline (ported from handle_user_input -> pure function)
# --------------------------------------------------------------------------- #
def run_chat(
    *,
    messages: list[dict[str, str]],
    prompt: str,
    lang_name: str,
    lang_code: str,
    search_languages: list[str] | None = None,
    llm_model: str = "",
    user_token: str = "",
    with_narration: bool = True,
) -> dict:
    """Process a user message: conversation + optional studio build.

    ``messages`` is the prior history (excluding this prompt). Returns
    ``{"assistant": {...}, "studio": {...} | None}``.

    ``with_narration=False`` builds the studio WITHOUT the slow studio_brief call,
    so the UI gets the tracks + service data immediately and fetches the narration
    in a second phase (see ``generate_narration_speeches`` / ``/api/narrate``).
    """
    log = PipelineLog()
    log.add("User request", prompt)
    model = llm_model or settings.llm_model

    history = [{"role": m["role"], "content": m["content"]} for m in messages]
    history.append({"role": "user", "content": prompt})

    if not settings.llm_ready:
        log.add("LLM skipped", "LLM_API_KEY is missing; the reasoning pipeline cannot run.")
        return {
            "assistant": {
                "role": "assistant",
                "content": "LLM not configured: set `LLM_API_KEY` (and "
                "`LLM_BASE_URL`/`LLM_MODEL`) to populate the studio. "
                "Showing empty structure for now.",
                "llm_log": log.snapshot(),
            },
            "studio": empty_studio(prompt),
        }

    teller = Storyteller(model=model)
    log.add("LLM model", model)
    if search_languages:
        log.add("Search languages", ", ".join(search_languages))

    # 1) Search router
    try:
        plan = teller.plan_musixmatch_search(
            messages=history,
            language=lang_name,
            context="",
            search_languages=search_languages or None,
        )
        # Auto mode removed: the language ALWAYS follows the selected UI language
        # (even if the user writes in another language). Every generated text
        # (response writer + studio narrations) AND the Musixmatch translated
        # lyrics use this exact language, so they can never diverge nor leak the
        # source language.
        narration_name, narration_code, translation_code = resolve_narration_lang(
            plan, lang_name, lang_code
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
        log.add(
            "Search router",
            f"music_related={plan.get('music_related', True)}, "
            f"needs_search={plan.get('needs_search', True)}, "
            f"limit={plan.get('limit', 8)}, "
            f"narration_lang={plan.get('narration_lang') or '(auto)'} -> {narration_name}, "
            f"query_count={len(query_details)}"
            + ("\nQueries: " + "; ".join(query_details) if query_details else ""),
        )
    except StorytellerError as exc:
        log.add("Search router failed", user_facing_llm_error(exc))
        return {
            "assistant": {"role": "assistant", "content": user_facing_llm_error(exc), "llm_log": log.snapshot()},
            "studio": empty_studio(prompt),
        }

    # 2) Scope check
    if not plan.get("music_related", True):
        key = lang_name if lang_name in REFUSALS else "English"
        log.add("Scope check", "The request was classified as outside the music domain.")
        return {
            "assistant": {"role": "assistant", "content": REFUSALS[key], "llm_log": log.snapshot()},
            "studio": None,
        }

    # 3) Direct conversation (no search)
    if not plan.get("needs_search", True):
        try:
            content, reasoning = teller.converse(
                messages=history, language=narration_name, context=""
            )
            text, _ = Storyteller.extract_playlist(content)
            log.add("Conversation response", "Generated a direct music-domain answer without a Musixmatch search.")
        except StorytellerError as exc:
            log.add("Conversation response failed", user_facing_llm_error(exc))
            return {
                "assistant": {"role": "assistant", "content": user_facing_llm_error(exc), "llm_log": log.snapshot()},
                "studio": empty_studio(prompt),
            }
        if "[NON_MUSICALE]" in text:
            key = lang_name if lang_name in REFUSALS else "English"
            text = text.replace("[NON_MUSICALE]", "").strip() or REFUSALS[key]
        return {
            "assistant": {
                "role": "assistant", "content": text, "reasoning": reasoning,
                "tracks": [], "llm_log": log.snapshot(),
            },
            "studio": empty_studio(prompt),
        }

    # 4) Musixmatch search
    tracks, notes = search_musixmatch_from_plan(
        plan, lang_name, user_token, translation_lang=translation_code,
        search_languages=search_languages,
    )
    log.add("Musixmatch search", f"Found {len(tracks)} track(s)." + ("\n" + "\n".join(notes) if notes else ""))

    # 5) Studio build (single LLM call: studio_brief generates ONLY the two speeches
    # per track + valence/energy; mood, origin and coordinates come from real data).
    # The chat reply is a plain list of the tracks found, so the whole playlist path
    # costs exactly two LLM calls: search router + studio brief.
    if not tracks:
        notes_text = "\n".join(f"> {note}" for note in notes) if notes else ""
        no_results = (
            "Non ho trovato brani adatti a questa richiesta. "
            "Prova con un prompt più specifico (artista, titolo o tema)."
        )
        text = (no_results + ("\n\n" + notes_text if notes_text else "")) if notes_text else no_results
        return {
            "assistant": {
                "role": "assistant", "content": text, "reasoning": "",
                "tracks": [], "llm_log": log.snapshot(),
            },
            "studio": None,
        }

    studio = build_studio(
        prompt, tracks, narration_name, narration_code,
        translation_lang=translation_code,
        llm_model=model, user_token=user_token, log=log,
        with_narration=with_narration,
    )
    log.add("Studio built", f"Narration, photos and geography ready for {len(studio.get('tracks', []))} track(s).")

    text = compose_track_list_reply(tracks)
    if notes:
        text = text + "\n\n" + "\n".join(f"> {note}" for note in notes)

    studio["llm_log"] = log.snapshot()
    assistant = {
        "role": "assistant", "content": text, "reasoning": "",
        "tracks": tracks, "llm_log": log.snapshot(),
    }
    return {"assistant": assistant, "studio": studio}


# --------------------------------------------------------------------------- #
# Spotify "inspired by your listening" themes (task 10)
# --------------------------------------------------------------------------- #
def fetch_spotify_top_listening(user_token: str) -> dict[str, Any] | None:
    import requests

    if not user_token:
        return None
    headers = {"Authorization": f"Bearer {user_token}"}
    artists: list[str] = []
    genres: list[str] = []
    tracks: list[str] = []
    try:
        ra = requests.get(
            "https://api.spotify.com/v1/me/top/artists?limit=20&time_range=medium_term",
            headers=headers, timeout=10,
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
            headers=headers, timeout=10,
        )
        if rt.ok:
            for t in rt.json().get("items", []):
                name = t.get("name", "")
                performers = ", ".join(a.get("name", "") for a in t.get("artists", []))
                if name:
                    tracks.append(f"{name} — {performers}".strip(" —"))
    except requests.RequestException:
        return None
    seen: set[str] = set()
    genres = [g for g in genres if g and not (g in seen or seen.add(g))]
    if not (artists or tracks or genres):
        return None
    return {"artists": artists, "genres": genres, "tracks": tracks}


def get_spotify_theme_recs(lang_name: str, user_token: str, llm_model: str = "") -> dict:
    """Returns {themes:[...], no_scope:bool}."""
    if not settings.llm_ready or not user_token:
        return {"themes": [], "no_scope": False}
    data = fetch_spotify_top_listening(user_token)
    if not data or data.get("_no_scope"):
        return {"themes": [], "no_scope": bool(data and data.get("_no_scope"))}
    try:
        themes = Storyteller(model=llm_model or settings.llm_model).suggest_listening_themes(
            artists=data.get("artists", []),
            tracks=data.get("tracks", []),
            genres=data.get("genres", []),
            language=lang_name,
        )
    except StorytellerError:
        themes = []
    return {"themes": themes, "no_scope": False}


# --------------------------------------------------------------------------- #
# Spotify playlist creation (from a conversation's tracks)
# --------------------------------------------------------------------------- #
def create_spotify_playlist(
    tracks: list[dict[str, Any]], name: str, user_token: str
) -> dict:
    """Crea su Spotify la playlist suggerita dal bot. Mirror di app.py.

    Usa il token utente (flusso PKCE) ottenuto nel browser.
    """
    if not tracks:
        return {"ok": False, "error": "No tracks to add."}
    if not user_token:
        return {"ok": False, "error": "Log in with Spotify to create the playlist."}
    try:
        client = SpotifyClient(access_token=user_token)
        playlist = client.create_thematic_playlist(
            name=f"Sonder · {name}"[:100],
            description="Curated by Sonder during the conversation.",
            tracks=tracks,
        )
    except SpotifyError as exc:
        return {"ok": False, "error": f"Spotify: {exc}"}
    return {
        "ok": True,
        "name": playlist.name,
        "track_count": playlist.track_count,
        "url": playlist.url,
        "embed_url": playlist.embed_url,
    }
