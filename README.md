# clipagent — Agent IA de clipping vidéo

Projet autonome : un agent IA qui **transforme une vidéo longue en extraits
courts verticaux**, sous-titrés, prêts à publier.

Pipeline : **transcription → agent (LLM) → validation stricte → rendu FFmpeg → rapport**.

```
video.mp4 + transcript.srt
        │
        ├─ 1. Transcript      (SRT/VTT parsing, fenêtrage, recalage sur les phrases)
        ├─ 2. Agent OpenAI    (outils : read_transcript / propose_clip / finish_selection)
        ├─ 3. Validation      (bornes, durées, doublons, recouvrement — logique pure)
        ├─ 4. Rendu FFmpeg    (coupe + recadrage 9:16 + sous-titres + vignette)
        └─ 5. Rapport         (clips_plan.json / clips_plan.md + best-of.mp4)
```

---

## 1. Installation

Prérequis : **Python 3.10+** et **FFmpeg**.

```powershell
cd $HOME\Desktop\video-clip-agent

# Environnement virtuel
& "C:\Users\oussama\AppData\Local\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1

# Dépendances
pip install -e ".[dev]"
```

FFmpeg (Windows) :

```powershell
winget install Gyan.FFmpeg        # puis rouvrir le terminal
```

ou, sans installation système : `pip install imageio-ffmpeg` (le projet le
détecte automatiquement).

Clé API (optionnelle — sans elle, le projet fonctionne en mode heuristique) :

```powershell
Copy-Item .env.example .env
# puis renseigner OPENAI_API_KEY=sk-...
```

## 2. Interface web + API

```powershell
pip install -e ".[web]"
clipagent-server                     # http://127.0.0.1:8765
```

L'interface permet de **lancer un clipping depuis le navigateur** : source
(URL / fichier / transcription), style, langue, nombre et durée des extraits,
consigne libre — puis de **suivre l'avancement en direct** (journal, barre de
progression) et de **prévisualiser/télécharger** chaque extrait ainsi que la
vidéo best-of.

### API HTTP

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/api/health` | état du service (ffmpeg, Whisper, OpenCV, IA, disque) |
| `GET` | `/api/styles` | catalogue des styles et des profils |
| `POST` | `/api/jobs` | crée une tâche → `{id}` |
| `GET` | `/api/jobs` | liste des tâches |
| `GET` | `/api/jobs/{id}` | état détaillé (progression, journal, extraits) |
| `DELETE` | `/api/jobs/{id}` | annule / supprime une tâche |
| `GET` | `/api/jobs/{id}/events` | suivi en direct (Server-Sent Events) |
| `GET` | `/api/jobs/{id}/clips/{n}` | télécharge un extrait (MP4) |
| `GET` | `/api/jobs/{id}/best-of` | télécharge la vidéo best-of |
| `GET` | `/api/jobs/{id}/report` | rapport Markdown |
| `GET` | `/api/jobs/{id}/usage` | taille des artefacts sur disque |
| `POST` | `/api/upload` | téléverse une vidéo / transcription |

Exemple :

```bash
curl -X POST http://127.0.0.1:8765/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"url":"https://kick.com/…/videos/…","style":"streamer","num_clips":6,"render":true}'
```

Chaque tâche tourne dans un **thread** dédié : l'API reste responsive, et le
progrès est poussé en direct vers l'interface.

## 2b. Utilisation en ligne de commande

### 🥇 Mode navigateur — analyser une VOD **sans la télécharger**

```powershell
clipagent browse --url "https://kick.com/<pseudo>/videos/<id>" --output output_kick
```

Le projet ouvre la VOD dans **Edge/Chrome**, la balaie, capture uniquement les
fenêtres utiles, transcribe l'audio en local et rend les clips verticaux.
Aucun téléchargement de la VOD complète (plusieurs Go) : quelques dizaines de Mo.

```
storyboard (1 image / 60 s, mouvement mesuré dans la page)
   → pics de mouvement → fenêtres candidates
   → capture AUDIO seule (≈ 250 Ko / 30 s) → transcription Whisper locale
   → l'agent LLM choisit les extraits (titre + hook)
   → capture AUDIO+VIDÉO des seuls extraits retenus
   → ffmpeg : 1080×1920 + sous-titres + hook
```

> **Edge ou Chrome obligatoire** : le Chromium de Playwright n'a pas les codecs
> H.264 (Kick sert en HLS/H.264). Le projet tente `msedge`, puis `chrome`.

### Parcours livestream (Kick / VOD longue)

```powershell
# 1. Télécharger la VOD
clipagent fetch --url "https://kick.com/xxx/videos/123456" --out downloads

