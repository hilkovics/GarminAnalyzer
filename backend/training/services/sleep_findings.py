"""Slovak wording of the §9 correlation findings: fixed label dicts, strength words, caveat, `CorrelationDTO`.

Presentation text only – the statistics come from `training.analysis.correlation`. The sentence template is

    Keď <predictor phrase> (<variant>), <outcome subject> je <vyšší|nižší> – <slabá|stredná|silná> súvislosť.

with the direction taken from the sign of the headline ρ (partial, else raw) and the strength from |ρ|.
"""

from training.analysis.correlation import MIN_N, VARIANTS, CorrelationResult
from training.services.dto import CorrelationDTO

CAVEAT = (
    "Korelácia nie je kauzalita: súvislosť medzi spánkom a výkonom ešte neznamená, že jedno spôsobuje druhé. "
    "EF založený na tepe ovplyvňuje aj teplo, kofeín a choroba. "
    "Porovnaní je veľa a nekorigujú sa na násobné testovanie, takže jednotlivé zistenia môžu byť náhoda."
)

WEAK_BELOW = 0.3
MEDIUM_BELOW = 0.5

# "Keď <phrase>" – the phrase describes a HIGHER predictor value; the sign of ρ flips only the outcome side.
PREDICTOR_PHRASES = {
    "sleep_s": "spíš dlhšie",
    "deep_s": "máš viac hlbokého spánku",
    "rem_s": "máš viac REM spánku",
    "sleep_score": "máš vyššie skóre spánku",
    "rhr": "máš vyšší pokojový tep",
    "body_battery_wake": "sa zobudíš s vyššou Body Battery",
    "sleep_debt_7": "máš väčší spánkový dlh za posledných 7 nocí",
}
VARIANT_LABELS = {
    "lag0": "noc pred tréningom",
    "lag1": "dve noci pred tréningom",
    "mean3": "priemer 3 nocí pred tréningom",
}
NO_VARIANT_LABEL = {"sleep_debt_7"}  # already says "posledných 7 nocí"

SPORT_LABELS = {"run": "pri behu", "bike": "na bicykli"}
# outcome → (subject with a {sport} slot, word when higher, word when lower)
OUTCOME_TEXT = {
    "ef": ("tvoj EF {sport}", "vyšší", "nižší"),
    "decoupling_pct": ("tvoj aeróbny decoupling {sport}", "vyšší (horší)", "nižší (lepší)"),
    "pace_at_ref_hr_day": ("tvoje tempo pri referenčnom tepe {sport}", "rýchlejšie", "pomalšie"),
    "rpe_residual": ("tvoje vnímané úsilie (RPE) {sport} oproti očakávanému", "vyššie", "nižšie"),
}
UNCERTAIN_SUFFIX = " (neisté – interval obsahuje 0)"


def split_predictor(predictor: str) -> tuple[str, str]:
    """`sleep_s_lag1` → (`sleep_s`, `lag1`); `sleep_debt_7` → (`sleep_debt_7`, `lag0`)."""
    for variant in VARIANTS:
        if predictor.endswith(f"_{variant}"):
            return predictor[: -len(variant) - 1], variant
    return predictor, "lag0"


def strength_word(rho: float) -> str:
    """slabá / stredná / silná (feminine, agrees with "súvislosť") at |ρ| < 0.3 / < 0.5 / ≥ 0.5."""
    size = abs(rho)
    if size < WEAK_BELOW:
        return "slabá"
    if size < MEDIUM_BELOW:
        return "stredná"
    return "silná"


def _predictor_text(base: str, variant: str) -> str:
    phrase = PREDICTOR_PHRASES.get(base, base)
    if base in NO_VARIANT_LABEL:
        return f"Keď {phrase}"
    return f"Keď {phrase} ({VARIANT_LABELS.get(variant, variant)})"


def sentence(result: CorrelationResult) -> str:
    """The Slovak sentence of one finding (also for pairs without data)."""
    base, variant = split_predictor(result.predictor)
    subject, higher, lower = OUTCOME_TEXT.get(result.outcome, (result.outcome + " {sport}", "vyšší", "nižší"))
    subject = subject.format(sport=SPORT_LABELS.get(result.sport, ""))
    head = _predictor_text(base, variant)
    if result.status != "ok":
        return f"{head} → {subject}: nedostatok dát (n = {result.n}, treba aspoň {MIN_N})."
    rho = result.headline_rho
    if rho is None:
        return f"{head} → {subject}: súvislosť sa nedá určiť (konštantná hodnota)."
    if rho == 0:
        return f"{head} → {subject}: žiadna súvislosť (ρ = 0)."
    text = f"{head}, {subject} je {higher if rho > 0 else lower} – {strength_word(rho)} súvislosť"
    return text + (UNCERTAIN_SUFFIX if result.uncertain else "") + "."


def correlation_dto(result: CorrelationResult) -> CorrelationDTO:
    base, variant = split_predictor(result.predictor)
    return CorrelationDTO(
        sport=result.sport,
        predictor=result.predictor,
        predictor_base=base,
        variant=variant,
        outcome=result.outcome,
        n=result.n,
        status=result.status,
        rho=result.rho,
        p=result.p,
        ci_low=result.ci_low,
        ci_high=result.ci_high,
        partial_n=result.partial_n,
        partial_rho=result.partial_rho,
        partial_p=result.partial_p,
        partial_ci_low=result.partial_ci_low,
        partial_ci_high=result.partial_ci_high,
        q_contrast=result.q_contrast,
        q_ci_low=result.q_ci_low,
        q_ci_high=result.q_ci_high,
        q_n_bottom=result.q_n_bottom,
        q_n_top=result.q_n_top,
        uncertain=result.uncertain,
        headline_rho=result.headline_rho,
        sentence=sentence(result),
    )
