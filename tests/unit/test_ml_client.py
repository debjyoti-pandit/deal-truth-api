from app.ml import AxisAvailability, EmotionAxes, LabelScore, _parse_classification, canonical_sales_label


def test_canonical_sales_label_maps_worker_slugs() -> None:
    assert canonical_sales_label("pain_point") == "pain point"
    assert canonical_sales_label("pain point") == "pain point"
    assert canonical_sales_label("security-blocker") == "security blocker"


def test_parse_classification_accepts_slug_ids() -> None:
    result = _parse_classification(
        {"labels": [{"label": "pain_point", "score": 0.91}, {"label": "budget_blocker", "score": 0.8}]}
    )
    assert result.score("pain point") == 0.91
    assert result.as_dict()["pain point"] == 0.91
    assert result.as_dict()["budget blocker"] == 0.8


def test_parse_classification_accepts_v1_label_ids() -> None:
    # `/v1/classify` names the label `id`, not `label`, and only returns the ones that
    # cleared their catalogue threshold.
    result = _parse_classification(
        {"id": "0", "labels": [{"id": "pain_point", "score": 0.91, "passed_threshold": True}]}
    )
    assert result.as_dict() == {"pain point": 0.91}


def test_sales_emotion_valence_is_emotion_axis_only() -> None:
    grouped = EmotionAxes(
        emotion=[
            LabelScore(label="enthusiastic", score=0.9),
            LabelScore(label="frustrated", score=0.2),
            LabelScore(label="neutral", score=0.1),
        ],
        # `negative` here is buying intent, not a feeling. Folding it into valence is the
        # merge the axes exist to prevent.
        buying_intent=[LabelScore(label="negative", score=0.95)],
    ).grouped()
    assert grouped is not None
    assert grouped["positive"] == 0.9
    assert grouped["negative"] == 0.2
    assert grouped["valence"] == 0.7


def test_grouped_is_none_when_the_emotion_axis_was_never_scored() -> None:
    axes = EmotionAxes(unavailable=AxisAvailability(emotion=True))
    assert axes.grouped() is None
    assert axes.valence() is None
    # The other two axes are untouched — axes fail independently.
    assert not axes.is_unavailable("buying_intent")
    assert axes.any_available()
