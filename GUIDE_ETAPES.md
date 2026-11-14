# Guide étape par étape — clipagent

Objectif : transformer **une vidéo + sa transcription** en **extraits verticaux sous-titrés**.

Trois parcours :
- **parcours navigateur** (le plus simple, aucune VOD téléchargée) ;
- **parcours livestream** (VOD longue déjà à l'avance) ;
- **parcours classique** (fichier vidéo local).

---

## 🥇 Parcours navigateur — sans télécharger la VOD (recommandé)

La VOD est analysée **directement dans Edge/Chrome** : le projet y lit le lecteur,
balaye la vidéo, capture seulement les fenêtres utiles, transcribe l'audio
**en local** et rend les clips. Rien de plusieurs Go n'est téléchargé.

```powershell
cd $HOME\Desktop\video-clip-agent
.\.venv\Scripts\Activate.ps1

clipagent browse --url "https://kick.com/<pseudo>/videos/<id>" --output output_kick
```

Options utiles :

| Option | Défaut | Rôle |
|---|---|---|
| `--step` | 60 | pas du storyboard (1 image analyse toutes les N s) |
| `--candidates` | 8 | nombre de fenêtres candidates à capturer |
| `--window` | 35 | durée d'une fenêtre candidate (s) |
| `--num-clips` | 6 | nombre d'extraits finaux |
| `--whisper` | tiny | modèle Whisper local (`base` = plus juste, 3× plus lent) |
| `--language` | auto | langue de la VOD (`en`, `fr`, `ar`…) |
| `--channel` | msedge | `msedge`, `chrome`, `chromium`, `auto` |
| `--headed` | off | afficher le navigateur (débogage) |
| `--style` | default | style visuel (`tiktok`, `arabic`…) |

### Face cam (visage du streamer en bas)

Le style `tiktok` active le **face cam** : le visage du streamer est détecté
(OpenCV YuNet) dans la source et superposé **en bas** du clip vertical, dans un
cercle, sur un fond flouté. Sans visage détecté, le clip est rendu normalement.

Pour l'activer sur un autre style, ou le désactiver :

```powershell
clipagent browse --url "…" --style tiktok          # face cam activé
clipagent browse --url "…" --style reels            # sans face cam
```

### Ce que ça fait, étape par étape

1. **Storyboard** : une image JPEG par `--step` secondes, prélevée dans le
   lecteur ; le *mouvement* est mesuré dans la page (canvas).
2. **Chat replay** : lu dans le DOM (horodatages vidéo) → signal sémantique.
3. **Classement** : score composite (55 % mouvement + 45 % chat) → `--candidates`
   fenêtres bien espacées sur toute la durée.
4. **Capture** : chaque fenêtre candidate est capturée en audio+vidéo à faible
   débit (≈ 10 Mo / 80 s), puis transcrite **en local** par Whisper.
5. **Choix** : l'agent LLM lit ces transcriptions (et l'activité du chat) et
   retient les meilleurs extraits (titre + hook TikTok).
6. **Validation** : bornes recalées sur les phrases, début ancré sur une phrase
   accrocheuse, recouvrement et doublons de sujets écartés.
7. **Rendu** : seule la fenêtre de chaque extrait retenu est capturée en
   audio+vidéo, puis ffmpeg la transforme en **1080×1920 sous-titré**, avec
   accroche et face cam.

### Re-sélectionner sans re-capturer (30 s)

```powershell
clipagent plan --transcript output\candidates.srt --output output --num-clips 6
clipagent finalize --plan output\clips_plan.json --fragments output\work --output output --style tiktok
```

`candidates.srt` contient le transcript des fenêtres retenues et `output\work`
les fragments capturés : la sélection et le rendu peuvent être refaits sans
toucher au réseau.

### Ce qu'il faut savoir

* **Edge ou Chrome est obligatoire** : le Chromium de Playwright n'a pas les
  codecs H.264 (Kick sert en HLS/H.264) → la lecture échouerait.
* **Durée** : le storyboard coûte ~2,5 s par image ; chaque capture se fait en
  temps réel (on ne peut pas accélérer la lecture). Pour une VOD de 3 h :
  ~15 à 25 min pour 6 extraits.
* **Qualité** : les clips sont à la résolution servie par le lecteur
  (souvent 640×360 sur Kick) → le recadrage vertical upscale. Pour une qualité
  maximale, utilisez le **parcours livestream** (yt-dlp, 1080p) ou forcez la
  qualité dans le lecteur.