# 2. Transcrire en local (Whisper)
clipagent transcribe --video .\downloads\vod.mp4 --output .\vod.srt --model small --language fr

# 3. Sélectionner les moments forts (12 extraits par défaut)
clipagent plan --video .\downloads\vod.mp4 --transcript .\vod.srt --output output --profile livestream

# 4. Rendre les extraits verticaux
clipagent render --plan output\clips_plan.json --video .\downloads\vod.mp4 --transcript .\vod.srt --output output
```

> **VOD de plusieurs heures** : la transcription est découpée en portions
> (12 000 caractères) analysées une par une par l'agent, puis les propositions
> sont fusionnées, dédoublonnées et triées. `--max-chunks` borne le nombre de
> portions analysées (12 par défaut) pour maîtriser le nombre d'appels LLM.

### Parcours classique

```powershell
# a) Analyser une vidéo + transcription (sans rendre)
clipagent plan --video .\ma-video.mp4 --transcript .\ma-video.srt --output output

# b) Analyse + rendu complet
clipagent run --video .\ma-video.mp4 --transcript .\ma-video.srt --output output

# c) Rendre un plan déjà validé (relance, correction manuelle du JSON)
clipagent render --plan output\clips_plan.json --video .\ma-video.mp4 --output output

# d) Transcrire automatiquement (Whisper local, optionnel)
pip install faster-whisper
clipagent transcribe --video .\ma-video.mp4 --output .\ma-video.srt --model small

# e) Métadonnées d'une vidéo
clipagent info --video .\ma-video.mp4
```

Options principales :

| Option | Défaut | Rôle |
|---|---|---|
| `--num-clips` | 5 | nombre d'extraits |
| `--min-clip` / `--max-clip` | 20 s / 90 s | durée d'un extrait |
| `--aspect` | `9:16` | format de sortie (`9:16`, `16:9`, `1:1`) |
| `--model` | `gpt-4o-mini` | modèle LLM (tout modèle compatible OpenAI) |
| `--instruction` | — | consigne libre (« cible les passages techniques »…) |
| `--profile` | `default` | préréglage : `livestream` (12 extraits), `podcast`, `short` |
| `--no-subtitles` | off | désactive l'incrustation des sous-titres |
| `--ffmpeg` | auto | chemin explicite de ffmpeg |

### Profils

| Profil | Extraits | Durée min–max | Usage |
|---|---|---|---|
| `default` | 5 | 20–90 s | usage général |
| `short` | 3 | 15–45 s | TikTok / Reels |
| `podcast` | 6 | 30–120 s | extraits plus longs |
| `livestream` | 12 | 25–90 s | VOD de live (beaucoup de pics) |

## 3. Sorties (`output/`)

| Fichier | Contenu |
|---|---|
| `clips_plan.json` | plan machine-readable (bornes, titres, scores, chemins) |
| `clips_plan.md` | rapport lisible, tableau + justification de chaque extrait |
| `<video>_01_<titre>.mp4` | extrait vertical (1080×1920), sous-titré |
| `<video>_01.jpg` | vignette de couverture |
| `<video>_best_of.mp4` | concaténation de tous les extraits |

## 3b. Utiliser une autre IA (NVIDIA, Ollama, vLLM…)

Tout endpoint compatible OpenAI fonctionne. Le projet bascule tout seul sur
l'API **Chat Completions** quand une `base_url` est fournie (l'API `/responses`
d'OpenAI n'existe pas chez ces fournisseurs).

```powershell
# NVIDIA NIM (clé nvapi-… depuis https://build.nvidia.com)
clipagent plan --video .\ma-video.mp4 --transcript .\ma-video.srt `
  --base-url https://integrate.api.nvidia.com/v1 `
  --model meta/llama-3.1-70b-instruct `
  --api-key nvapi-XXXXXXXX `
  --non-strict-tools
```

Equivalents :

| Fournisseur | `--base-url` | modèle conseillé |
|---|---|---|
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `meta/llama-3.1-70b-instruct`, `qwen/qwen2.5-coder-32b-instruct` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:14b`, `llama3.1:8b` |
| vLLM (local) | `http://localhost:8000/v1` | nom du modèle servi |
| Together / Groq | `https://api.together.xyz/v1`, `https://api.groq.com/openai/v1` | `meta-llama/…`, `llama-3.3-70b-versatile` |

> `--non-strict-tools` : certains endpoints refusent le schéma JSON strict des
> outils. En cas d'erreur « tool schema », ajoutez cette option.
> Variables d'environnement équivalentes : `CLIPAGENT_BASE_URL`,
> `CLIPAGENT_MODEL`, `CLIPAGENT_CHAT_COMPLETIONS`, `CLIPAGENT_STRICT_TOOLS`.

