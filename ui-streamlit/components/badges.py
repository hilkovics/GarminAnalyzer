"""Text/colour helpers for status badges (ACWR band, load sanity). No Streamlit import.

`Badge.markdown` yields Streamlit's coloured-badge markdown, e.g. `:green-badge[Optimum]`. The band itself is
decided by the metrics layer (`PmcPointDTO.acwr_band`); this only maps it to a label and a colour.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Badge:
    text: str
    color: str  # a Streamlit colour name: green | orange | red | blue | gray

    @property
    def markdown(self) -> str:
        return f":{self.color}-badge[{self.text}]"


_ACWR = {
    "under": Badge("nízka záťaž", "blue"),
    "optimal": Badge("optimum", "green"),
    "caution": Badge("pozor", "orange"),
    "danger": Badge("riziko", "red"),
}
_UNKNOWN = Badge("–", "gray")

_SANITY = {
    "good": Badge("dobrá zhoda", "green"),
    "fair": Badge("prijateľná zhoda", "orange"),
    "warning": Badge("slabá zhoda, skontroluj LTHR", "red"),
    "insufficient": Badge("málo dát", "gray"),
}


def acwr_badge(band: str | None) -> Badge:
    """ACWR band ("under" | "optimal" | "caution" | "danger" | None) → label and colour."""
    return _ACWR.get(band or "", _UNKNOWN)


def load_sanity_badge(status: str | None) -> Badge:
    """Load-sanity status (METRICS §2.5) → label and colour."""
    return _SANITY.get(status or "", _UNKNOWN)
