# Guide étape par étape — clipagent

Objectif : transformer **une vidéo + sa transcription** en **5 extraits verticaux sous-titrés**.

Durée totale : ~5 minutes de mise en route, puis 1 commande par étape.

---

## Étape 0 — Environnement (déjà fait sur cette machine ✔)

```powershell
cd $HOME\Desktop\video-clip-agent
.\.venv\Scripts\Activate.ps1
```

Vérification rapide :

```powershell
.\.venv\Scripts\python.exe -m pytest        # doit afficher : 39 passed
```

> `ffmpeg` n'est pas installé en système : le projet utilise automatiquement le
> binaire embarqué `imageio-ffmpeg` (avec `libass` → sous-titres OK).

---

## Étape 1 — Préparer la transcription

**Si vous avez déjà un `.srt` / `.vtt`** → passez directement à l'étape 2.

**Sinon**, transcrivez automatiquement (Whisper local, la vidéo ne sort pas de la machine) :

```powershell
clipagent transcribe --video "C:\chemin\ma-video.mp4" --output .\ma-video.srt --model small
```

| Modèle | Taille | Vitesse | Recommandé pour |
|---|---|---|---|
| `base` | ~150 Mo | très rapide | essai / français clair |
| `small` | ~480 Mo | rapide | **usage normal** |
| `medium` | ~1,5 Go | lent | français bruité, noms techniques |

> Le modèle est téléchargé une seule fois (cache HuggingFace) puis fonctionne hors-ligne.

**Contrôle** : le fichier `.srt` doit contenir des blocs horodatés.

---

## Étape 2 — Demander les extraits (sans rendre)

```powershell
clipagent plan --video "C:\chemin\ma-video.mp4" --transcript .\ma-video.srt --output output
```

Affiche les extraits retenus + écrit `output\clips_plan.json` et `output\clips_plan.md`.

**C'est l'étape de contrôle humaine** : ouvrez `output\clips_plan.md`, lisez les
titres et les justifications, et ajustez `clips_plan.json` à la main si besoin
(bornes `start` / `end`, `title`, ordre).

Options utiles :

```powershell
--num-clips 5          # nombre d'extraits
--min-clip 20 --max-clip 60   # durée d'un extrait (secondes)
--aspect 9:16         # 9:16 (réseaux sociaux) | 16:9 | 1:1
--instruction "cible les passages sur l'architecture"   # consigne libre pour l'agent
```

---

## Étape 3 — Rendre la vidéo

```powershell
clipagent render --plan output\clips_plan.json --video "C:\chemin\ma-video.mp4" --transcript .\ma-video.srt --output output
```

Produit dans `output\` :

| Fichier | Contenu |
|---|---|
| `<video>_01_<titre>.mp4` | extrait **1080×1920** sous-titré |
| `<video>_01.jpg` | vignette de couverture |
| `<video>_best_of.mp4` | tous les extraits concaténés |

> Si vous avez modifié `clips_plan.json`, c'est **cet extrait-là** qui est rendu :
> on peut corriger les bornes sans rejouer l'analyse.

---

## Étape 4 — Contrôle qualité (2 minutes)

Pour chaque extrait :

1. **Le début est propre ?** pas de phrase coupée, pas de « euh » ;
2. **La fin est propre ?** la phrase se termine ;
3. **Le sens est complet ?** on comprend sans le reste de la vidéo ;
4. **Les sous-titres sont lisibles ?** (blanc + contour noir) ;
5. **Le format est vertical ?** 1080×1920.

Un extrait qui échoue au point 1 ou 2 → on recale `start` / `end` dans
`clips_plan.json` (à la seconde) et on relance l'étape 3.

---

## Étape 5 — Exploitation

* **Publication** : `output\*.mp4` (extraits) + `output\*.jpg` (vignettes).
* **Newsletter / récapitulatif** : `output\<video>_best_of.mp4`.
* **Relecture rapide** : `output\clips_plan.md` (tableau + justification).

---

## Variante « tout-en-un »

Si vous n'avez pas besoin de contrôler le plan :

```powershell
clipagent run --video "C:\chemin\ma-video.mp4" --transcript .\ma-video.srt --output output
```

---

## Dépannage express

| Symptôme | Cause / solution |
|---|---|
| `Aucune clé OPENAI_API_KEY` | mode heuristique : mettez `OPENAI_API_KEY` dans `.env` pour l'agent LLM |
| `ffmpeg introuvable` | `pip install imageio-ffmpeg` (déjà fait ici) ou `winget install Gyan.FFmpeg` |
| `Erreur ffmpeg : ... subtitles` | le binaire ffmpeg n'a pas `libass` → utilisez le build officiel ou `--no-subtitles` |
| Aucun extrait proposé | transcription vide/incorrecte → vérifiez le `.srt` ; baissez `--min-clip` |
| Extraits qui se ressemblent | le recouvrement est mesuré sur l'extrait le plus court (seuil 0,35) : les doublons sont écartés automatiquement ; sinon ajustez le plan à la main |
| Sortie en français bizarre | `chcp 65001` dans PowerShell (la console Windows force cp1252) |
