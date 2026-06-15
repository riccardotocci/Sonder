# 💕 SONDER

> Piattaforma di **curatela musicale, analisi letteraria e storytelling emotivo multilingua** — Musicathon 2026.

A differenza degli algoritmi tradizionali (Spotify/Apple Music) che lavorano solo su
metadati acustici (BPM, genere), **Sonder** decodifica il *significato
poetico profondo* dei testi, collegando brani di epoche, generi e lingue diverse sotto
lo stesso filo conduttore narrativo (l'ombra, la redenzione, il conflitto umano).

---

## ✨ Features

- **Estrazione & analisi dei testi** — recupero dei testi originali e identificazione di metafore, slang e temi psicologici complessi.
- **Storytelling multilingua** — saggi brevi / micro-racconti / note di copertina che collegano i brani a un archetipo emotivo.
- **Curatela dinamica delle playlist** — playlist Spotify generate dal "vettore emotivo" emerso dall'analisi testuale.
- **UX immersiva** — interfaccia web minimale/dark, pronta per la narrazione audio (podcast-style).

---

## 🧱 Stack tecnologico

| Livello | Tecnologia |
|---|---|
| Frontend / UI | Streamlit |
| Backend / logica | Python 3.10+ |
| Catalogo & testi | API Musixmatch |
| Biografie & media | API TheAudioDB |
| Motore di ragionamento | LLM "Thinking" (DeepSeek-R1 via OpenRouter, oppure OpenAI o3-mini) |
| Voce narrante | ElevenLabs TTS (MP3 generati lato server) |
| Automazione musicale | API Spotify (spotipy) |

---

## 🔁 Flusso dei dati

```
[ Input: Canzone / Artista / Tema ]
            │
            ▼
[ Musixmatch ] ─► testo grezzo + metadati traccia
            │
            ▼
[ TheAudioDB ] ─► biografia multilingua + foto artista
            │
            ▼
[ LLM Thinking ] ─► decodifica slang/metafore, fonde col bio,
                    genera analisi psicologica + micro-racconto (Markdown)
            │
            ▼
[ ElevenLabs ] ─► MP3 della voce narrante, senza fallback Web Speech nel browser
            │
            ▼
[ Spotify ] ─► genera/aggiorna la playlist tematica
            │
            ▼
[ Streamlit ] ─► storia + testi + grafica artista + player playlist
```

---

## 📁 Struttura del progetto

```
empathy-for-the-devil/
├── app.py                   # Entry point Streamlit
├── core/
│   ├── __init__.py
│   ├── config.py            # Caricamento chiavi/impostazioni da .env
│   ├── musixmatch_client.py # Chiamate e filtri API Musixmatch
│   ├── audiodb_client.py    # Biografie e immagini artisti
│   ├── storyteller.py       # Prompt e logica LLM (Thinking/Reasoning)
│   └── spotify_client.py    # Creazione automatica playlist (Spotipy)
├── .streamlit/config.toml   # Tema dark/minimale
├── .env                     # Chiavi API (NON pubblicare)
├── .env.example             # Template chiavi
├── .gitignore
└── requirements.txt
```

---

## 🚀 Avvio rapido

```bash
# 1. (consigliato) crea un ambiente virtuale
python3 -m venv .venv
source .venv/bin/activate

# 2. installa le dipendenze
pip install -r requirements.txt

# 3. configura le chiavi
cp .env.example .env      # poi apri .env e incolla le tue chiavi

# 4. avvia l'app
streamlit run app.py
```

> **Nota:** l'app si avvia anche **senza chiavi API** (modalità demo): ogni sezione
> mostra un avviso che indica quale chiave inserire nel file `.env`.

---

## 🔑 Chiavi necessarie

| Variabile | Dove ottenerla | Obbligatoria |
|---|---|---|
| `MUSIXMATCH_API_KEY` | https://developer.musixmatch.com/ | per i testi |
| `AUDIODB_API_KEY` | https://www.theaudiodb.com/ (test = `2`) | opzionale |
| `LLM_API_KEY` | https://openrouter.ai/ o https://platform.openai.com/ | per l'analisi |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | https://elevenlabs.io/ | per la voce narrante |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | https://developer.spotify.com/dashboard | per le playlist |

---

## 🗺️ Roadmap hackathon

- **Giorno 1** — Setup ambiente, chiavi e test isolati delle API (Musixmatch, TheAudioDB).
- **Giorno 2** — Prompt engineering sull'LLM (analisi psicologica + micro-racconto).
- **Giorno 3** — Interfaccia Streamlit minimale e integrazione dei flussi di testo.
- **Giorno 4 (Effetto Wow)** — Integrazione partner (es. ElevenLabs per la voce narrante) e rifinitura del pitch.