## 3c. Styles visuels, hook TikTok et arabe

### Styles

```powershell
clipagent render --plan output\clips_plan.json --video .\ma-video.mp4 --transcript .\ma-video.srt --style tiktok
```

| Style | Hook | Zoom | Sous-titres | Usage |
|---|---|---|---|---|
| `default` | oui | non | blancs, 48 px | usage général |
| `tiktok` | oui, en haut | 1,08 | gras, 60 px | format short |
| `hype` | oui, centré, jaune | 1,12 | capitales | moments forts |
| `podcast` | non | 1,03 | discrets, 46 px | extrait sobre |
| `clean` | non | non | fins, 42 px | minimal |
| `reels` | oui, en haut | 1,05 | gras, 54 px | Reels / Shorts |
| `arabic` | oui, en haut | non | gras, RTL, 54 px | contenu arabe |

Chaque style contrôle : le recadrage, le zoom progressif, la police, la taille,
la couleur, le contour, la position et le fond des sous-titres **et** de
l'accroche. Tout est défini dans `clipagent/styles.py` (un seul endroit à
modifier pour en ajouter un).

### Hook TikTok

L'agent rédige pour chaque extrait une **accroche de 4 à 9 mots**, affichée
pendant les 3 premières secondes en gros en haut de l'image :

```
  LA RÉPONSE TIENT EN
  UNE PHRASE
```

* le hook vient de l'agent (outil `propose_clip`, champ `hook`) ;
* à défaut, il est déduit de la première phrase de l'extrait ;
* `--no-hook` le désactive, `--hook-duration 4` change sa durée ;
* la police s'auto-cale pour ne jamais déborder de la largeur.

### Arabe (RTL)

```powershell
clipagent transcribe --video .\arabe.mp4 --output .\arabe.srt --model small --language ar
clipagent plan --transcript .\arabe.srt --language ar --style arabic --output output
clipagent render --plan output\clips_plan.json --video .\arabe.mp4 --transcript .\arabe.srt --style arabic
```

* le prompt passe en arabe (`title`, `reason`, `hook` en arabe) ;
* le style `arabic` est choisi automatiquement pour une langue RTL
  (`ar`, `fa`, `he`, `ur`) ;
* le rendu passe par **libass** : la mise en forme des lettres (shaping) et
  l'ordre droite-à-gauche sont corrects, ponctuation arabe comprise (`؟`).

## 3d. Face cam — format « streamer » (contenu + caméra)

Format de référence : le contenu occupe le haut, la **caméra du streamer en
plein cadre** occupe le bas. Le visage est **redétecté** (OpenCV YuNet) dans
la source, la région caméra est isolée puis redimensionnée sur la bande basse.

```
┌──────────────────────┐
│  accroche TikTok     │  ← 3 premières secondes
│  contenu (16:9)      │  ← 56 % du haut (couvre la zone)
│  sous-titres         │
├──────────────────────┤
│  caméra du streamer  │  ← 44 % du bas, plein cadre
│  (plein cadre)       │
└──────────────────────┘
```

* style `streamer` : exactement ce layout (56 / 44) ;
* style `tiktok` : même layout + accroche plus affirmée ;
* styles `podcast` / `clean` : pas de face cam ;
* `--no-subtitles` : rend la vidéo **sans** sous-titres (comme la référence) ;
* `--logo logo.png` : badge image posé en haut à gauche (comme la référence).

### Détection fiable de la webcam

Un stream contient souvent d'autres visages (illustrations d'un site, photos).
Le projet retient la face **la plus persistante ET la plus mobile** : une vraie
webcam bouge entre deux images, une illustration reste figée.

```powershell
clipagent finalize --plan output\clips_plan.json --fragments output\work --style streamer --no-subtitles
```

## 3e. Réglages de qualité (actifs par défaut)

| Réglage | Valeur | Pourquoi |
|---|---|---|
| `unsharp=5:5:0.6` | après l'agrandissement | une source 360p/480p montée en 1080×1920 est molle : l'accentuation rend le texte lisible |
| `eq=contrast=1.06:brightness=0.012:saturation=1.08` | léger | les écrans de stream sont ternes |
| `libx264 -crf 18 -preset slow -profile:v high` | CRF 18 | CRF 21 → 18 : ~30 % de détails en plus (fichier ~1,5× plus gros) |
| `-r 30` | constant | évite les à-coups de cadence |
| `aac 192k / 48 kHz` | audio | voix plus nette |
| Whisper `small` | sous-titres | `--whisper small` : bien plus fiable que `tiny` |

