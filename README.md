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
| `--no-subtitles` | off | désactive l'incrustation des sous-titres |
| `--ffmpeg` | auto | chemin explicite de ffmpeg |

## 3. Sorties (`output/`)

| Fichier | Contenu |
|---|---|
| `clips_plan.json` | plan machine-readable (bornes, titres, scores, chemins) |
| `clips_plan.md` | rapport lisible, tableau + justification de chaque extrait |
| `<video>_01_<titre>.mp4` | extrait vertical (1080×1920), sous-titré |
| `<video>_01.jpg` | vignette de couverture |
| `<video>_best_of.mp4` | concaténation de tous les extraits |

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
