"""Built-in themes, number for number from the apps snakelane grew out of. Sizes under 1 are shares
of the canvas height; fonts ship with every Mac. Why: docs/design/framing.md#themes"""

from __future__ import annotations

from typing import Any

FONTS, SUPPLEMENTAL = "/System/Library/Fonts", "/System/Library/Fonts/Supplemental"
AVENIR_HEAVY = {"font": f"{FONTS}/Avenir Next.ttc", "font_face": "Heavy", "italic_face": "Heavy Italic"}
SF_HEAVY = {"font": f"{FONTS}/SFNS.ttf", "font_face": "Heavy", "bold_face": "Black", "italic_font": f"{FONTS}/SFNSItalic.ttf",
            "italic_face": "Heavy Italic", "bold_italic_face": "Black Italic"}
SF_ROUNDED_HEAVY = {"font": f"{FONTS}/SFNSRounded.ttf", "font_face": "Heavy", "bold_face": "Black"}  # no italic
NEW_YORK_BOLD = {"font": f"{FONTS}/NewYork.ttf", "font_face": "Bold", "bold_face": "Black",
                 "italic_font": f"{FONTS}/NewYorkItalic.ttf", "italic_face": "Bold Italic", "bold_italic_face": "Black Italic"}
HELVETICA_BOLD = {"font": f"{FONTS}/HelveticaNeue.ttc", "font_face": "Bold", "italic_face": "Bold Italic"}
ROCKWELL_BOLD = {"font": f"{SUPPLEMENTAL}/Rockwell.ttc", "font_face": "Bold", "italic_face": "Bold Italic"}
FUTURA_CONDENSED = {"font": f"{SUPPLEMENTAL}/Futura.ttc", "font_face": "Condensed ExtraBold"}  # no italic
# The gold lip and its shadow, shared by the felt and ruby arches (Lamplight and Spider Solitaire).
GOLD_LIP = {"color": "#BF8F2E", "highlight": "#FCD978", "height": 0.012}
GOLD_SHADOW = {"color": "#000000", "opacity": 0.55, "blur": 0.0216, "offset": [0, 0.006]}

# One theme per distinct look; recolours go in VARIATIONS.
THEMES: dict[str, dict[str, Any]] = {
    # Card-table green, gold lip, heavy white capitals (Lamplight Solitaire's arch).
    "felt": {**AVENIR_HEAVY, "case": "upper", "fill": ["#1A7540", "#053D1F"], "text": "#FFFFFF",
             "panel": {"color": "#298C4F", "opacity": 0.55}, "lip": GOLD_LIP, "shadow": GOLD_SHADOW,
             "text_shadow": {"color": "#001F0A", "opacity": 0.8}},
    # The same rail in card-room red (Spider Solitaire, Spades; Hearts' coral rim is a variation).
    "ruby": {**AVENIR_HEAVY, "case": "upper", "fill": ["#CC1A17", "#8F0508"], "text": "#FFFFFF",
             "panel": {"color": "#DB3329", "opacity": 0.55}, "lip": GOLD_LIP, "shadow": GOLD_SHADOW,
             "text_shadow": {"color": "#4D0000", "opacity": 0.8}},
    # A card club: dark green strip, copper rule, soft shadow, slab serif (Euchre; Spades Mac, Word Search vary it).
    "evergreen": {**ROCKWELL_BOLD, "fill": "#0E281B", "text": "#FFFFFF", "rule": {"color": "#C78538", "height": 0.0023},
                  "shadow": {"color": "#000000", "opacity": 0.45, "blur": 0.009, "offset": [0, 0.008]}},
    # A book page: parchment, dark serif ink, copper accent (Jigsaw Puzzles; pairs with a sagging arch).
    "parchment": {**NEW_YORK_BOLD, "fill": "#FAF5EB", "text": "#2E2924", "accent": "#B56B2B"},
    # Night indigo band and letterbox, round friendly type (Puzzle Reef, for young children).
    "indigo": {**SF_ROUNDED_HEAVY, "fill": "#170F33", "text": "#FFFFFF"},
    # Near-black band, lime rule and accent, condensed poster capitals on warm brown (Picnic Defense).
    "campfire": {**FUTURA_CONDENSED, "case": "upper", "fill": "#16110B", "background": ["#3D3024", "#241C14"],
                 "text": "#FFFFFF", "accent": "#B8EB66", "rule": {"color": "#B8EB66", "height": 0.0038}},
    # Brand-blue canvas for a device card, white system type (Pool Log).
    "azure": {**SF_HEAVY, "fill": "#2F6FED", "background": "#2F6FED", "text": "#FFFFFF",
              "shadow": {"color": "#000000", "opacity": 0.30, "blur": 0.03, "offset": [0, 0.012]}},
    # Blue dusk gradient, white type, amber accent, a card bleeding off the bottom (Cloudless Cam).
    "dusk": {**HELVETICA_BOLD, "fill": ["#2F6BEA", "#0B2352"], "background": ["#2F6BEA", "#0B2352"],
             "text": "#FFFFFF", "accent": "#FFC46B",
             "shadow": {"color": "#000000", "opacity": 0.43, "blur": 0.014, "offset": [0, 0.0063]}},
}

# Recolours of a theme, as the overrides an app would write: shown in the docs, not built in.
VARIATIONS: dict[str, dict[str, Any]] = {
    # Hearts: deep red, a coral rim and an opaque inner panel.
    "coral": {"base": "ruby", "fill": ["#C80C0E", "#8C0000"], "panel": {"color": "#E03234", "opacity": 1.0},
              "lip": {"color": "#CC4C29", "highlight": "#F65F34", "height": 0.011},
              "text_shadow": {"color": "#500000", "opacity": 0.75}},
    "walnut": {"base": "evergreen", "fill": "#3B2612", "text": "#F5E6C4"},  # Spades on the Mac: brass rule, cream type
    "moss": {"base": "evergreen", "fill": "#293626", "rule": None, "shadow": None},  # Word Search: plain moss band
}
