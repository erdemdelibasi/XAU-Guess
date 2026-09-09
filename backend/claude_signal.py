"""Claude's own read on gold, as one component among several.

Given the same evidence the mechanical components see -- the technical score,
the macro drivers, current levels, and the actual recent headlines rather than
news_signal.py's keyword tally -- this asks for an independent direction and
confidence via a single Messages API call per prediction cycle.

COST, AND WHY THE MODEL CHOICE DIFFERS FROM XRP-GUESS
-----------------------------------------------------
That project ran every 15 minutes -- 96 calls a day -- so it chose Sonnet and
documented rejecting a stronger model on cost (~$25-30/mo versus ~$5-6). This
one runs ONCE per trading day. At roughly 1500 input and a few hundred output
tokens that is on the order of a dollar a month on Opus, so the cost argument
that shaped the sibling project simply does not apply here and the default
model is used.

THE PROMPT LESSON, CARRIED OVER
-------------------------------
XRP-Guess's system prompt originally said "do not just restate the technical
signal's direction". The intent was to stop parroting; the effect was to push
the model toward *disagreeing* with the one component that had a measured
edge. Live data was consistent with that backfiring -- over its first 73
resolved rows that component agreed with `technical` only 48% of the time,
called DOWN in 56 of 73, and scored 37%: not uninformative, anti-correlated.
So the prompt below explicitly says agreement is a fine answer.

A METALS-SPECIFIC ADDITION
--------------------------
The prompt states THIS METAL's base rate outright -- gold closes higher over
five trading days 55.7% of the time, silver 53.9% (research/compare.py, 25
years). Without that, a model reasonably treats 50/50 as neutral and its "UP"
carries no information beyond the drift everything already has.
research/edge.py showed the mechanical models beating chance while still
losing to always-UP, which is exactly the failure mode this line avoids.

Like every other signal module: fails soft to neutral on any problem, so a
hiccup here never blocks a prediction run. It cannot be backtested (no cheap
way to replay a paid call against 25 years of history, and the model has
memorised those dates anyway), so its value is only judgeable from live rows.
"""
from __future__ import annotations

import json
import os

import anthropic

import news_signal

# The current default model. See the module docstring: at one call per
# trading day the cost reasoning that pushed XRP-Guess to a smaller model
# does not apply.
MODEL = "claude-opus-5"
MAX_HEADLINES = 10
NEUTRAL = {"direction": "UP", "confidence": 0.0, "score": 0.0}


def build_system_prompt(asset) -> str:
    """The prompt names THIS metal and quotes THIS metal's measured base rate.

    Quoting the base rate is not decoration. research/edge.py measured the
    mechanical models beating chance while still losing to always-UP; a model
    told nothing about the drift reasonably treats 50/50 as neutral, and its
    "UP" then carries no information beyond what everything already has.
    Gold's rate is 55.7% and silver's 53.9% -- close enough that reusing one
    prompt for both would look harmless and still misstate the baseline the
    model is asked to beat.
    """
    return SYSTEM_PROMPT_TEMPLATE.format(
        label=asset.label_en, symbol=asset.symbol,
        base_pct=f"{100 * asset.base_rate_up:.0f}",
    )


SYSTEM_PROMPT_TEMPLATE = (
    "You are forecasting the direction of COMEX {label} ({symbol}) over the "
    "next 5 trading days for a paper-trading experiment. You will see a "
    "rule-based technical score, a macro-driver score, current market levels, "
    "and recent headlines.\n\n"
    "Two things you must account for:\n"
    "1. {label} closes higher over 5 trading days about {base_pct}% of the "
    "time. A bare 'UP' therefore carries almost no information -- it is close "
    "to the base rate. Only report meaningful confidence when you think the "
    "odds differ from that {base_pct}% baseline for a specific, identifiable "
    "reason.\n"
    "2. Weigh the evidence and reach your own judgment. Agreeing with the "
    "technical or macro signal is a perfectly good answer when the evidence "
    "supports it -- judge it on the merits rather than either deferring to it "
    "or making a point of diverging from it.\n\n"
    "Most of the time there is no real edge. Confidence above roughly 0.20 "
    "should be rare and should correspond to a concrete catalyst you can "
    "point to. Respond only via the given schema. The 'reasoning' field is "
    "shown verbatim on a Turkish-language dashboard next to Turkish labels "
    "for every other component, so write it in Turkish; 'direction' must "
    "still be exactly 'UP' or 'DOWN' as the schema requires."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "direction": {"type": "string", "enum": ["UP", "DOWN"]},
        # json_schema in output_config.format rejects "minimum"/"maximum" on a
        # number property with a 400, so the 0..1 range is clamped at runtime.
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["direction", "confidence", "reasoning"],
    "additionalProperties": False,
}


