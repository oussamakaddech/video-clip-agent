# Style « GTA 6 » pour les extraits

Ajout local, en plus du rendu amont (`integrations/gtavi/scripts/cut.py`).
Code : `scripts/gta6_style.py` · commande : `python scripts/gta6.py style ...`

Le style ne change pas la sélection des moments : il change **ce que le
spectateur voit dans les 3 premières secondes** et la façon dont les sous-titres
tiennent l'attention. C'est là que se joue le scroll.

> Choisir une bonne source (et repérer les sous-titres déjà incrustés) :
> `docs/sources-gta6.md`.

## Anatomie d'un extrait

```
┌──────────────────────────┐
│        [ GTA 6 ]         │  pastille rose, 2,8 s
│   He walked into         │  accroche 2 lignes, blanc + contour noir
│   gator water            │  ombre rose, entrée en zoom 90 -> 100 %
│                          │
│        (vidéo)           │  saturation +10 %, contraste +5 %, vignettage
│                          │
│   WITH THE GATORS?       │  karaoké : mot actif rose, reste blanc
│                          │
│  [Follow for more GTA 6] │  CTA optionnel, 1,8 s de fin
└──────────────────────────┘
```

## Palette et styles ASS

| Élément | Couleur | Code ASS |
|---|---|---|
| Accroche | blanc | `&H00FFFFFF` |
| Mot actif / ombre / pastille | rose Vice City `#FF2E88` | `&H00882EFF` |
| Contour | noir | `&H00000000` |
| Texte de la pastille | encre `#0B0B0F` | `&H000F0B0B` |

