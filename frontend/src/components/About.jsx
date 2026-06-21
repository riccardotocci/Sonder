import { useEffect, useState } from "react";
import { useT } from "../i18n.jsx";

// Contenuti dell'About co-locati nel componente (prosa lunga: non ha senso
// gonfiare il dizionario i18n con questi blocchi). Tradotti in tutte e 9 le
// lingue dell'interfaccia; il fallback all'inglese resta come difesa.
const CONTENT = {
  en: {
    kicker: "About the project",
    tagline:
      "the realization that every person carries an inner world as vivid and complex as your own.",
    ideaHeading: "The idea",
    ideaLead:
      "Sonder takes a theme, a feeling, a message — or simply an artist and a song — and turns it into a narrated, multilingual emotional journey through real music. It doesn't just build a playlist: it tells the human story behind every track, with the voice of an AI narrator who actually read the lyrics.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Start from anything",
        text: "A theme, a mood, a sentence, or just an artist and a song. Sonder finds the music that fits.",
      },
      {
        icon: "🗣️",
        title: "A narrated journey",
        text: "An AI voice tells the emotional story behind each track, like a radio host who read between the lines.",
      },
      {
        icon: "🌍",
        title: "Multilingual by design",
        text: "Explore in 9 languages — narration, lyric translations and the whole interface follow your choice.",
      },
      {
        icon: "🗺️",
        title: "A map of origins",
        text: "See where every artist comes from, plotted on an interactive world map.",
      },
      {
        icon: "🎧",
        title: "Real, known songs",
        text: "Tracks are filtered by real streaming numbers, so you discover music that genuinely resonated.",
      },
      {
        icon: "▶️",
        title: "Listen & keep",
        text: "Play full tracks through your Spotify and save the whole journey as a playlist.",
      },
    ],
    techKicker: "Under the hood",
    techHeading: "How it works",
    techLead:
      "Behind a single prompt, Sonder chains a handful of specialized services. Everything degrades gracefully — the app boots and runs even with zero API keys, falling back to a demo mode that tells you which variable to set.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Themed lyric & track search — fetches lyrics and translations.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Artist bios, images, metadata and external IDs used to map their origins.",
      },
      {
        name: "Thinking engine (LLM)",
        text: "An OpenAI-compatible model routes your theme into balanced multilingual queries, writes the narration and derives mood & geography.",
      },
      {
        name: "ElevenLabs",
        text: "Text-to-speech turns the narration into a natural AI voice.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Per-user login for full playback and one-click playlist creation.",
      },
    ],
    stackHeading: "Built with",
    archNote:
      "A React (Vite) front-end talks to a FastAPI back-end that reuses the Python service clients; in production FastAPI also serves the built single-page app. The Studio is a self-contained interactive experience rendered in an isolated frame.",
    soonTag: "Planned",
    songstatsNote:
      "Songstats — real streaming statistics by ISRC, to keep only genuinely notable tracks — is planned but not available at the moment.",
    madeBy: "Made by",
    role: "Creator & developer of Sonder",
  },
  it: {
    kicker: "Il progetto",
    tagline:
      "la consapevolezza che ogni persona porta con sé un mondo interiore vivido e complesso quanto il tuo.",
    ideaHeading: "L'idea",
    ideaLead:
      "Sonder prende un tema, un'emozione, un messaggio — o semplicemente un artista e un brano — e lo trasforma in un viaggio emotivo narrato e multilingue attraverso musica vera. Non costruisce solo una playlist: racconta la storia umana dietro ogni brano, con la voce di un narratore AI che i testi li ha letti davvero.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Parti da qualsiasi cosa",
        text: "Un tema, un'atmosfera, una frase, o solo un artista e un brano. Sonder trova la musica giusta.",
      },
      {
        icon: "🗣️",
        title: "Un viaggio narrato",
        text: "Una voce AI racconta la storia emotiva dietro ogni brano, come un conduttore radio che ha letto tra le righe.",
      },
      {
        icon: "🌍",
        title: "Multilingue per natura",
        text: "Esplora in 9 lingue — narrazione, traduzioni dei testi e tutta l'interfaccia seguono la tua scelta.",
      },
      {
        icon: "🗺️",
        title: "Una mappa delle origini",
        text: "Scopri da dove viene ogni artista, posizionato su una mappa del mondo interattiva.",
      },
      {
        icon: "🎧",
        title: "Brani veri e conosciuti",
        text: "I brani sono filtrati sui numeri di streaming reali: scopri musica che ha davvero lasciato il segno.",
      },
      {
        icon: "▶️",
        title: "Ascolta e conserva",
        text: "Riproduci i brani interi con il tuo Spotify e salva l'intero viaggio come playlist.",
      },
    ],
    techKicker: "Sotto il cofano",
    techHeading: "Come funziona",
    techLead:
      "Dietro a un singolo prompt, Sonder concatena una serie di servizi specializzati. Tutto degrada con grazia — l'app si avvia e funziona anche senza nessuna chiave API, con un demo mode che ti dice quale variabile impostare.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Ricerca tematica di testi e brani — recupera testi e traduzioni.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Biografie, immagini, metadati e ID esterni degli artisti, usati per mapparne le origini.",
      },
      {
        name: "Motore di pensiero (LLM)",
        text: "Un modello OpenAI-compatible instrada il tema in query multilingue bilanciate, scrive la narrazione e ricava mood e geografia.",
      },
      {
        name: "ElevenLabs",
        text: "Il text-to-speech trasforma la narrazione in una voce AI naturale.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Accesso per-utente per la riproduzione completa e la creazione di playlist con un clic.",
      },
    ],
    stackHeading: "Costruito con",
    archNote:
      "Un front-end React (Vite) dialoga con un back-end FastAPI che riusa i client dei servizi in Python; in produzione FastAPI serve anche la single-page app compilata. Lo Studio è un'esperienza interattiva autonoma resa in un frame isolato.",
    soonTag: "Previsto",
    songstatsNote:
      "Songstats — statistiche di streaming reali per ISRC, per tenere solo i brani davvero noti — è previsto ma al momento non disponibile.",
    madeBy: "Realizzato da",
    role: "Ideatore e sviluppatore di Sonder",
  },
  fr: {
    kicker: "À propos du projet",
    tagline:
      "la prise de conscience que chaque personne porte en elle un monde intérieur aussi vivant et complexe que le vôtre.",
    ideaHeading: "L'idée",
    ideaLead:
      "Sonder prend un thème, une émotion, un message — ou simplement un artiste et une chanson — et le transforme en un voyage émotionnel narré et multilingue à travers de la vraie musique. Il ne se contente pas de créer une playlist : il raconte l'histoire humaine derrière chaque morceau, avec la voix d'un narrateur IA qui a vraiment lu les paroles.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Partez de n'importe quoi",
        text: "Un thème, une ambiance, une phrase, ou juste un artiste et une chanson. Sonder trouve la musique qui correspond.",
      },
      {
        icon: "🗣️",
        title: "Un voyage narré",
        text: "Une voix IA raconte l'histoire émotionnelle derrière chaque morceau, comme un animateur radio qui a lu entre les lignes.",
      },
      {
        icon: "🌍",
        title: "Multilingue par nature",
        text: "Explorez en 9 langues — la narration, les traductions des paroles et toute l'interface suivent votre choix.",
      },
      {
        icon: "🗺️",
        title: "Une carte des origines",
        text: "Voyez d'où vient chaque artiste, placé sur une carte du monde interactive.",
      },
      {
        icon: "🎧",
        title: "De vraies chansons connues",
        text: "Les morceaux sont filtrés selon les vrais chiffres de streaming : découvrez la musique qui a vraiment marqué.",
      },
      {
        icon: "▶️",
        title: "Écoutez et gardez",
        text: "Lisez les morceaux en entier avec votre Spotify et enregistrez tout le voyage en playlist.",
      },
    ],
    techKicker: "Sous le capot",
    techHeading: "Comment ça marche",
    techLead:
      "Derrière une seule requête, Sonder enchaîne une poignée de services spécialisés. Tout se dégrade en douceur — l'application démarre et fonctionne même sans aucune clé API, en se repliant sur un mode démo qui vous indique quelle variable définir.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Recherche thématique de paroles et de titres — récupère paroles et traductions.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Biographies, images, métadonnées et identifiants externes des artistes, utilisés pour cartographier leurs origines.",
      },
      {
        name: "Moteur de réflexion (LLM)",
        text: "Un modèle compatible OpenAI traduit votre thème en requêtes multilingues équilibrées, écrit la narration et en déduit l'ambiance et la géographie.",
      },
      {
        name: "ElevenLabs",
        text: "La synthèse vocale transforme la narration en une voix IA naturelle.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Connexion par utilisateur pour la lecture complète et la création de playlist en un clic.",
      },
    ],
    stackHeading: "Construit avec",
    archNote:
      "Un front-end React (Vite) dialogue avec un back-end FastAPI qui réutilise les clients de services en Python ; en production, FastAPI sert aussi l'application single-page compilée. Le Studio est une expérience interactive autonome rendue dans un cadre isolé.",
    soonTag: "Prévu",
    songstatsNote:
      "Songstats — des statistiques de streaming réelles par ISRC, pour ne garder que les morceaux vraiment notables — est prévu mais pas disponible pour le moment.",
    madeBy: "Réalisé par",
    role: "Créateur et développeur de Sonder",
  },
  es: {
    kicker: "Sobre el proyecto",
    tagline:
      "la conciencia de que cada persona lleva consigo un mundo interior tan vívido y complejo como el tuyo.",
    ideaHeading: "La idea",
    ideaLead:
      "Sonder toma un tema, una emoción, un mensaje — o simplemente un artista y una canción — y lo convierte en un viaje emocional narrado y multilingüe a través de música real. No solo crea una playlist: cuenta la historia humana detrás de cada canción, con la voz de un narrador de IA que de verdad leyó las letras.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Empieza desde cualquier cosa",
        text: "Un tema, un ambiente, una frase, o solo un artista y una canción. Sonder encuentra la música que encaja.",
      },
      {
        icon: "🗣️",
        title: "Un viaje narrado",
        text: "Una voz de IA cuenta la historia emocional detrás de cada canción, como un locutor de radio que leyó entre líneas.",
      },
      {
        icon: "🌍",
        title: "Multilingüe por diseño",
        text: "Explora en 9 idiomas — la narración, las traducciones de las letras y toda la interfaz siguen tu elección.",
      },
      {
        icon: "🗺️",
        title: "Un mapa de orígenes",
        text: "Descubre de dónde viene cada artista, situado en un mapa del mundo interactivo.",
      },
      {
        icon: "🎧",
        title: "Canciones reales y conocidas",
        text: "Las canciones se filtran por cifras de streaming reales: descubre música que de verdad dejó huella.",
      },
      {
        icon: "▶️",
        title: "Escucha y guarda",
        text: "Reproduce las canciones completas con tu Spotify y guarda todo el viaje como playlist.",
      },
    ],
    techKicker: "Bajo el capó",
    techHeading: "Cómo funciona",
    techLead:
      "Detrás de una sola petición, Sonder encadena un puñado de servicios especializados. Todo se degrada con elegancia — la aplicación arranca y funciona incluso sin ninguna clave de API, recurriendo a un modo demo que te dice qué variable configurar.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Búsqueda temática de letras y canciones — obtiene letras y traducciones.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Biografías, imágenes, metadatos e identificadores externos de los artistas, usados para mapear sus orígenes.",
      },
      {
        name: "Motor de pensamiento (LLM)",
        text: "Un modelo compatible con OpenAI convierte tu tema en consultas multilingües equilibradas, escribe la narración y deduce el ambiente y la geografía.",
      },
      {
        name: "ElevenLabs",
        text: "La síntesis de voz convierte la narración en una voz de IA natural.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Inicio de sesión por usuario para la reproducción completa y la creación de playlists con un clic.",
      },
    ],
    stackHeading: "Construido con",
    archNote:
      "Un front-end de React (Vite) se comunica con un back-end de FastAPI que reutiliza los clientes de servicios en Python; en producción, FastAPI también sirve la single-page app compilada. El Studio es una experiencia interactiva autónoma renderizada en un marco aislado.",
    soonTag: "Previsto",
    songstatsNote:
      "Songstats — estadísticas de streaming reales por ISRC, para conservar solo las canciones realmente notables — está previsto pero de momento no disponible.",
    madeBy: "Creado por",
    role: "Creador y desarrollador de Sonder",
  },
  de: {
    kicker: "Über das Projekt",
    tagline:
      "die Erkenntnis, dass jeder Mensch eine innere Welt in sich trägt, die so lebendig und komplex ist wie deine eigene.",
    ideaHeading: "Die Idee",
    ideaLead:
      "Sonder nimmt ein Thema, ein Gefühl, eine Botschaft — oder einfach einen Künstler und einen Song — und verwandelt es in eine erzählte, mehrsprachige emotionale Reise durch echte Musik. Es erstellt nicht nur eine Playlist: Es erzählt die menschliche Geschichte hinter jedem Track, mit der Stimme eines KI-Erzählers, der die Texte wirklich gelesen hat.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Beginne mit allem",
        text: "Ein Thema, eine Stimmung, ein Satz oder einfach ein Künstler und ein Song. Sonder findet die passende Musik.",
      },
      {
        icon: "🗣️",
        title: "Eine erzählte Reise",
        text: "Eine KI-Stimme erzählt die emotionale Geschichte hinter jedem Track, wie ein Radiomoderator, der zwischen den Zeilen gelesen hat.",
      },
      {
        icon: "🌍",
        title: "Mehrsprachig von Grund auf",
        text: "Erkunde in 9 Sprachen — Erzählung, Textübersetzungen und die gesamte Oberfläche folgen deiner Wahl.",
      },
      {
        icon: "🗺️",
        title: "Eine Karte der Herkunft",
        text: "Sieh, woher jeder Künstler kommt, eingezeichnet auf einer interaktiven Weltkarte.",
      },
      {
        icon: "🎧",
        title: "Echte, bekannte Songs",
        text: "Tracks werden nach echten Streaming-Zahlen gefiltert, damit du Musik entdeckst, die wirklich Anklang fand.",
      },
      {
        icon: "▶️",
        title: "Hören & behalten",
        text: "Spiele ganze Tracks über dein Spotify ab und speichere die ganze Reise als Playlist.",
      },
    ],
    techKicker: "Hinter den Kulissen",
    techHeading: "Wie es funktioniert",
    techLead:
      "Hinter einer einzigen Eingabe verkettet Sonder eine Handvoll spezialisierter Dienste. Alles degradiert sanft — die App startet und läuft sogar ganz ohne API-Schlüssel und fällt auf einen Demo-Modus zurück, der dir sagt, welche Variable du setzen musst.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Thematische Text- und Tracksuche — ruft Songtexte und Übersetzungen ab.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Künstlerbiografien, Bilder, Metadaten und externe IDs, genutzt, um ihre Herkunft zu kartieren.",
      },
      {
        name: "Denk-Engine (LLM)",
        text: "Ein OpenAI-kompatibles Modell verwandelt dein Thema in ausgewogene mehrsprachige Anfragen, schreibt die Erzählung und leitet Stimmung und Geografie ab.",
      },
      {
        name: "ElevenLabs",
        text: "Die Sprachsynthese macht aus der Erzählung eine natürliche KI-Stimme.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Anmeldung pro Nutzer für die vollständige Wiedergabe und die Playlist-Erstellung mit einem Klick.",
      },
    ],
    stackHeading: "Gebaut mit",
    archNote:
      "Ein React-Frontend (Vite) kommuniziert mit einem FastAPI-Backend, das die Python-Service-Clients wiederverwendet; in der Produktion liefert FastAPI auch die kompilierte Single-Page-App aus. Das Studio ist ein eigenständiges interaktives Erlebnis, das in einem isolierten Frame gerendert wird.",
    soonTag: "Geplant",
    songstatsNote:
      "Songstats — echte Streaming-Statistiken per ISRC, um nur wirklich bemerkenswerte Tracks zu behalten — ist geplant, aber derzeit nicht verfügbar.",
    madeBy: "Erstellt von",
    role: "Schöpfer und Entwickler von Sonder",
  },
  pt: {
    kicker: "Sobre o projeto",
    tagline:
      "a consciência de que cada pessoa carrega consigo um mundo interior tão vívido e complexo quanto o seu.",
    ideaHeading: "A ideia",
    ideaLead:
      "Sonder pega um tema, uma emoção, uma mensagem — ou simplesmente um artista e uma música — e transforma em uma jornada emocional narrada e multilíngue através de música real. Não cria apenas uma playlist: conta a história humana por trás de cada faixa, com a voz de um narrador de IA que realmente leu as letras.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "Comece de qualquer coisa",
        text: "Um tema, um clima, uma frase, ou só um artista e uma música. Sonder encontra a música que combina.",
      },
      {
        icon: "🗣️",
        title: "Uma jornada narrada",
        text: "Uma voz de IA conta a história emocional por trás de cada faixa, como um locutor de rádio que leu nas entrelinhas.",
      },
      {
        icon: "🌍",
        title: "Multilíngue por natureza",
        text: "Explore em 9 idiomas — a narração, as traduções das letras e toda a interface seguem a sua escolha.",
      },
      {
        icon: "🗺️",
        title: "Um mapa das origens",
        text: "Veja de onde vem cada artista, marcado em um mapa-múndi interativo.",
      },
      {
        icon: "🎧",
        title: "Músicas reais e conhecidas",
        text: "As faixas são filtradas por números reais de streaming: descubra música que de fato marcou.",
      },
      {
        icon: "▶️",
        title: "Ouça e guarde",
        text: "Toque as faixas completas pelo seu Spotify e salve toda a jornada como playlist.",
      },
    ],
    techKicker: "Por dentro",
    techHeading: "Como funciona",
    techLead:
      "Por trás de um único prompt, o Sonder encadeia um punhado de serviços especializados. Tudo degrada com elegância — o app inicia e funciona mesmo sem nenhuma chave de API, recorrendo a um modo demo que diz qual variável definir.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "Busca temática de letras e faixas — obtém letras e traduções.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "Biografias, imagens, metadados e IDs externos dos artistas, usados para mapear suas origens.",
      },
      {
        name: "Motor de pensamento (LLM)",
        text: "Um modelo compatível com OpenAI converte o seu tema em consultas multilíngues equilibradas, escreve a narração e deduz o clima e a geografia.",
      },
      {
        name: "ElevenLabs",
        text: "A síntese de voz transforma a narração em uma voz de IA natural.",
      },
      {
        name: "Spotify (PKCE)",
        text: "Login por usuário para reprodução completa e criação de playlist com um clique.",
      },
    ],
    stackHeading: "Construído com",
    archNote:
      "Um front-end React (Vite) conversa com um back-end FastAPI que reutiliza os clientes de serviço em Python; em produção, o FastAPI também serve a single-page app compilada. O Studio é uma experiência interativa autônoma renderizada em um frame isolado.",
    soonTag: "Previsto",
    songstatsNote:
      "Songstats — estatísticas reais de streaming por ISRC, para manter apenas as faixas realmente notáveis — está previsto, mas no momento indisponível.",
    madeBy: "Feito por",
    role: "Criador e desenvolvedor do Sonder",
  },
  ja: {
    kicker: "プロジェクトについて",
    tagline:
      "すべての人が、あなた自身と同じくらい鮮やかで複雑な内なる世界を抱えているという気づき。",
    ideaHeading: "アイデア",
    ideaLead:
      "Sonderは、テーマ、感情、メッセージ — あるいは単にアーティストと曲 — を受け取り、本物の音楽を通じた、ナレーション付きで多言語の感情の旅へと変えます。単にプレイリストを作るだけではありません。歌詞を実際に読み込んだAIナレーターの声で、それぞれの曲の背後にある人間の物語を語ります。",
    ideaPoints: [
      {
        icon: "🎯",
        title: "どんなものからでも始められる",
        text: "テーマ、ムード、ひとつのフレーズ、あるいはアーティストと曲だけでも。Sonderがぴったりの音楽を見つけます。",
      },
      {
        icon: "🗣️",
        title: "ナレーション付きの旅",
        text: "AIの声が、行間を読んだラジオのパーソナリティのように、それぞれの曲の背後にある感情の物語を語ります。",
      },
      {
        icon: "🌍",
        title: "もともと多言語対応",
        text: "9つの言語で楽しめます — ナレーション、歌詞の翻訳、インターフェース全体があなたの選択に従います。",
      },
      {
        icon: "🗺️",
        title: "出身地のマップ",
        text: "それぞれのアーティストの出身地を、インタラクティブな世界地図上で確認できます。",
      },
      {
        icon: "🎧",
        title: "本物の、よく知られた曲",
        text: "楽曲は実際のストリーミング数で絞り込まれるので、本当に響いた音楽に出会えます。",
      },
      {
        icon: "▶️",
        title: "聴いて、残す",
        text: "あなたのSpotifyでフルトラックを再生し、旅全体をプレイリストとして保存できます。",
      },
    ],
    techKicker: "舞台裏",
    techHeading: "仕組み",
    techLead:
      "ひとつのプロンプトの裏側で、Sonderはいくつかの専門サービスをつなぎ合わせます。すべてが優雅にフォールバックします — アプリはAPIキーがまったくなくても起動して動作し、どの変数を設定すればよいかを伝えるデモモードに切り替わります。",
    pipeline: [
      {
        name: "Musixmatch",
        text: "テーマに沿った歌詞と楽曲の検索 — 歌詞と翻訳を取得します。",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "アーティストの経歴、画像、メタデータ、外部ID。出身地のマッピングに使われます。",
      },
      {
        name: "思考エンジン（LLM）",
        text: "OpenAI互換のモデルが、あなたのテーマをバランスの取れた多言語クエリに振り分け、ナレーションを書き、ムードと地理を導き出します。",
      },
      {
        name: "ElevenLabs",
        text: "テキスト読み上げが、ナレーションを自然なAIの声に変えます。",
      },
      {
        name: "Spotify（PKCE）",
        text: "フル再生とワンクリックのプレイリスト作成のための、ユーザーごとのログイン。",
      },
    ],
    stackHeading: "使用技術",
    archNote:
      "React（Vite）のフロントエンドが、Pythonのサービスクライアントを再利用するFastAPIのバックエンドと通信します。本番環境では、FastAPIがビルドされたシングルページアプリも配信します。Studioは、隔離されたフレーム内でレンダリングされる、独立したインタラクティブな体験です。",
    soonTag: "予定",
    songstatsNote:
      "Songstats（ISRCごとの実際のストリーミング統計で、本当に注目すべき楽曲だけを残すための機能）は予定されていますが、現在は利用できません。",
    madeBy: "制作",
    role: "Sonderの考案者・開発者",
  },
  ko: {
    kicker: "프로젝트 소개",
    tagline:
      "모든 사람이 당신만큼이나 생생하고 복잡한 내면의 세계를 품고 있다는 깨달음.",
    ideaHeading: "아이디어",
    ideaLead:
      "Sonder는 주제, 감정, 메시지 — 또는 그저 아티스트와 곡 — 를 받아, 진짜 음악을 통한 내레이션이 있는 다국어 감정 여정으로 바꿉니다. 단순히 플레이리스트를 만드는 것이 아니라, 가사를 실제로 읽은 AI 내레이터의 목소리로 각 곡 뒤에 담긴 인간의 이야기를 들려줍니다.",
    ideaPoints: [
      {
        icon: "🎯",
        title: "무엇으로든 시작하세요",
        text: "주제, 분위기, 한 문장, 또는 아티스트와 곡만으로도. Sonder가 어울리는 음악을 찾아냅니다.",
      },
      {
        icon: "🗣️",
        title: "내레이션이 있는 여정",
        text: "AI 목소리가 행간을 읽은 라디오 진행자처럼 각 곡 뒤에 담긴 감정의 이야기를 들려줍니다.",
      },
      {
        icon: "🌍",
        title: "처음부터 다국어",
        text: "9개 언어로 탐험하세요 — 내레이션, 가사 번역, 그리고 전체 인터페이스가 당신의 선택을 따릅니다.",
      },
      {
        icon: "🗺️",
        title: "출신지 지도",
        text: "각 아티스트가 어디 출신인지 인터랙티브 세계 지도 위에서 확인하세요.",
      },
      {
        icon: "🎧",
        title: "진짜로 알려진 곡들",
        text: "곡은 실제 스트리밍 수치로 걸러지므로, 진정으로 공감을 얻은 음악을 발견하게 됩니다.",
      },
      {
        icon: "▶️",
        title: "듣고, 간직하세요",
        text: "당신의 Spotify로 곡 전체를 재생하고, 여정 전체를 플레이리스트로 저장하세요.",
      },
    ],
    techKicker: "내부 들여다보기",
    techHeading: "작동 방식",
    techLead:
      "하나의 프롬프트 뒤에서 Sonder는 몇 가지 전문 서비스를 연결합니다. 모든 것이 우아하게 대체됩니다 — 앱은 API 키가 전혀 없어도 시작되고 작동하며, 어떤 변수를 설정해야 하는지 알려주는 데모 모드로 전환됩니다.",
    pipeline: [
      {
        name: "Musixmatch",
        text: "주제별 가사 및 곡 검색 — 가사와 번역을 가져옵니다.",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "아티스트의 약력, 이미지, 메타데이터, 외부 ID. 출신지를 매핑하는 데 사용됩니다.",
      },
      {
        name: "사고 엔진 (LLM)",
        text: "OpenAI 호환 모델이 당신의 주제를 균형 잡힌 다국어 쿼리로 분배하고, 내레이션을 쓰고, 분위기와 지리를 도출합니다.",
      },
      {
        name: "ElevenLabs",
        text: "음성 합성이 내레이션을 자연스러운 AI 목소리로 바꿉니다.",
      },
      {
        name: "Spotify (PKCE)",
        text: "전체 재생과 원클릭 플레이리스트 생성을 위한 사용자별 로그인.",
      },
    ],
    stackHeading: "사용 기술",
    archNote:
      "React(Vite) 프론트엔드가 Python 서비스 클라이언트를 재사용하는 FastAPI 백엔드와 통신합니다. 프로덕션에서는 FastAPI가 빌드된 싱글 페이지 앱도 제공합니다. Studio는 격리된 프레임 안에서 렌더링되는 독립적인 인터랙티브 경험입니다.",
    soonTag: "예정",
    songstatsNote:
      "Songstats(ISRC 기반의 실제 스트리밍 통계로, 정말로 주목할 만한 곡만 남기는 기능)은 예정되어 있지만 현재는 사용할 수 없습니다.",
    madeBy: "제작",
    role: "Sonder의 기획자이자 개발자",
  },
  zh: {
    kicker: "关于项目",
    tagline:
      "意识到每个人都怀揣着一个与你自己同样鲜活而复杂的内心世界。",
    ideaHeading: "理念",
    ideaLead:
      "Sonder 接收一个主题、一种情感、一条讯息 — 或者只是一位艺术家和一首歌 — 然后将其转化为一段通过真实音乐展开的、带旁白的多语言情感旅程。它不只是生成一个播放列表：它用一位真正读过歌词的 AI 旁白者的声音，讲述每首歌背后的人性故事。",
    ideaPoints: [
      {
        icon: "🎯",
        title: "从任何东西开始",
        text: "一个主题、一种氛围、一句话，或者只是一位艺术家和一首歌。Sonder 会找到契合的音乐。",
      },
      {
        icon: "🗣️",
        title: "一段带旁白的旅程",
        text: "AI 的声音像一位读懂字里行间的电台主持人，讲述每首歌背后的情感故事。",
      },
      {
        icon: "🌍",
        title: "生而多语言",
        text: "用 9 种语言探索 — 旁白、歌词翻译和整个界面都随你的选择切换。",
      },
      {
        icon: "🗺️",
        title: "一张起源地图",
        text: "在交互式世界地图上看到每位艺术家来自何方。",
      },
      {
        icon: "🎧",
        title: "真实而知名的歌曲",
        text: "歌曲会按真实的播放量筛选，让你发现真正引起共鸣的音乐。",
      },
      {
        icon: "▶️",
        title: "聆听并珍藏",
        text: "通过你的 Spotify 播放完整歌曲，并把整段旅程保存为播放列表。",
      },
    ],
    techKicker: "幕后",
    techHeading: "工作原理",
    techLead:
      "在一个提示词的背后，Sonder 串联起一系列专门的服务。一切都会优雅降级 — 即使没有任何 API 密钥，应用也能启动并运行，回退到一个演示模式，告诉你需要设置哪个变量。",
    pipeline: [
      {
        name: "Musixmatch",
        text: "主题化的歌词与歌曲搜索 — 获取歌词和翻译。",
      },
      {
        name: "TheAudioDB · MusicBrainz",
        text: "艺术家的简介、图片、元数据和外部 ID，用于映射他们的起源。",
      },
      {
        name: "思考引擎（LLM）",
        text: "一个兼容 OpenAI 的模型把你的主题分配为均衡的多语言查询，撰写旁白，并推导出情绪与地理。",
      },
      {
        name: "ElevenLabs",
        text: "文本转语音把旁白变成自然的 AI 声音。",
      },
      {
        name: "Spotify (PKCE)",
        text: "按用户登录，实现完整播放和一键创建播放列表。",
      },
    ],
    stackHeading: "技术栈",
    archNote:
      "React（Vite）前端与一个复用 Python 服务客户端的 FastAPI 后端通信；在生产环境中，FastAPI 还会提供编译后的单页应用。Studio 是一段在隔离框架中渲染的、独立的交互式体验。",
    soonTag: "计划中",
    songstatsNote:
      "Songstats（按 ISRC 提供的真实播放统计，用于只保留真正知名的歌曲）已在计划中，但目前尚不可用。",
    madeBy: "制作者",
    role: "Sonder 的创造者与开发者",
  },
};

