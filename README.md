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

## 2. Utilisation

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

## 3d. Face cam — le visage du streamer en bas du clip

Sur les lives, le streamer apparaît souvent dans un coin de l'image. Pour un
format vertical, ce visage est **redétecté** (OpenCV YuNet) puis **superposé
en bas**, dans un cercle. L'écran est **divisé** :

```
┌──────────────────────┐
│  accroche TikTok     │  ← 3 premières secondes
│  contenu (16:9) net  │  ← 2/3 du haut
│                      │
│  sous-titres         │
├──────────────────────┤
│  fond flouté         │
│         ( ◕ )        │  ← 1/3 du bas : visage du streamer
└──────────────────────┘
```

* activé par le style `tiktok` (désactivé pour `default`, `clean`, `podcast`) ;
* si aucun visage n'est trouvé, le clip est rendu normalement (avec un
  avertissement dans le rapport) ;
* position et taille réglables : `bottom-center` / `bottom-left` / `bottom-right`,
  taille 320 px par défaut.

## 4. Comment l'agent décide

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