- **Cap** : Arial Black 92, contour 7, ombre 3, mot actif rose. Le surlignage
  se fait par couleur (pas par mise à l'échelle) : une pop d'échelle faisait
  chevaucher les lettres voisines sur les mots larges.
- **Hook** : Arial Black 78, contour 10, ombre rose 5, entrée
  `\fscx90\fscy90` -> 100 % en 150 ms.
- **Kicker** : boîte pleine (BorderStyle 3) rose, texte encre, 40 px.
- **Cta** : boîte rose, texte blanc, 52 px, dernières 1,8 s.

## Trois cadrages

| Layout | Ce qu'on voit | Quand |
|---|---|---|
| `fill` | jeu plein cadre 9:16 (le centre du 16:9) | action centrée, pas de caméra |
| `blur` | 16:9 entier sur fond flou | plans larges, dialogue, caméra visible en petit |
| `facecam` | caméra du streamer en haut (1080×608), jeu en dessous | le visage doit être dans le clip |

```text
┌──────────────────────────┐
│   caméra du streamer     │  1080 x 608 (16:9), recadrée sur le visage
├──────────────────────────┤
│      [ GTA 6 ]           │  pastille, y = 690
│   He walked into         │  accroche, y = 830
│   gator water            │
│                          │
│        (jeu)             │  jeu 9:16, crop centre
│                          │
│   WITH THE GATORS?       │  karaoké, y = 1450
│  [Follow for more GTA 6] │  CTA, y = 1690
└──────────────────────────┘
```

- `--cam auto` : le visage est trouvé par la même détection OpenCV (YuNet) que
  l'upstream (`integrations/gtavi/scripts/facecam.py`), puis la boîte est
  élargie de 15 % et remontée pour garder bonnet/écouteurs/menton.
- `--cam x:y:w:h` (fractions) force la position : à utiliser quand le streamer
  bouge, ou quand la détection tombe sur un décor.
- L'aspect du panneau (1080/608 = 1,78) est celui d'une webcam 16:9 : la boîte
  détectée est donc reprise **sans recadrage vertical** (pas de tête coupée).

## Traitement d'image

```text
setsar=1, eq=saturation=1.10:contrast=1.05, vignette=PI/5,
fade=t=in:st=0:d=0.18, fps=30, subtitles='clip_N_gta6.ass'
```

Le fondu d'entrée de 0,18 s évite le démarrage « sec » sans faire flash
publicitaire. Pas de zoom animé : sur 40 s en 1080x1920 il double le temps de
rendu pour un gain visuel faible.

## Règles d'accroche

Tirées de `skills/hook-writer/SKILL.md`, appliquées à la lettre :

1. 3 à 9 mots, phrase affirmative, pas de « wait for it » ni de majuscules
   partout.
2. Elle doit être **tenue par le clip** : si l'accroche promet trois choses,
   les trois sont à l'écran.
3. Deux lignes de 22 caractères maximum (largeur lisible en Arial Black 78 sur
   1080 px). Au-delà, la fin est coupée et signalée par `…` — jamais en silence.
4. Pas d'accroche recyclée d'un clip à l'autre.

## Commandes

```powershell
# un extrait
.\.venv\Scripts\python.exe scripts\gta6.py style output\gta6\jobs\<id> --pick 3 `
    --hook "He walked into gator water" --cta "Follow for more GTA 6"

# variantes d'accroche pour A/B (la première est rendue, les autres listées)
.\.venv\Scripts\python.exe scripts\gta6.py style output\gta6\jobs\<id> --pick 3 `
    --hooks "He walked into gator water" "Gators don't show up on the map"

# recadrage plus court, autre habillage
.\.venv\Scripts\python.exe scripts\gta6.py style output\gta6\jobs\<id> --pick 4 `
    --start 500 --end 528 --layout blur --kicker "GTA 6"

# source qui porte déjà des sous-titres incrustés → on coupe le bas du cadre
.\.venv\Scripts\python.exe scripts\gta6.py style output\gta6\jobs\<id> --pick 2 `
    --hook "They got tigers in the game" --trim-bottom 0.17

# le visage du streamer en haut du cadre (détection automatique)
.\.venv\Scripts\python.exe scripts\gta6.py style output\gta6\jobs\<id> --pick 1 `
    --layout facecam --hook "He got 3 stars INSTANTLY"
```

Sortie : `jobs/<id>/edits/clip_<n>_gta6.mp4` + `.ass` + `.json` (le rendu
classique, `clip_<n>.mp4`, n'est pas écrasé : on garde l'avant/après).

## Pièges

- **Sous-titres déjà incrustés dans la source** : les rediffusions YouTube
  portent souvent leurs propres sous-titres en bas du cadre (auto-captions ou
  sous-titres du créateur). Ils se superposent aux nôtres. `--trim-bottom <f>`
  retire `f` de la hauteur source **avant** le cadrage.

  Le piège mesuré : `--trim-bottom` ne supprime pas seulement le bas, il
  **remonte tout le reste** dans le cadre final (86 % → 86 / (1 − f)). Un `0.08`
  censé couvrir les 8 % du bas a donc fait *descendre* les sous-critiques de la
  VOD Speed à 93 % au lieu de les couper. `0.08` ne suffit que si la bande de
  texte commence après 92 % de la hauteur.

  Méthode de mesure (30 s, fiable) :

  ```powershell
  # 1. une frame de la zone qui pose problème
  output\gta6\bin\ffmpeg.exe -v error -y -ss 1077 -i <source.mp4> -frames:v 1 shot.jpg
  # 2. lire le haut de la bande de texte en fraction de hauteur :
  #    bande à y ≈ 0.84..0.89  →  --trim-bottom 0.17   (1 - 0.83)
  ```

  Règle : `trim = 1 - (haut de la bande)`, arrondi au % supérieur. Conséquence
  assumée : le cadrage se resserre (une fenêtre 1920x900 recadrée en 9:16 ne
  garde que ~26 % de la largeur). Si le zoom est trop fort, préférer une autre
  source : les VOD **officielles** (chaîne du streamer) n'ont pas ces
  sous-titres, seuls les reuploads en ajoutent.
- **Parole qui se chevauche** (deux personnes, ou mots transcrits en double) :
  deux groupes de sous-titres au même point d'ancrage s'impriment l'un sur
  l'autre et les lettres s'entremêlent (`THAT'SGOINGTO`). Chaque groupe est donc
  borné au début du suivant — un seul groupe à l'écran, jamais deux.
- Une couleur ASS s'écrit `&HAABBGGRR&` avec l'esperluette finale : sans elle,
  `\c` n'est pas reconnu et les mots se collent.
- Une accroche trop longue est coupée : la fin est remplacée par `…`, jamais
  tronquée en silence.
- **Dialecte mal transcrit** (arabe tunisien, créole) : Whisper sort du bruit
  (« ايش ايش »). Mieux vaut `--captions none` qu'un sous-titre faux ; l'accroche,
  la pastille et le CTA suffisent à porter le clip.
- **Caméra du streamer** : `--cam auto` lance la détection YuNet sur les 40
  premières secondes. Si le streamer n'est pas à l'image (écran de chargement,
  menu), ou si le visage bouge beaucoup, fixer la boîte à la main avec
  `--cam x:y:w:h`. La boîte est en fractions de l'image **source** (16:9), pas du
  cadre 9:16 final.

## Coût

Même temps de rendu que le style amont (± 10 %) : ~60 s pour 40 s d'extrait en
1080x1920 sur ce poste. Aucune dépendance nouvelle.
