"""The "Kokpit" presentation pieces: workout profile, ρ axis, palette, theme config and Slovak plot layout."""

import tomllib
import xml.dom.minidom

import pytest

from tests.test_ui_plan import step
from tests.test_ui_support import UI_DIR, ui_module
from training.services.dto import CorrelationDTO, WorkoutStepDTO


@pytest.fixture(scope="module")
def profile():
    return ui_module("components.profile")


@pytest.fixture(scope="module")
def rho():
    return ui_module("components.rho")


@pytest.fixture(scope="module")
def theme():
    return ui_module("components.theme")


def sweet_spot() -> list[WorkoutStepDTO]:
    """Rozcvička 15 min Z2, 2 × (20 min Z3 / 5 min Z1), Vychladenie 10 min Z1 – the design's example."""
    return [
        step("warmup", 900, 2),
        step("work", 1200, 3, repeat=2, group=0),
        step("recovery", 300, 1, repeat=2, group=0),
        step("cooldown", 600, 1),
    ]


# --- workout profile ----------------------------------------------------------------------------------------


def test_profile_expands_repeats_in_play_order(profile):
    played = profile.expand_steps(sweet_spot())
    assert [(s.type, a / 60, b / 60) for s, a, b in played] == [
        ("warmup", 0, 15),
        ("work", 15, 35),
        ("recovery", 35, 40),
        ("work", 40, 60),
        ("recovery", 60, 65),
        ("cooldown", 65, 75),
    ]
    assert [(n, a / 60, b / 60) for n, a, b in profile.repeat_spans(sweet_spot())] == [(2, 15, 65)]


def test_profile_figure_width_is_duration_and_colour_is_zone(profile):
    theme = ui_module("components.theme")
    fig = profile.workout_profile(sweet_spot())
    by_name = {t.name: t for t in fig.data}
    assert sorted(by_name) == ["Z1", "Z2", "Z3"]
    assert list(by_name["Z3"].width) == [20.0, 20.0] and list(by_name["Z3"].y) == [3, 3]
    assert list(by_name["Z1"].width) == [5.0, 5.0, 10.0]
    assert by_name["Z2"].marker.color == theme.ZONE_COLORS[2]
    assert list(by_name["Z3"].x) == [25.0, 50.0]  # bar centres in minutes
    assert list(fig.layout.xaxis.tickvals) == [0, 15, 35, 40, 60, 65, 75]
    assert fig.layout.xaxis.ticktext[-1] == "75 min"
    assert [a.text for a in fig.layout.annotations] == ["2×"]  # one bracket over the repeated block
    assert fig.layout.separators == ", "
    assert fig.layout.yaxis.visible is False


def test_profile_open_steps_use_their_effort_zone_and_empty_is_explained(profile):
    open_step = WorkoutStepDTO(
        type="steady", duration_s=2700, target_kind="open", zone=2, repeat=None, group=None
    )
    fig = profile.workout_profile([open_step])
    assert [t.name for t in fig.data] == ["Z2"] and list(fig.data[0].width) == [45.0]
    assert not fig.layout.annotations  # nothing repeats
    empty = profile.workout_profile([])
    assert empty.layout.annotations[0].text == "Tréning nemá kroky."


# --- ρ indicator --------------------------------------------------------------------------------------------


def finding(**overrides) -> CorrelationDTO:
    values = {
        "sport": "run",
        "predictor": "sleep_s_lag0",
        "predictor_base": "sleep_s",
        "variant": "lag0",
        "outcome": "ef",
        "n": 50,
        "status": "ok",
        "rho": 0.4,
        "p": 0.01,
        "ci_low": 0.1,
        "ci_high": 0.6,
        "partial_n": 50,
        "partial_rho": 0.46,
        "partial_p": 0.01,
        "partial_ci_low": 0.21,
        "partial_ci_high": 0.65,
        "q_contrast": None,
        "q_ci_low": None,
        "q_ci_high": None,
        "q_n_bottom": None,
        "q_n_top": None,
        "uncertain": False,
        "headline_rho": 0.46,
        "sentence": "Keď spíš dlhšie, EF je vyšší.",
    }
    return CorrelationDTO(**{**values, **overrides})


