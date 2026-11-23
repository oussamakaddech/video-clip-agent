# AGENTS.md — video-clip-agent

## Projet
Agent IA de **clipping vidéo** : à partir d'une VOD longue (Kick, YouTube…) et de
sa transcription, il sélectionne les moments forts, puis rend des extraits
**verticaux 9:16 sous-titrés**, avec accroche TikTok et **face cam** (visage du
streamer détecté et superposé en bas).

Projet **autonome**, hors dépôt `pfe-d2f-enseignants`. Python 3.10+.

## Deux modes de collecte
| Mode | Commande | Réseau | Usage |
|---|---|---|---|
| **Navigateur** (recommandé) | `clipagent browse --url <vOD>` | quelques dizaines de Mo | VOD de plusieurs heures, connexion faible |
| Fichier local | `clipagent run --video v.mp4 --transcript v.srt` | local | vidéo courte |

Le mode navigateur lit la VOD **dans Edge/Chrome** (Playwright) : storyboard
(1 image / N s), captures ciblées, transcription Whisper **en local**. La VOD
complète n'est jamais téléchargée.

> Edge ou Chrome est **obligatoire** : le Chromium de Playwright n'a pas les
> codecs H.264 (Kick sert en HLS/H.264).

## Architecture (règles structurantes)
1. **Le LLM ne fait que proposer.** Toute validation (bornes, durées, doublons,
   recouvrement, ancrage hook, diversité) vit dans `clipagent/selection.py` —
   logique **pure**, sans dépendance ni réseau, **couverte par des tests**.
2. **Outils `ffmpeg.py` = construction de commandes séparée de l'exécution**
   (`build_*` vs `render_*`) → testables sans binaire externe.
3. **Import du SDK OpenAI différé** (`agents`, `imageio_ffmpeg`, `faster_whisper`,
   `cv2`) : la suite de tests doit passer même sans ces dépendances.
4. **Repli sans clé API** : `narrative_proposals` (puis `heuristic_proposals`
   si la transcription est trop courte). Le pipeline ne doit jamais échouer à
   cause du LLM (warning + repli), jamais perdre l'utilisateur.
5. **Deux référentiels de temps** dans l'ASS : `absolute=True` (source complète,
   seek de sortie) et `absolute=False` (fragment téléchargé, temps relatifs au
   fragment). Ne jamais mélanger.
6. **Les webm de MediaRecorder** déclarent une résolution d'en-tête parfois
   fausse (284x160 pour des frames 1280x720) : **normaliser la taille avant
   tout `crop`**, sinon ffmpeg refuse.

