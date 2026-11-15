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
4. **Repli sans clé API** : `heuristic_proposals`. Le pipeline ne doit jamais
   échouer à cause du LLM (warning + repli), jamais perdre l'utilisateur.
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
| `ffmpeg.py` | commandes de rendu (coupe, face cam, ASS, netteté) | ~560 |
| `facecam.py` | détection du visage (OpenCV YuNet, mobilité) | ~260 |
| `pipeline.py` | pipeline local (plan → rendu → rapport) | ~430 |
| `llm.py` | agent OpenAI Agents SDK + outils | ~470 |
| `styles.py` | styles visuels (tiktok, streamer, arabic…) | ~280 |
| `hooks.py` | accroche TikTok (nettoyage, découpage) | ~125 |
| `subtitles.py` | génération ASS (2 styles, 2 référentiels de temps) | ~150 |
| `model_picker.py` | **sélection automatique du modèle** (sonde + classement) | ~260 |
| `service.py` | couche de service (CLI + API), comparaison de styles | ~430 |

## Commandes
```powershell
.\.venv\Scripts\python.exe -m pytest                      # 120 tests
.\.venv\Scripts\python.exe -m clipagent doctor            # diagnostic env
.\.venv\Scripts\python.exe -m clipagent browse --url <vOD> --style tiktok
.\.venv\Scripts\python.exe -m clipagent finalize --plan output\clips_plan.json --fragments output\work
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