def test_rho_svg_is_valid_and_places_dot_and_whisker(rho, theme):
    svg = rho.rho_svg(finding())
    xml.dom.minidom.parseString(svg)  # well-formed
    assert 'aria-label="ρ = +0,46 [95 % CI +0,21; +0,65]"' in svg  # headline = the partial ρ, decimal comma
    centre = rho._x(0.0)
    assert centre == pytest.approx(150.0)
    assert f'<circle cx="{rho._x(0.46):.1f}"' in svg
    assert f'x1="{rho._x(0.21):.1f}" x2="{rho._x(0.65):.1f}"' in svg  # the CI whisker
    assert f'fill="{theme.BLUE}"' in svg and ">−1<" in svg and ">+1<" in svg


def test_rho_svg_colours_sign_and_mutes_uncertain(rho, theme):
    negative = rho.rho_svg(finding(partial_rho=-0.3, partial_ci_low=-0.5, partial_ci_high=-0.1))
    assert f'fill="{theme.ORANGE}"' in negative
    muted = rho.rho_svg(finding(uncertain=True, partial_ci_low=-0.1))
    assert f'fill="{theme.GRAY}"' in muted and theme.BLUE not in muted and "(neisté)" in muted


def test_rho_svg_falls_back_to_the_raw_rho_and_clamps(rho):
    raw = rho.rho_svg(finding(partial_rho=None, partial_ci_low=None, partial_ci_high=None, rho=1.2))
    assert (
        'aria-label="ρ = +1,20' in raw and f'<circle cx="{rho._x(1.0):.1f}"' in raw
    )  # clamped to the axis end
    assert rho.rho_svg(finding(rho=None, partial_rho=None)) == ""


# --- palette, layout and theme config -----------------------------------------------------------------------


def test_plotly_layout_uses_the_slovak_separators_and_transparent_background(theme):
    import plotly.graph_objects as go

    fig = theme.apply_base_layout(go.Figure(), height=200)
    assert fig.layout.separators == ", "  # decimal comma, space for thousands
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)" and fig.layout.plot_bgcolor == "rgba(0,0,0,0)"
    assert fig.layout.legend.xanchor == "right"
    dated = theme.date_axis(theme.apply_base_layout(go.Figure(), height=200))
    assert dated.layout.xaxis.tickformat == "%-d. %-m."


def test_palette_keeps_the_colour_meanings(theme):
    z = theme.ZONE_COLORS
    lum = [int(z[i][1:3], 16) + int(z[i][3:5], 16) + int(z[i][5:7], 16) for i in range(1, 6)]
    assert lum == sorted(lum, reverse=True)  # Z1 lightest … Z5 darkest blue
    plan = ui_module("components.plan")
    assert plan.PHASE_COLORS == {
        "base": theme.BLUE,
        "build": theme.ORANGE,
        "peak": theme.RED,
        "taper": theme.AQUA,
    }
    sleep = ui_module("components.sleep")
    assert sleep.BAND_COLORS == {"green": theme.AQUA, "yellow": theme.YELLOW, "red": theme.RED}
    assert sleep.STAGES[2][2] == theme.AQUA and sleep.STAGES[3][2] == theme.ORANGE


def test_readiness_yellow_is_one_colour_for_badge_and_gauge(theme):
    config = tomllib.loads((UI_DIR.parent / ".streamlit" / "config.toml").read_text())
    badges = ui_module("components.badges")
    assert badges.readiness_badge("yellow").color == "yellow"  # Streamlit's yellow family …
    assert config["theme"]["yellowColor"] == theme.YELLOW  # … is the gauge's yellow


def test_streamlit_theme_config_defines_both_modes_and_fonts():
    config = tomllib.loads((UI_DIR.parent / ".streamlit" / "config.toml").read_text())["theme"]
    assert (
        config["dark"]["backgroundColor"] == "#0d0f12"
        and config["dark"]["secondaryBackgroundColor"] == "#161a1f"
    )
    assert config["dark"]["borderColor"] == "#232930" and config["dark"]["primaryColor"] == "#5b9ff0"
    assert config["light"]["backgroundColor"] == "#f2f4f6" and config["light"]["textColor"] == "#12161b"
    assert config["font"].startswith("Barlow:") and config["headingFont"].startswith("Barlow Semi Condensed:")
    assert config["baseRadius"] == "14px"


def test_every_theme_key_is_a_real_streamlit_option():
    from streamlit import config as st_config

    def keys(prefix: str, table: dict):
        for name, value in table.items():
            if isinstance(value, dict):
                yield from keys(f"{prefix}.{name}", value)
            else:
                yield f"{prefix}.{name}"

    config = tomllib.loads((UI_DIR.parent / ".streamlit" / "config.toml").read_text())
    unknown = [k for k in keys("theme", config["theme"]) if k not in st_config._config_options_template]
    assert unknown == []
