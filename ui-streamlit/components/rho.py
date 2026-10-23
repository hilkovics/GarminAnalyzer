"""Mini ρ indicator of the findings list: a −1…+1 axis, the headline ρ as a dot, its 95 % CI as a whisker.

DTO in, SVG text out; the page renders it with `st.markdown(..., unsafe_allow_html=True)`. The headline is
the partial ρ if there is one, else the raw ρ (the same pick as `CorrelationDTO.headline_rho`). Positive ρ is
blue, negative orange; an uncertain finding (the CI contains 0) is drawn muted grey. Axis marks use
`currentColor`, so they read on both themes.
"""

import math

from training.services.dto import CorrelationDTO

from .format import fmt_rho
from .theme import BLUE, GRAY, ORANGE

WIDTH = 300
HEIGHT = 38
_PAD = 14  # horizontal padding so the "−1" / "+1" labels are not clipped
_AXIS_Y = 12


def headline(f: CorrelationDTO) -> tuple[float | None, float | None, float | None]:
    """(ρ, CI low, CI high) of the finding's headline statistic."""
    if f.partial_rho is not None:
        return f.partial_rho, f.partial_ci_low, f.partial_ci_high
    return f.rho, f.ci_low, f.ci_high


def _x(value: float) -> float:
    clamped = max(-1.0, min(1.0, value))
    return _PAD + (clamped + 1.0) / 2.0 * (WIDTH - 2 * _PAD)


def _ok(v: float | None) -> bool:
    return v is not None and not math.isnan(v)


def rho_svg(f: CorrelationDTO) -> str:
    """Inline SVG for one finding; "" when it has no ρ."""
    rho, low, high = headline(f)
    if not _ok(rho):
        return ""
    assert rho is not None
    color = GRAY if f.uncertain else (BLUE if rho >= 0 else ORANGE)
    label = f"ρ = {fmt_rho(rho, low, high)}" + (" (neisté)" if f.uncertain else "")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="100%" role="img" aria-label="{label}" '
        f'style="max-width:{WIDTH}px;color:inherit">',
        f"<title>{label}</title>",
        f'<line x1="{_x(-1):.1f}" x2="{_x(1):.1f}" y1="{_AXIS_Y}" y2="{_AXIS_Y}" '
        f'stroke="currentColor" stroke-opacity="0.3" stroke-width="1"/>',
        f'<line x1="{_x(0):.1f}" x2="{_x(0):.1f}" y1="{_AXIS_Y - 6}" y2="{_AXIS_Y + 6}" '
        f'stroke="currentColor" stroke-opacity="0.5" stroke-width="1" stroke-dasharray="2 2"/>',
    ]
    if _ok(low) and _ok(high):
        assert low is not None and high is not None
        parts.append(
            f'<line x1="{_x(low):.1f}" x2="{_x(high):.1f}" y1="{_AXIS_Y}" y2="{_AXIS_Y}" stroke="{color}" '
            'stroke-opacity="0.55" stroke-width="5" stroke-linecap="round"/>'
        )
    parts.append(f'<circle cx="{_x(rho):.1f}" cy="{_AXIS_Y}" r="4.5" fill="{color}"/>')
    for value, text, anchor in ((-1, "−1", "start"), (0, "0", "middle"), (1, "+1", "end")):
        x = _x(value) + (-_PAD + 2 if value == -1 else _PAD - 2 if value == 1 else 0)
        parts.append(
            f'<text x="{x:.1f}" y="{HEIGHT - 3}" font-size="14" text-anchor="{anchor}" '
            f'fill="currentColor" fill-opacity="0.65">{text}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