## Modules
| Fichier | Rôle | Lignes |
|---|---|---|
| `cli.py` | parseur d'arguments + dispatch | ~180 |
| `commands.py` | implémentation des 9 commandes | ~430 |
| `service.py` | **couche de service** (CLI + API), avec callbacks de progression | ~330 |
| `api/server.py` | API FastAPI (jobs, SSE, téléchargements) + interface web | ~290 |
| `api/jobs.py` | file de tâches (threads, concurrence bornée, annulation) | ~170 |
| `api/schemas.py` | modèles de requête/réponse (validation pydantic) | ~70 |
| `web/` | interface web (HTML/CSS/JS vanilla, sans dépendance) | 3 fichiers |
| `browser.py` | pilotage Chromium (storyboard, capture, retries) | ~420 |
| `browser_pipeline.py` | orchestration du mode navigateur | ~480 |
| `scoring.py` | classement des fenêtres (mouvement + chat) | ~140 |
| `chat.py` | chat replay Kick (extraction, densité, contexte) | ~190 |
| `selection.py` | **validation pure** des extraits | ~430 |
| `narrative.py` | **découpage narratif** TextTiling (d'après ClipsAI) | ~380 |
| `ffmpeg.py` | commandes de rendu (coupe, face cam, ASS, netteté) | ~560 |
| `facecam.py` | détection du visage (OpenCV YuNet, mobilité) | ~260 |
| `pipeline.py` | pipeline local (plan → rendu → rapport) | ~430 |
| `llm.py` | agent OpenAI Agents SDK + outils | ~470 |
| `styles.py` | styles visuels (tiktok, streamer, arabic…) | ~280 |
| `hooks.py` | accroche TikTok (nettoyage, découpage) | ~125 |
| `subtitles.py` | génération ASS (2 styles, 2 référentiels de temps) | ~150 |
| `model_picker.py` | **sélection automatique du modèle** (sonde + classement) | ~260 |
| `service.py` | couche de service (CLI + API), comparaison de styles | ~430 |

## Intégration GTA 6 (`integrations/gtavi/`)
Copie datée du plugin MIT **gtavi-claudecode** (commit `dd95d39`) : 14 scripts
(découverte, scoring de moments, rendu 1080x1920, face cam, contrôle avant
publication) + 16 fiches `SKILL.md` qui sont des **consignes d'agent**, pas du
code. Analyse complète : `docs/gtavi-claudecode-analyse.md`.

- Toujours passer par le pont `scripts/gta6.py` : il met `ffmpeg` dans le `PATH`
  (`output/gta6/bin`) et fixe `CLIP_DESK_HOME` (`output/gta6`). Lancer un script
  amont directement échoue.
- Deux fonctions seulement sont patchées dans `common.py` (`tool`, `ffprobe`) ;
  le pont `scripts/compat.py` fournit `ffprobe` via PyAV (absent du poste).
- `scripts/gta6.py run` ajoute : accroches heuristiques (sans LLM), légendes avec
  crédit, rapport `report.md`/`report.json`. Rien n'est publié automatiquement.
- Trouver une source (chaînes vérifiées, fenêtre à télécharger, contrôle des
  sous-titres incrustés) : `docs/sources-gta6.md` + `scripts/yt_search.py`,
  `scripts/yt_window.py`, `scripts/audio_energy.py`.
- Trois cadrages : `fill` (jeu plein cadre), `blur` (16:9 sur fond flou) et
  `facecam` (caméra du streamer en haut 1080x608, jeu dessous). La boîte caméra
  vient de la détection YuNet de l'upstream (`--cam auto`) ou de `--cam x:y:w:h`.

## Intégration ClipsAI (`integrations/clipsai/`)
Copie datée du dépôt MIT **clipsai** (commit `8e73c8a`, v0.2.1) : référence
seulement, **le code amont ne tourne pas ici** (`whisperx` + `torch` +
`sentence-transformers` + `pyannote` ≈ 3 Go, jeton Hugging Face). Analyse :
`docs/clipsai-analyse.md`.

- Ce qui est repris est **l'algorithme** : `clipagent/narrative.py` réimplémente
  le TextTiling (frontières de sujet) et la fusion hiérarchique de `ClipFinder`
  sur des vecteurs lexicaux, sans aucune dépendance.
- Deux écarts assumés : la **pause** entre deux phrases entre dans le score de
  cohésion (des vecteurs lexicaux disjoints donnent sinon 0 partout, donc
  aucune frontière), et une **cascade de seuils** (`high` → `average` → `low`)
  évite de fusionner toute la vidéo en un seul extrait.
- Sélection : `--selection auto|llm|narrative|heuristic` (`CLIPAGENT_SELECTION`).
  `auto` = LLM si clé API, sinon narratif, sinon heuristique.

## Shorts scriptés (`scripts/gta6_short.py`)
Le short de référence `youtube.com/shorts/uz-Iq7nCfnA` (Viceprint, 57 s, 11,8 M
de vues) n'est **pas un extrait de VOD** : c'est un montage scripté — voix off
continue, plans de 1 à 3 s, un texte plein cadre par phrase, CTA final. Reproduit
par `scripts/gta6_short.py` (spec JSON) + `scripts/tts.ps1` (System.Speech, hors
ligne). Analyse et mode d'emploi : `docs/gta6-shorts.md`.

- **La voix commande le montage** : chaque phrase est synthétisée d'abord, sa
  durée réelle devient celle du plan (+ 0,22 s). Le texte et l'image ne peuvent
  pas se désynchroniser.
- `plan_shots` / `build_ass` / `build_command` sont purs et testés
  (`tests/test_gta6_short.py`) : aucun binaire, aucune synthèse en test.
- Le crédit est placé **sous** le logo du streamer (y=262), sinon les deux se
  superposent.

## Commandes
```powershell
.\.venv\Scripts\python.exe -m pytest                      # 222 tests
.\.venv\Scripts\python.exe -m clipagent doctor            # diagnostic env
.\.venv\Scripts\python.exe -m clipagent plan --transcript v.srt --selection narrative --min-clip 25 --max-clip 60
.\.venv\Scripts\python.exe -m clipagent browse --url <vOD> --style tiktok
.\.venv\Scripts\python.exe -m clipagent finalize --plan output\clips_plan.json --fragments output\work
.\.venv\Scripts\python.exe scripts\gta6.py setup           # ffmpeg/yt-dlp/whisper + espace de travail
.\.venv\Scripts\python.exe scripts\gta6.py trends --hours 24
.\.venv\Scripts\python.exe scripts\gta6.py run "<url>" --clips 3 --max-minutes 25 --layout fill
.\.venv\Scripts\python.exe scripts\gta6.py style output\gta6\jobs\<id> --pick 3 --hook "He walked into gator water" --cta "Follow for more GTA 6"
.\.venv\Scripts\python.exe scripts\gta6_short.py --spec output\gta6\shorts\<spec>.json --out output\gta6\shorts\<nom>.mp4
```

## Environnement
- venv local `.venv` (Python 3.13 système : `C:\Users\oussama\AppData\Local\Programs\Python\Python313\python.exe`).
- `ffmpeg` absent du système → repli automatique sur `imageio-ffmpeg`
  (binaire embarqué **avec libass** → filtre `subtitles` disponible).
- `playwright==1.49.1` (épinglé : correspond au Chromium 1148 déjà présent).
- OpenCV 5 : plus de cascades Haar → **YuNet** (`data/face_detection_yunet_2023mar.onnx`, 232 Ko).
- `av<16` requis par faster-whisper (PyAV 19 casse `metadata_errors`).
- CUDA absent sur ce poste → repli CPU automatique (détection `cublas`).

## Pièges déjà payés
- `run_sync()` de l'API Agents refuse une boucle asyncio active (Playwright) →
  l'appel LLM est déporté dans un thread (`llm._run_agent_sync`).
- Le tracing du SDK vise l'API OpenAI → `OPENAI_AGENTS_DISABLE_TRACING=1` avec un
  endpoint tiers.
- Les modèles « raisonneurs » (Nemotron) **consomment tous les tokens en
  réflexion** avant d'appeler un outil : budget ≤ 300 tokens ⇒ faux négatif.
  Sondage : `max_tokens=1024` + `enable_thinking: false` (NVIDIA).
- Les webm n'ont pas de durée lisible (`Duration: N/A`) → échantillonner le
  début du fragment, ne pas lire la durée.
- Une frame d'extraction périmée fausse la détection de visage → supprimer le
  fichier **avant** extraction.
- Les avertissements d'un plan JSON ne doivent pas être rejoués au run suivant.
- `Set-Content -Encoding UTF8` (PowerShell) écrit un BOM → lire en `utf-8-sig`.
- Les fichiers `/static` doivent être servis **sans cache** (le navigateur
  garde une version périmée du front).
- Les tâches vivent **en mémoire** : un redémarrage du serveur les perd.
- `imageio-ffmpeg` ne fournit **que ffmpeg** (pas ffprobe), et yt-dlp exige un
  exécutable nommé `ffmpeg.exe` dans le `PATH` (sinon il refuse
  `--download-sections` et le muxing) → le pont `scripts/gta6.py` crée
  `output/gta6/bin/ffmpeg.exe` (lien dur) et fournit `ffprobe` via PyAV.
- Les scripts amont de `integrations/gtavi/` appellent `sys.exit()` au premier
  échec : les lancer en **sous-processus**, sinon une erreur réseau tue
  l'orchestrateur au milieu du pipeline.
- La parole se chevauche parfois dans une transcription : deux groupes de
  sous-titres au même point d'ancrage s'impriment l'un sur l'autre
  (`THAT'SGOINGTO`) → borner chaque groupe au début du suivant
  (`scripts/gta6_style.py`).
- Les rediffusions YouTube portent souvent leurs **propres sous-titres incrustés**
  en bas du cadre : `--trim-bottom` (style GTA 6) les retire avant le cadrage,
  sinon ils se superposent aux nôtres. Attention, trimer **remonte** le reste du
  cadre : `trim = 1 - (haut de la bande de texte)`. Sur la VOD Speed (bande à
  84 %), `0.08` ne suffisait pas — il faut `0.17`. Les VOD **officielles** n'ont
  pas ce problème : préférer la chaîne du streamer aux reuploads.
