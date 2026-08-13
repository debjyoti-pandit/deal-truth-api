"""Synthetic call scenarios. No customer audio or real transcripts."""

from __future__ import annotations

from typing import Any

HIGH = 0.92
LOW = 0.05


def _seg(sid: int, speaker: str, start: int, text: str, end: int | None = None) -> dict[str, Any]:
    duration = max(4000, len(text) * 80)
    return {
        "id": sid,
        "speaker": speaker,
        "start_ms": start,
        "end_ms": end or start + duration,
        "text": text,
    }


def _transcript(segments: list[dict[str, Any]], *, stereo: bool = False) -> dict[str, Any]:
    speakers = sorted({s["speaker"] for s in segments})
    return {
        "id": "job_fixture",
        "status": "completed",
        "language": "en",
        "result": {
            "language": "en",
            "text": " ".join(s["text"] for s in segments),
            "duration_ms": segments[-1]["end_ms"] if segments else 0,
            "segments": segments,
            "channel": stereo,
        },
        "speakers": speakers,
    }


def _labels_for(text: str, mapping: dict[str, dict[str, float]]) -> dict[str, float]:
    return mapping.get(text, {})


HAPPY_SEGMENTS = [
    _seg(1, "speaker_0", 0, "Thanks for taking the time today. I can walk you through how we route calls."),
    _seg(2, "speaker_1", 8000, "We're losing around 6 hours every week manually routing these calls."),
    _seg(3, "speaker_0", 16000, "That is helpful. I will send the SOC2 report by Friday."),
    _seg(4, "speaker_1", 24000, "If you can support Salesforce, I think we're good to move forward next week."),
]

PRICING_SEGMENTS = [
    _seg(1, "speaker_0", 0, "Our plan is 800 dollars a month."),
    _seg(2, "speaker_1", 6000, "We currently pay about 400. This would be almost double."),
    _seg(3, "speaker_1", 14000, "We're losing around 6 hours every week manually routing these calls."),
]

SECURITY_SEGMENTS = [
    _seg(1, "speaker_0", 0, "We can onboard quickly."),
    _seg(2, "speaker_1", 5000, "Our security team has to approve any new vendor."),
    _seg(3, "speaker_1", 12000, "We can't onboard another vendor without security review."),
]

COMPETITOR_SEGMENTS = [
    _seg(1, "speaker_0", 0, "How are you evaluating tools?"),
    _seg(2, "speaker_1", 4000, "We've also got a demo with AcmeAI next Tuesday."),
    _seg(3, "speaker_1", 11000, "AcmeVoice is cheaper, but we are unsure about Salesforce."),
]

POSITIVE_NO_BUDGET = [
    _seg(1, "speaker_1", 0, "This is impressive, but there's no chance we have budget this quarter."),
    _seg(2, "speaker_0", 8000, "I can send a proposal anyway."),
]

NO_TIMELINE = [
    _seg(1, "speaker_1", 0, "We're losing around 6 hours every week manually routing these calls."),
    _seg(2, "speaker_0", 8000, "When would you want to decide?"),
    _seg(3, "speaker_1", 12000, "Not sure, we are just exploring."),
]

NO_ECONOMIC_BUYER = [
    _seg(1, "speaker_1", 0, "I like the product and it would save my team time."),
    _seg(2, "speaker_0", 7000, "Are you the budget owner?"),
    _seg(3, "speaker_1", 11000, "I am on the ops team. I cannot approve spend."),
]

OVERSTATED = [
    _seg(1, "speaker_0", 0, "Customer is ready to purchase this month."),
    _seg(2, "speaker_1", 6000, "We still need to evaluate two other vendors."),
    _seg(3, "speaker_1", 14000, "Our security team has to approve any new vendor."),
]

SELLER_DUE = [
    _seg(1, "speaker_0", 0, "I will send the SOC2 documentation by Friday."),
    _seg(2, "speaker_1", 7000, "Please also share the Salesforce integration docs tomorrow."),
    _seg(3, "speaker_0", 14000, "I will send the Salesforce integration docs tomorrow."),
]

WEAKENED = [
    _seg(1, "speaker_1", 0, "Let's meet next week to go through security."),
    _seg(2, "speaker_0", 6000, "Great, we will reconvene next week."),
    _seg(3, "speaker_1", 12000, "Actually, just send me something and I'll get back to you."),
]


