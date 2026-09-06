from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.api.schemas import EvalRunRequest
from opsmind.evals import EvalSuiteLoader, SQLiteEvalRepository
from opsmind.models import MockModelProvider, ModelGateway, ModelProfile, ModelRoute
from opsmind.runs import SQLiteRunRepository
from opsmind.state import AgentAction, PrimaryIntent, RequestType, RiskSignal


def test_eval_request_rejects_blank_suite_id() -> None:
    with pytest.raises(ValueError, match="suite_id must not be blank"):
        EvalRunRequest.model_validate({"suite_id": " \t"})


def _understanding() -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom="test",
        entities={},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def test_eval_api_runs_and_reads_persisted_job(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_id": "api-suite",
                "suite_version": "1.0",
                "description": "API test suite",
                "cases": [
                    {
                        "case_id": "C1",
                        "title": "close",
                        "turns": [{"message": "done"}],
                        "assertions": [
                            {
                                "assertion_id": "action",
                                "type": "final_action_in",
                                "expected": ["END_CONVERSATION"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = MockModelProvider(
        structured_responses=[
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="done",
            ),
        ],
        responses=[],
    )
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="mock-chat",
            )
        },
        providers={"mock": provider},
    )
    path = tmp_path / "opsmind.db"
    app = create_app(
        runtime=OpsAgentRuntime(gateway),
        run_repository=SQLiteRunRepository(path),
        eval_repository=SQLiteEvalRepository(path),
        eval_suite_loader=EvalSuiteLoader(suite_path),
    )
    client = TestClient(app)

    response = client.post("/api/v1/evals/run", json={"suite_id": "api-suite"})

    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle_status"] == "COMPLETED"
    assert body["case_results"][0]["status"] == "PASS"
    job_id = body["eval_job_id"]
    assert client.get("/api/v1/evals").json()[0]["eval_job_id"] == job_id
    detail = client.get(f"/api/v1/evals/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["case_runs"][0]["run_id"]


def test_eval_api_rejects_unknown_suite_without_creating_job(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_id": "api-suite",
                "suite_version": "1.0",
                "description": "API test suite",
                "cases": [
                    {
                        "case_id": "C1",
                        "title": "close",
                        "turns": [{"message": "done"}],
                        "assertions": [
                            {
                                "assertion_id": "action",
                                "type": "final_action_in",
                                "expected": ["END_CONVERSATION"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = MockModelProvider(structured_responses=[], responses=[])
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="mock-chat",
            )
        },
        providers={"mock": provider},
    )
    path = tmp_path / "opsmind.db"
    app = create_app(
        runtime=OpsAgentRuntime(gateway),
        run_repository=SQLiteRunRepository(path),
        eval_suite_loader=EvalSuiteLoader(suite_path),
    )
    client = TestClient(app)

    response = client.post("/api/v1/evals/run", json={"suite_id": "missing"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EVAL_SUITE_INVALID"
    assert client.get("/api/v1/evals").json() == []
