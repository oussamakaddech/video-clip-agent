# Shorts scriptés — reproduire le format « Viceprint »

Le short `youtube.com/shorts/uz-Iq7nCfnA` (*Get STRONGER FAST in GTA 6! (Secret
Workout)*, chaîne **Viceprint**) sert de référence de format. Ce document décrit
ce qu'il est, ce qui a été repris, et comment en produire d'autres avec nos
propres images.

## 1. Ce qu'est le short de référence

| Mesure | Valeur |
|---|---|
| Identifiant | `uz-Iq7nCfnA` |
| Chaîne | Viceprint |
| Durée | 57,2 s |
| Format | 1080 × 1920, 30 fps, VP9 + Opus |
| Publication | 20/11/2026 |
| Vues / likes | 11,87 M / 220 k |

Ce n'est **pas un extrait de VOD** : c'est un montage scripté.

- **Voix off continue**, du premier au dernier mot, sans respiration longue.
- **Un texte plein cadre par phrase**, en blanc, contour noir épais, qui résume
  la phrase plutôt qu'il ne la transcrit.
- **Plans de 1 à 3 s** de gameplay (le montage est plus rapide que la parole),
  aucun face cam du streamer.
- **Aucun silence** : la voix porte le rythme, la musique/le jeu reste en fond.
- **CTA explicite** dans les 3 dernières secondes (« Share this with your
  friends… »).

Le script suit une boucle de guide : promesse (0–3 s) → étapes numérotées
(3–45 s) → révélation (« and the best part? ») → astuce finale → CTA. La
transcription complète est dans `output/gta6/shorts/reference/`.

## 2. Ce que nous reproduisons

`scripts/gta6_short.py` construit le même objet à partir de nos sources GTA 6 :
une **spec JSON** décrit des *beats*, chaque beat = un plan + une phrase.

```json
{
  "credit": "@IShowSpeed",
  "cta": "Follow for more GTA 6",
  "voice": "Microsoft David Desktop",
  "rate": 1,
  "layout": "fill",
  "beats": [
    {
      "source": "C:\\…\\output\\gta6\\sources\\speed-finale-4h30.mp4",
      "start": 1117,
      "end": 1123.5,
      "text": "This is the final mission of GTA 6.",
      "label": "THE LAST MISSION"
    }
  ]
}
```

- `text` : la phrase prononcée par la voix off.
- `label` : le texte affiché (facultatif ; à défaut, la phrase elle-même).
  Tenir en 3 lignes de 22 caractères.
- `start` / `end` : fenêtre dans la source (secondes absolues du fichier).

### Principe : la voix commande le montage

Chaque phrase est d'abord **synthétisée** (`scripts/tts.ps1`, System.Speech,
100 % hors ligne), puis sa durée réelle devient celle du plan (+ 0,22 s de
respiration). Conséquences :

- impossible de désynchroniser texte et image : le timeline est calculé **après**
  la synthèse ;
- si la fenêtre source est plus courte que la phrase, le plan est **allongé dans
  la même source** (on ne fige pas l'image) ;
- si elle est plus longue, le plan est **coupé** : c'est la voix qui décide.

### Rendu

Un seul passage ffmpeg : N entrées (`-ss`/`-t` par plan), concaténation vidéo,
concaténation audio, voix mixée sur le jeu à −16 dB, `loudnorm` à −14 LUFS,
ASS incrusté par libass, H.264 CRF 19.

```powershell
.\.venv\Scripts\python.exe scripts\gta6_short.py `
  --spec output\gta6\shorts\final-mission-v2.json `
  --out  output\gta6\shorts\final-mission-v2.mp4 `
  --work output\gta6\shorts\_work_v2
```

`--work` garde les WAV de synthèse, la piste voix et le `.ass` : indispensable
pour retoucher une phrase sans tout refaire.

## 3. Choix de mise en page

- **Position du texte** : `LINE_Y = 470` (zone haute, au-dessus de l'interface
  TikTok/Reels). Le premier beat est en 96 px, les suivants en 88 px.
- **Crédit** : `CREDIT_Y = 262`, volontairement **sous** le logo du streamer
  présent dans l'image source — sinon les deux se superposent.
- **CTA** : `CTA_Y = 1640`, posé 0,6 s avant le dernier beat.
- **Cadrage** : `fill` (9:16 plein) pour l'action centrée ; `blur` pour les plans
  larges où le plein format couperait les personnages.

## 4. Pièges

- **`Set-Content -Encoding UTF8` écrit un BOM** : la spec est lue en
  `utf-8-sig`.
- **Les sources contiennent de la nudité** (PNJ de GTA 6) : vérifier chaque
  fenêtre à la frame avant de la garder. Sur la VOD Speed, `1171–1178` montre un
  PNJ nu — écarté au profit de `1164–1171`.
- **La voix `Microsoft David Desktop` est robotique.** Elle passe pour un
  montage « guide », mais pour un rendu plus naturel il faudra une vraie voix
  (enregistrement ou TTS neural hors ligne) : la spec n'a pas à changer.
- **`label` trop long** : le texte est tronqué à 3 lignes ; garder ≤ 66
  caractères utiles.
- Le script exige des **chemins absolus** dans la spec (ffmpeg est lancé avec un
  autre répertoire de travail).

## 5. Tests

`tests/test_gta6_short.py` couvre la logique pure : durée des plans, extension
de fenêtre, continuité du timeline, ASS (un événement par plan, crédit, CTA,
échappement, retour à la ligne), commande ffmpeg (entrées, concat, mixage,
`loudnorm`, échappement du chemin ASS). Aucun binaire, aucune synthèse vocale.
