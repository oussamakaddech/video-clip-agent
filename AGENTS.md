# AGENTS.md — video-clip-agent

## Projet
Agent IA de **clipping vidéo** : à partir d'une vidéo longue + sa transcription,
il sélectionne les moments forts (LLM OpenAI Agents SDK), valide strictement les
bornes, puis rend des extraits **verticaux 9:16 sous-titrés** via FFmpeg.

Projet **autonome**, hors dépôt `pfe-d2f-enseignants`. Python 3.10+.

## Architecture (règles structurantes)
1. **Le LLM ne fait que proposer.** Toute validation (bornes, durées, doublons,
   recouvrement) vit dans `clipagent/selection.py` — logique **pure**, sans
   dépendance ni réseau, **obligatoirement couverte par des tests**.
2. **Outils `ffmpeg.py` = construction de commandes séparée de l'exécution**
   (`build_*` vs `render_*`) → commandes testables sans binaire externe.
3. **Import du SDK OpenAI différé** (`agents`, `imageio_ffmpeg`) : la suite de
   tests doit passer même sans ces dépendances (`pytest.importorskip`).
4. **Repli sans clé API** : `heuristic_proposals` (densité de mots + signaux
   d'accroche). Le pipeline ne doit jamais échouer à cause du LLM (warning
   + repli), jamais loses l'utilisateur.

## Commandes
```powershell
.\.venv\Scripts\python.exe -m pytest              # 39 tests
.\.venv\Scripts\python.exe -m clipagent plan  --transcript examples\demo.srt --output output
.\.venv\Scripts\python.exe -m clipagent run   --video examples\demo.mp4 --transcript examples\demo.srt --output output
.\.venv\Scripts\python.exe -m clipagent info  --video examples\demo.mp4
```

## Environnement
- venv local `.venv` (Python 3.13 système : `C:\Users\oussama\AppData\Local\Programs\Python\Python313\python.exe`).
- `ffmpeg` **non installé en système** : le projet retombe sur `imageio-ffmpeg`
  (binaire embarqué, **avec libass** → filtre `subtitles` disponible).
- Aucune clé `OPENAI_API_KEY` sur cette machine → le chemin LLM n'a été validé
  que **structurellement** (construction de l'agent + invocation des outils via
  `ToolContext`), jamais contre l'API réelle.

## Pièges
- Console Windows en cp1252 → `main()` force l'UTF-8 (`reconfigure`).
- Les bornes de phrases : `snap_to_sentence_boundaries` décale de max 3 s.
- Un segment est inclus dans une fenêtre s'il **chevauche** l'intervalle
  (bornes exclusives).
- Le recouvrement entre extraits est mesuré sur l'extrait **le plus court**
  (`overlap_ratio`), seuil 0,35.
