from src.core.engine import BotEngine


class _DummyPredictor:
    def __init__(self, loaded: bool):
        self.is_model_loaded = loaded


class _DummyEngine:
    def __init__(self, predictor=None, continuous_learner=None):
        self.confluence = None
        self.predictor = predictor
        self.continuous_learner = continuous_learner


def _ai_row(engine: _DummyEngine):
    rows = BotEngine.get_algorithm_stats(engine)
    return next(r for r in rows if r.get("name") == "ai_predictor")


def test_ai_predictor_reports_enabled_with_heuristic_fallback():
    row = _ai_row(_DummyEngine(predictor=_DummyPredictor(loaded=False)))
    assert row["enabled"] is True
    assert "heuristic" in row["note"]


def test_ai_predictor_reports_enabled_with_continuous_learner_only():
    row = _ai_row(_DummyEngine(predictor=None, continuous_learner=object()))
    assert row["enabled"] is True