```powershell
# rendu haute qualité
clipagent finalize --plan output\clips_plan.json --fragments output\work --style streamer --whisper small
```

## 4. Comment l'agent décide (le « niveau de clipping »)

```
VOD 3 h
  │
  ├─ 1. storyboard      1 image JPEG / 60 s, mouvement mesuré dans la page
  │                    + chat replay lu dans le DOM (signal sémantique gratuit)
  ├─ 2. classement     score composite = 55 % mouvement + 45 % activité du chat
  │                    → 8 fenêtres candidates, espacées sur toute la durée
  ├─ 3. capture        audio+vidéo des seules fenêtres retenues (≈ 10 Mo / 80 s)
  │                    → transcription Whisper 100 % locale
  ├─ 4. agent LLM      lit les transcriptions + l'activité du chat
  │                    → titre, raison, score et hook TikTok par extrait
  └─ 5. validation     (code pur, jamais le LLM)
                       · bornes recalées sur les fins de phrases
                       · durée forcée dans [min, max]
                       · début ancré sur une phrase « accrocheuse »
                       · recouvrement < 35 % entre extraits
                       · titres trop proches écartés (diversité des sujets)
```

### Les 5 leviers de qualité

| Levier | Effet |
|---|---|
| **Ancrage hook** | le début du clip est déplacé vers la première phrase vraiment « accrocheuse » (question, chiffre, annonce) — sinon on perd les 2 premières secondes |
| **Diversité** | deux extraits qui racontent la même chose (titres trop proches) sont écartés |
| **Chat replay** | une vague de messages signale un moment fort ; le chat est aussi fourni à l'IA comme contexte |
| **Fenêtres espacées** | les candidats couvrent toute la durée du live, pas seulement le début |
| **Score composite** | le classement combine image **et** communauté, pas seulement le mouvement |

### Re-sélectionner sans rien re-capturer

Le transcript des fenêtres retenues est sauvegardé (`candidates.srt`) : on peut
rejouer la sélection avec d'autres consignes, puis re-rendre **depuis les
fragments déjà capturés** (30 s au lieu de 25 min) :

```powershell
clipagent plan --transcript output\candidates.srt --output output --num-clips 6
clipagent finalize --plan output\clips_plan.json --fragments output\work --output output --style tiktok
```

L'agent (OpenAI Agents SDK) ne fait que **proposer** des extraits via l'outil
`propose_clip`. Toute la validation est assurée par `clipagent/selection.py`,
en logique pure et testée :

* bornes recalées sur les fins de phrases de la transcription ;
* durée forcée dans `[min_clip, max_clip]` ;
* suppression des propositions qui se recouvrent fortement (IoU ≥ 0,55) ;
* tri par score, puis sélection du nombre demandé.

Ce découplage garantit qu'une réponse d'IA fantaisiste ne peut pas produire un
clip incohérent.

**Mode heuristique** (sans clé API) : score de chaque segment (densité de
mots + signaux d'accroche : « la clé », « tout le monde », « première fois »…)
puis assemblage des meilleurs segments consécutifs.

## 5. Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

La suite couvre le parsing SRT/VTT, la validation des clips, la construction
des commandes FFmpeg et l'orchestration du pipeline (aucun appel réseau, aucun
binaire externe requis).

## 6. Structure

```
clipagent/
├── config.py      # réglages (env + CLI)
├── models.py      # Segment / ClipProposal / Clip
├── transcript.py  # lecture SRT/VTT, fenêtrage, export
├── selection.py   # validation pure (bornes, durées, doublons, heuristique)
├── llm.py         # agent OpenAI Agents SDK + outils
├── ffmpeg.py      # sonde, coupe, recadrage, sous-titres, concat
├── pipeline.py    # orchestration + rapport
└── cli.py         # interface en ligne de commande
```

## 7. Pièges connus

* **Sans ffmpeg** : l'analyse fonctionne, seul le rendu échoue (message explicite).
* **Sous-titres** : incrustés via le filtre `subtitles` de FFmpeg (nécessite
  `libass`, présent dans les builds FFmpeg officiels).
* **Découpe à la frame près** : le rendu recode (`libx264`) ; le mode rapide
  `--fast` n'est pas exposé en CLI car il coupe sur la keyframe suivante.
* **Modèles locaux** : le SDK Agents accepte d'autres fournisseurs via
  `LiteLLM` (`--model openai/...`, `--model anthropic/...` avec les variables
  d'environnement correspondantes).