const STACK = [
  "React + Vite",
  "FastAPI",
  "OpenRouter / OpenAI",
  "ElevenLabs",
  "Spotify Web API",
  "Musixmatch",
  "MusicBrainz",
  "TheAudioDB",
];

// Possibili nomi/estensioni della foto autore in /static: si prova in ordine e,
// se nessuna esiste, si ripiega sul monogramma "RT". Basta rilasciare il file in
// static/ con uno di questi nomi perché la foto compaia automaticamente.
const PHOTO_CANDIDATES = [
  "/static/riccardo.jpg",
  "/static/riccardo.png",
  "/static/riccardo.jpeg",
  "/static/riccardo.webp",
];

export default function About({ onClose }) {
  const { code, t } = useT();
  const c = CONTENT[code] || CONTENT.en;
  const [photoIdx, setPhotoIdx] = useState(0);
  const photoSrc =
    photoIdx < PHOTO_CANDIDATES.length ? PHOTO_CANDIDATES[photoIdx] : null;

  // Chiudi con ESC + blocca lo scroll del body finché l'overlay è aperto, così
  // non scorre la pagina sottostante (Studio incluso) mentre leggi l'About.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="about-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="About Sonder"
    >
      <div className="about-backdrop" onClick={onClose} />
      <div className="about-panel">
        <button
          className="about-close"
          onClick={onClose}
          title={t("aboutClose")}
          aria-label={t("aboutClose")}
        >
          ✕
        </button>

        <header className="about-head">
          <div className="about-kicker">{c.kicker}</div>
          <h1 className="about-title">Sonder</h1>
          <p className="about-tagline">
            <em>sonder</em> — {c.tagline}
          </p>
        </header>

        {/* Parte 1: l'idea */}
        <section className="about-section">
          <h2 className="about-h2">{c.ideaHeading}</h2>
          <p className="about-lead">{c.ideaLead}</p>
          <div className="about-grid">
            {c.ideaPoints.map((p) => (
              <div className="about-feature" key={p.title}>
                <span className="about-feature-icon">{p.icon}</span>
                <div>
                  <div className="about-feature-title">{p.title}</div>
                  <div className="about-feature-text">{p.text}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <hr className="hr-glow" />

        {/* Parte 2: tecnica */}
        <section className="about-section">
          <div className="about-section-kicker">{c.techKicker}</div>
          <h2 className="about-h2">{c.techHeading}</h2>
          <p className="about-lead">{c.techLead}</p>

          <ol className="about-pipeline">
            {c.pipeline.map((step, i) => (
              <li className="about-step" key={step.name}>
                <span className="about-step-num">{i + 1}</span>
                <div>
                  <div className="about-step-name">{step.name}</div>
                  <div className="about-step-text">{step.text}</div>
                </div>
              </li>
            ))}
          </ol>

          <h3 className="about-h3">{c.stackHeading}</h3>
          <div className="about-stack">
            {STACK.map((s) => (
              <span className="pill about-pill" key={s}>
                {s}
              </span>
            ))}
          </div>
          <p className="about-arch">{c.archNote}</p>

          <p className="about-soon">
            <span className="about-soon-tag">{c.soonTag}</span>
            <span>{c.songstatsNote}</span>
          </p>
        </section>

        {/* Footer: autore */}
        <footer className="about-author">
          <div className="about-avatar">
            {photoSrc ? (
              <img
                src={photoSrc}
                alt="Riccardo Tocci"
                onError={() => setPhotoIdx((i) => i + 1)}
              />
            ) : (
              <span className="about-avatar-fallback">RT</span>
            )}
          </div>
          <div className="about-author-meta">
            <div className="about-author-label">{c.madeBy}</div>
            <div className="about-author-name">Riccardo Tocci</div>
            <div className="about-author-role">{c.role}</div>
          </div>
        </footer>
      </div>
    </div>
  );
}
