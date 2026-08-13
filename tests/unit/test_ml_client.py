from app.ml import EmotionResult, LabelScore, _parse_classification, canonical_sales_label


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


def test_sales_emotion_valence() -> None:
    grouped = EmotionResult(
        labels=[
            LabelScore(label="enthusiastic", score=0.9),
            LabelScore(label="frustrated", score=0.2),
            LabelScore(label="neutral", score=0.1),
        ]
    ).grouped()
    assert grouped["positive"] == 0.9
    assert grouped["negative"] == 0.2
    assert grouped["valence"] == 0.7
