"""Small CSS layer on top of `.streamlit/config.toml` – only what the theme options cannot express.

Colours stay in the theme (it knows light and dark); the rules here use the neutral series colours of
`components/theme.py` (visible on both themes) or inherit from the theme. Injected once per run by `app.py`.
"""

import streamlit as st
from components.theme import AQUA, BLUE, NUMBER_FONT, ORANGE

CSS = f"""
html, body, .stApp {{ font-variant-numeric: tabular-nums; }}

/* big numbers use Barlow Semi Condensed, labels are small caps like the design's "Nadpis karty" */
[data-testid="stMetricValue"] {{ font-family: {NUMBER_FONT}; line-height: 1.1; }}
[data-testid="stMetricLabel"] p {{
  text-transform: uppercase; letter-spacing: .08em; font-size: .75rem; font-weight: 600; opacity: .8;
}}
[data-testid="stHeading"] h3 {{
  text-transform: uppercase; letter-spacing: .1em; font-size: .8rem; font-weight: 600; opacity: .75;
}}

/* metric tiles: a coloured bar per series colour (CTL blue, ATL orange, TSB green) */
[class*="st-key-tile_"] {{ border-top-width: 3px; }}
[class*="st-key-tile_ctl"] {{ border-top-color: {BLUE}; }}
[class*="st-key-tile_atl"] {{ border-top-color: {ORANGE}; }}
[class*="st-key-tile_tsb"] {{ border-top-color: {AQUA}; }}

/* plan week: today's day card is outlined in the primary series colour */
[class*="st-key-daycard_today"] {{ border-color: {BLUE}; }}

/* small label / value pairs (dashboard "Dnešný tréning") */
.ka-label {{
  font-size: .72rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; opacity: .7;
}}
.ka-value {{ font-family: {NUMBER_FONT}; font-size: 1.4rem; font-weight: 600; line-height: 1.2; }}
.ka-title {{
  font-family: {NUMBER_FONT}; font-size: 2rem; font-weight: 600; line-height: 1.15; margin: .1rem 0 .6rem;
}}
"""


def inject() -> None:
    """Add the stylesheet to the page (no JavaScript, no background work)."""
    st.html(f"<style>{CSS}</style>")