def _format_context(asset, price: float, tech: dict, macro: dict, context: dict,
                    headlines: list[dict]) -> str:
    lines = [
        f"Current {asset.label_en} price ({asset.symbol}): ${price:,.2f}",
        f"Technical component: {tech['direction']}, raw confidence {tech['confidence']:.3f}",
        f"Macro-driver component: {macro['direction']}, raw confidence {macro['confidence']:.3f}",
        "",
        "Current levels:",
    ]
    # Both metals are listed and only the COUNTERPART one is ever populated
    # (see macro_signal.describe_context): gold's panel carries silver's
    # close, silver's carries gold's. Naming only "silver" here -- as this
    # dict did -- silently dropped the counterpart level from the silver
    # prompt while leaving the gold/silver ratio in it, i.e. a ratio with
    # neither of its legs on screen.
    labels = {
        "dxy": "US Dollar Index", "us10y": "US 10Y Treasury yield (%)",
        "vix": "VIX", "gold": "Gold ($/oz)", "silver": "Silver ($/oz)",
        "spx": "S&P 500", "gold_silver_ratio": "Gold/Silver ratio",
    }
    for key, label in labels.items():
        value = context.get(key)
        if value is not None:
            lines.append(f"  {label}: {value:,.2f}")
    z = context.get("gold_silver_z")
    if z is not None:
        lines.append(f"  Gold/Silver ratio, z-score vs its own 1y history: {z:+.2f}")

    if headlines:
        lines.append("")
        lines.append(f"Recent {asset.label_en}-related headlines (last 24h):")
        lines += [f"- {h['title']}" for h in headlines[:MAX_HEADLINES]]
    else:
        lines.append("")
        lines.append(f"No {asset.label_en}-related headlines retrieved in the last 24 hours.")

    lines.append("")
    lines.append(f"Predict the direction of {asset.label_en} over the next 5 trading days.")
    return "\n".join(lines)


def claude_signal(asset, price: float, tech: dict, macro: dict, context: dict) -> dict:
    """{"direction", "confidence", "score"} -- the shape every signal module uses.

    Neutral when ANTHROPIC_API_KEY is unset (so the system runs fine before
    the key is provisioned) and on any API or parsing failure.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return dict(NEUTRAL)

    headlines = news_signal.recent_headlines(asset.key)

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=build_system_prompt(asset),
            messages=[{
                "role": "user",
                "content": _format_context(asset, price, tech, macro, context, headlines),
            }],
            output_config={
                # A daily judgement over a page of context -- worth some
                # reasoning, but this is still closer to classification than
                # to analysis, and XRP-Guess measured that throwing model
                # strength at this shape of task did not move accuracy.
                "effort": "medium",
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
        )

        # A safety decline arrives as HTTP 200 with stop_reason "refusal" and
        # no usable text, so it must be checked before reading content.
        # Server-side `fallbacks` are deliberately NOT used here: this
        # component's designed failure mode is abstention, which costs
        # nothing and is already the correct answer, whereas a fallback would
        # buy a second paid call to rescue an opinion the ensemble treats as
        # optional anyway.
        if response.stop_reason == "refusal":
            print("WARNING: claude_signal refused; falling back to neutral.")
            return dict(NEUTRAL)

        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
        direction = parsed["direction"]
        confidence = max(0.0, min(1.0, float(parsed["confidence"])))
        reasoning = str(parsed.get("reasoning", ""))[:500]
    except (anthropic.APIStatusError, anthropic.APIConnectionError, StopIteration,
            KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARNING: claude_signal failed ({exc}) -- falling back to neutral.")
        return dict(NEUTRAL)

    score = confidence if direction == "UP" else -confidence
    return {"direction": direction, "confidence": confidence, "score": score,
            "reasoning": reasoning}
