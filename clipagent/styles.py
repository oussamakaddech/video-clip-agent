"""Styles visuels des extraits (sous-titres, recadrage, zoom, hook).

Un style regroupe tout ce qui donne son identité visuelle à un clip :
la police et le rendu des sous-titres, le recadrage, un zoom éventuel et
la mise en page de l'accroche (« hook »).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _ass_color(rgba: str) -> str:
    """Convertit ``#RRGGBB[AA]`` (opacité FF = opaque) en couleur ASS ``&HAABBGGRR``.

    En ASS, l'alpha est inversé : ``00`` = opaque, ``FF`` = invisible.
    """
    value = rgba.lstrip("#")
    if len(value) == 6:
        r, g, b, a = value[0:2], value[2:4], value[4:6], "FF"
    elif len(value) == 8:
        r, g, b, a = value[0:2], value[2:4], value[4:6], value[6:8]
    else:
        r, g, b, a = "FF", "FF", "FF", "FF"
    alpha = f"{255 - int(a, 16):02X}"
    return f"&H{alpha}{b}{g}{r}".upper()


@dataclass(frozen=True)
class SubtitleStyle:
    """Rendu d'un bloc de texte (sous-titres ou accroche).

    Les tailles sont exprimées en pixels du script ASS (PlayResY = 1920) :
    48 ≈ sous-titre standard, 84 ≈ accroche TikTok.
    """

    font: str = "Arial"
    size: int = 48
    primary: str = "#FFFFFF"
    outline: str = "#000000"
    back: str = "#80000000"
    outline_width: int = 3
    shadow: int = 1
    bold: bool = False
    uppercase: bool = False
    alignment: int = 2          # 1 bas-gauche 2 bas-centre 5 milieu-centre 8 haut-centre
    margin_v: int = 90
    margin_h: int = 60
    border_style: int = 1       # 1 = contour, 3 = boîte opaque
    scale_x: int = 100
    scale_y: int = 100
    spacing: int = 0
    rtl: bool = False

    def to_ass_style(self, name: str) -> str:
        """Ligne ``Style:`` au format ASS."""
        bold = -1 if self.bold else 0
        return (
            f"Style: {name},{self.font},{self.size},{_ass_color(self.primary)},"
            f"{_ass_color(self.primary)},{_ass_color(self.outline)},{_ass_color(self.back)},"
            f"{bold},0,0,0,{self.scale_x},{self.scale_y},{self.spacing},0,"
            f"{self.border_style},{self.outline_width},{self.shadow},{self.alignment},"
            f"{self.margin_h},{self.margin_h},{self.margin_v},1"
        )


@dataclass(frozen=True)
class ClipStyle:
    """Identité visuelle complète d'un extrait."""

    name: str
    label: str
    description: str
    crop: str = "center"                 # center | top | fill
    zoom: float = 1.0                    # > 1 : zoom progressif (effet Ken Burns)
    background: str = "#000000"          # fond quand la source ne remplit pas le format
    subtitle: SubtitleStyle = field(default_factory=SubtitleStyle)
    hook_enabled: bool = True
    hook_duration: float = 3.0
    hook_style: SubtitleStyle = field(
        default_factory=lambda: SubtitleStyle(
            size=72,
            bold=True,
            border_style=3,
            alignment=8,
            margin_v=240,
            primary="#FFFFFF",
            back="#B3000000",
            outline_width=0,
            shadow=0,
        )
    )
    hook_uppercase: bool = True
    hook_max_chars: int = 52
    language_hint: str = ""
    # --- Face cam (visage du streamer superposé en bas) -------------------
    facecam_enabled: bool = False
    facecam_size: int = 320
    facecam_position: str = "bottom-center"   # bottom-center | bottom-left | bottom-right
    facecam_shape: str = "circle"             # circle | square
    facecam_margin: int = 140
    facecam_layout: str = "split"             # split | cam-bottom | blurred
    facecam_top_ratio: float = 0.67           # part de l'écran réservée au contenu
    facecam_region: float = 0.8               # élargissement de la zone caméra

    def is_rtl(self) -> bool:
        return self.subtitle.rtl or self.hook_style.rtl


def _style(name: str, label: str, description: str, **kwargs) -> ClipStyle:
    return ClipStyle(name=name, label=label, description=description, **kwargs)