def _map(*pairs: tuple[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return dict(pairs)


SCENARIOS: dict[str, dict[str, Any]] = {
    "happy_path": {
        "transcript": _transcript(HAPPY_SEGMENTS),
        "recap": {
            "status": "completed",
            "headline": "Ops team wants Salesforce routing",
            "tldr": "Customer has quantified pain and a next-week intent.",
            "summary": "The customer described six hours of weekly routing work and asked about Salesforce.",
            "action_items": [{"text": "Send SOC2 report by Friday", "side": "seller", "due_text": "Friday"}],
            "next_steps": [{"text": "Move forward next week", "side": "customer"}],
            "decisions": ["Evaluate Salesforce support"],
        },
        "classifications": _map(
            (HAPPY_SEGMENTS[0]["text"], {"seller commitment": HIGH}),
            (HAPPY_SEGMENTS[1]["text"], {"pain point": HIGH}),
            (HAPPY_SEGMENTS[2]["text"], {"seller commitment": HIGH}),
            (
                HAPPY_SEGMENTS[3]["text"],
                {
                    "positive buying signal": HIGH,
                    "purchase timeline": HIGH,
                    "next meeting commitment": HIGH,
                    "integration requirement": HIGH,
                    "customer commitment": HIGH,
                },
            ),
        ),
        "emotions": {HAPPY_SEGMENTS[1]["text"]: {"optimism": 0.7, "approval": 0.2}},
        "tracked": [("Salesforce", ["salesforce"])],
    },
    "pricing_objection": {
        "transcript": _transcript(PRICING_SEGMENTS),
        "recap": {"status": "completed", "headline": "Price is double current vendor"},
        "classifications": _map(
            (PRICING_SEGMENTS[1]["text"], {"pricing objection": HIGH}),
            (PRICING_SEGMENTS[2]["text"], {"pain point": HIGH}),
        ),
        "emotions": {PRICING_SEGMENTS[1]["text"]: {"annoyance": 0.6}},
        "tracked": [],
    },
    "security_blocker": {
        "transcript": _transcript(SECURITY_SEGMENTS),
        "recap": {"status": "completed", "headline": "Security review required"},
        "classifications": _map(
            (SECURITY_SEGMENTS[1]["text"], {"security blocker": HIGH}),
            (SECURITY_SEGMENTS[2]["text"], {"security blocker": HIGH}),
        ),
        "emotions": {},
        "tracked": [],
    },
    "active_competitor": {
        "transcript": _transcript(COMPETITOR_SEGMENTS),
        "recap": {"status": "completed", "headline": "AcmeAI demo scheduled"},
        "classifications": _map(
            (COMPETITOR_SEGMENTS[1]["text"], {"competitor mention": HIGH, "purchase timeline": 0.4}),
            (COMPETITOR_SEGMENTS[2]["text"], {"competitor mention": HIGH, "competitor preference": 0.6}),
        ),
        "emotions": {},
        "tracked": [("AcmeAI", ["acmeai", "acmevoice", "AcmeVoice"])],
    },
    "positive_emotion_no_budget": {
        "transcript": _transcript(POSITIVE_NO_BUDGET),
        "recap": {"status": "completed", "headline": "Admiration with budget blocker"},
        "classifications": _map(
            (
                POSITIVE_NO_BUDGET[0]["text"],
                {"budget blocker": HIGH, "positive buying signal": 0.2, "negative buying signal": 0.7},
            ),
        ),
        "emotions": {POSITIVE_NO_BUDGET[0]["text"]: {"admiration": 0.72, "optimism": 0.18}},
        "tracked": [],
    },
    "no_purchase_timeline": {
        "transcript": _transcript(NO_TIMELINE),
        "recap": {"status": "completed", "headline": "Exploring without a deadline"},
        "classifications": _map(
            (NO_TIMELINE[0]["text"], {"pain point": HIGH}),
            (NO_TIMELINE[2]["text"], {"purchase timeline": LOW, "negative buying signal": 0.4}),
        ),
        "emotions": {},
        "tracked": [],
    },
    "no_economic_buyer": {
        "transcript": _transcript(NO_ECONOMIC_BUYER),
        "recap": {"status": "completed", "headline": "Champion is not the buyer"},
        "classifications": _map(
            (
                NO_ECONOMIC_BUYER[0]["text"],
                {"pain point": HIGH, "positive buying signal": 0.7, "economic buyer identified": LOW},
            ),
            (NO_ECONOMIC_BUYER[2]["text"], {"economic buyer identified": LOW, "budget blocker": 0.6}),
        ),
        "emotions": {},
        "tracked": [],
    },
    "seller_overstates_intent": {
        "transcript": _transcript(OVERSTATED),
        "recap": {"status": "completed", "headline": "Seller overstated readiness"},
        "classifications": _map(
            (OVERSTATED[0]["text"], {"positive buying signal": HIGH, "seller commitment": 0.2}),
            (OVERSTATED[1]["text"], {"competitor mention": HIGH, "negative buying signal": 0.6}),
            (OVERSTATED[2]["text"], {"security blocker": HIGH}),
        ),
        "emotions": {},
        "tracked": [],
    },
    "seller_commitment_due_date": {
        "transcript": _transcript(SELLER_DUE),
        "recap": {
            "status": "completed",
            "headline": "Docs promised with dates",
            "action_items": [
                {"text": "Send SOC2 documentation by Friday", "side": "seller", "due_text": "Friday"},
                {"text": "Share Salesforce integration docs tomorrow", "side": "seller", "due_text": "tomorrow"},
            ],
        },
        "classifications": _map(
            (SELLER_DUE[0]["text"], {"seller commitment": HIGH}),
            (SELLER_DUE[1]["text"], {"feature requirement": 0.6, "customer commitment": 0.2}),
            (SELLER_DUE[2]["text"], {"seller commitment": HIGH}),
        ),
        "emotions": {},
        "tracked": [("Salesforce", [])],
    },
    "customer_weakens_commitment": {
        "transcript": _transcript(WEAKENED),
        "recap": {"status": "completed", "headline": "Next meeting slipped to a maybe"},
        "classifications": _map(
            (WEAKENED[0]["text"], {"next meeting commitment": HIGH, "customer commitment": HIGH}),
            (WEAKENED[1]["text"], {"seller commitment": 0.7, "positive buying signal": 0.6}),
            (WEAKENED[2]["text"], {"next meeting commitment": LOW, "negative buying signal": 0.55}),
        ),
        "emotions": {},
        "tracked": [],
    },
}
