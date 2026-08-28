import pytest
from pydantic import ValidationError

from mendpact.domain import ReplayDecision, ReplayPlan
from mendpact.drivers.replay import ReplayDataError, ReplayDriver


def test_rejects_duplicate_replay_keys() -> None:
    plan = ReplayPlan(
        model="test-model",
        decisions=[
            ReplayDecision(scenario_id="one", attempt=1),
            ReplayDecision(scenario_id="one", attempt=1),
        ],
    )

    with pytest.raises(ReplayDataError, match="Duplicate replay decision"):
        ReplayDriver(plan)


def test_rejects_unknown_replay_schema_version() -> None:
    with pytest.raises(ValidationError):
        ReplayPlan.model_validate(
            {
                "schema_version": "mendpact.replay.v2",
                "model": "test-model",
                "decisions": [{"scenario_id": "one"}],
            }
        )