# --- Catalogue ------------------------------------------------------------
STYLES: dict[str, ClipStyle] = {
    "default": _style(
        "default",
        "Par défaut",
        "Sous-titres blancs centrés en bas, pas de zoom.",
    ),
    "tiktok": _style(
        "tiktok",
        "TikTok",
        "Hook en gros en haut, zoom progressif, sous-titres gras : format short.",
        crop="center",
        zoom=1.08,
        subtitle=SubtitleStyle(size=60, bold=True, outline_width=6, margin_v=180),
        hook_enabled=True,
        hook_duration=3.0,
        hook_style=SubtitleStyle(
            size=88, bold=True, border_style=3, alignment=8, margin_v=280,
            primary="#FFFFFF", back="#CC000000", outline_width=0, shadow=0,
        ),
        hook_max_chars=42,
        facecam_enabled=True,
        facecam_size=560,
        facecam_layout="cam-bottom",
        facecam_top_ratio=0.56,
        facecam_region=1.0,
        facecam_margin=40,
    ),
    "hype": _style(
        "hype",
        "Hype",
        "Hook centré très visible, zoom rapide, sous-titres en capitales.",
        zoom=1.12,
        subtitle=SubtitleStyle(size=54, bold=True, uppercase=True, outline_width=6),
        hook_duration=2.5,
        hook_style=SubtitleStyle(
            size=96, bold=True, uppercase=True, border_style=3, alignment=5,
            primary="#FFE600", back="#CC000000", outline_width=0, shadow=0,
        ),
        hook_max_chars=40,
    ),
    "podcast": _style(
        "podcast",
        "Podcast",
        "Sobre : pas de hook, sous-titres discrets, léger zoom.",
        zoom=1.03,
        hook_enabled=False,
        subtitle=SubtitleStyle(size=46, outline_width=4, margin_v=160),
    ),
    "clean": _style(
        "clean",
        "Clean",
        "Minimal : sous-titres fins, aucun effet, aucun hook.",
        zoom=1.0,
        hook_enabled=False,
        subtitle=SubtitleStyle(size=42, outline_width=3, margin_v=140),
    ),
    "reels": _style(
        "reels",
        "Reels / Shorts",
        "Hook en haut, sous-titres compacts, format carré-vertical.",
        zoom=1.05,
        subtitle=SubtitleStyle(size=54, bold=True, margin_v=190),
        hook_duration=2.8,
        hook_style=SubtitleStyle(
            size=82, bold=True, border_style=3, alignment=8, margin_v=260,
            primary="#FFFFFF", back="#B3000000", outline_width=0, shadow=0,
        ),
    ),
    "streamer": _style(
        "streamer",
        "Streamer (caméra plein cadre)",
        "Layout de référence : contenu sur 56 % du haut, caméra du streamer "
        "en plein cadre sur 44 % du bas, sans cercle.",
        zoom=1.0,
        subtitle=SubtitleStyle(size=46, bold=True, outline_width=5, margin_v=90),
        hook_enabled=True,
        hook_duration=3.0,
        hook_style=SubtitleStyle(
            size=72, bold=True, border_style=3, alignment=8, margin_v=220,
            primary="#FFFFFF", back="#CC000000", outline_width=0, shadow=0,
        ),
        hook_max_chars=44,
        facecam_enabled=True,
        facecam_size=560,
        facecam_layout="cam-bottom",
        facecam_top_ratio=0.56,
        facecam_region=1.0,
    ),
    "arabic": _style(        "arabic",
        "عربي (RTL)",
        "Hook et sous-titres alignés pour l'arabe : police à couverture arabe, "
        "texte centré, interligne plus généreux.",
        subtitle=SubtitleStyle(
            font="Arial", size=54, bold=True, outline_width=5, margin_v=170,
            alignment=2, rtl=True,
        ),
        hook_enabled=True,
        hook_duration=3.0,
        hook_style=SubtitleStyle(
            font="Arial", size=84, bold=True, border_style=3, alignment=8, margin_v=280,
            primary="#FFFFFF", back="#CC000000", outline_width=0, shadow=0, rtl=True,
        ),
        hook_max_chars=48,
        language_hint="ar",
    ),
}

DEFAULT_STYLE = "default"


def get_style(name: str | None) -> ClipStyle:
    """Renvoie un style par son nom (repli sur le style par défaut)."""
    if not name:
        return STYLES[DEFAULT_STYLE]
    return STYLES.get(name.strip().lower(), STYLES[DEFAULT_STYLE])


def style_names() -> list[str]:
    return list(STYLES)


def style_for_language(language: str | None, preferred: str | None = None) -> ClipStyle:
    """Choisit le style : celui demandé, sinon celui adapté à la langue."""
    if preferred:
        return get_style(preferred)
    code = (language or "").lower().split("-")[0]
    if code in {"ar", "fa", "he", "ur"}:
        return STYLES["arabic"]
    return STYLES[DEFAULT_STYLE]