* **Coût réseau** : quelques dizaines de Mo au total, au lieu de plusieurs Go.

---

## Parcours livestream (Kick) — VOD longue, téléchargement partiel

```powershell
cd $HOME\Desktop\video-clip-agent
.\.venv\Scripts\Activate.ps1

# 1. Télécharger la VOD ( Kick, YouTube, Twitch… )
clipagent fetch --url "https://kick.com/xxxx/videos/123456" --out downloads
#    → affiche le chemin du fichier téléchargé

# 1 bis. Connexion faible : audio seul (≈ 100 Mo pour 4 h)
clipagent fetch --url "https://kick.com/xxxx/videos/123456" --out downloads --audio-only

# 1 ter. Connexion faible : uniquement les fragments utiles
clipagent fetch --url "https://kick.com/xxxx/videos/123456" --out downloads --sections "120-180,900-940"

# 2. Transcrire (Whisper local : rien ne sort de la machine)
clipagent transcribe --video .\downloads\<fichier>.mp4 --output .\vod.srt --model small --language fr

# 3. Choisir les extraits (profil livestream : 12 extraits, 25–90 s)
clipagent plan --video .\downloads\<fichier>.mp4 --transcript .\vod.srt --output output --profile livestream

# 4. Rendre (1080×1920, sous-titres incrustés)
clipagent render --plan output\clips_plan.json --video .\downloads\<fichier>.mp4 --transcript .\vod.srt --output output
```

### Points spécifiques au livestream

| Sujet | Réponse |
|---|---|
| **Durée** | une VOD de 4 h n'entre pas dans un seul prompt : le transcript est **découpé en portions** (12 000 caractères) et chaque portion est analysée par l'agent, puis les propositions sont fusionnées et dédoublonnées. `--max-chunks` limite le nombre de portions analysées (12 par défaut). |
| **Coût LLM** | 1 appel par portion. Pour une VOD de 4 h, comptez ~15 à 25 portions → `--max-chunks 8` pour un premier passage rapide. |
| **Transcription** | `small` sur CPU : ~1× le temps réel (4 h de VOD ≈ 2 à 4 h de calcul). Astuce : `--model base` pour aller 3× plus vite, `medium` si l'audio est bruité. |
| **VOD sans audio** | les enregistrements d'écran sont muets → message explicite, pas de crash. |
| **VOD protégés** | `--cookies-from-browser chrome` pour les streams réservés (le compte doit être connecté dans le navigateur). |
| **Choix des moments** | le profil `livestream` demande à l'agent de cibler les pics (réaction, annonce, chiffre, moment drôle, question du chat) et d'ignorer les phases vides. |
| **Durée des clips** | 25–90 s (format short). Pour des « extraits » de 2–3 min : `--max-clip 180 --min-clip 60`. |

### Variante tout-en-un (mode navigateur)

```powershell
clipagent browse --url "https://kick.com/…/videos/…" --output output --style tiktok --whisper base
```

---

## Parcours livestream (Kick) — VOD longue, téléchargement partiel

---

## Parcours court (vidéo de quelques minutes)

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

### Choisir le style et l'accroche

```powershell
# format TikTok : accroche en haut + zoom + sous-titres gras
clipagent render --plan output\clips_plan.json --video .\v.mp4 --transcript .\v.srt --style tiktok

# sans accroche, plus sobre
clipagent render --plan output\clips_plan.json --video .\v.mp4 --transcript .\v.srt --style podcast

# accroche plus longue (5 s)
clipagent render --plan output\clips_plan.json --video .\v.mp4 --transcript .\v.srt --style tiktok --hook-duration 5
```

Styles disponibles : `default`, `tiktok`, `hype`, `podcast`, `clean`, `reels`, `arabic`.

### Contenu arabe

```powershell
clipagent transcribe --video .\arabe.mp4 --output .\arabe.srt --model small --language ar
clipagent plan --transcript .\arabe.srt --language ar --output output          # style arabe auto
clipagent render --plan output\clips_plan.json --video .\arabe.mp4 --transcript .\arabe.srt --output output
```

Le prompt, les titres et l'accroche passent en arabe ; le rendu RTL est correct
(libass : lettres liées, ordre droite-à-gauche, ponctuation `؟`).

> Si vous avez déjà fait l'étape 3 avant de choisir le style, relancez-la :
> le style et le hook s'appliquent **au rendu**, pas à l'analyse.

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
