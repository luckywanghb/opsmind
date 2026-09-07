"""Load and validate the backend-owned Golden Suite artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from opsmind.evals.models import EvalSuite, _validate_json_depth

DEFAULT_SUITE_PATH = Path(__file__).resolve().parents[3] / "evals" / "golden-v0.3.json"
MAX_SUITE_FILE_BYTES = 512 * 1_024


class EvalSuiteLoadError(ValueError):
    """Raised when a Golden Suite is absent, malformed, or unsupported."""

    code = "EVAL_SUITE_INVALID"


class EvalSuiteLoader:
    """Strict JSON-to-Pydantic loader with evaluator-integrity checks."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        evaluator_registry: Any | None = None,
    ) -> None:
        self._path = Path(path) if path is not None else DEFAULT_SUITE_PATH
        self._evaluator_registry = evaluator_registry

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> EvalSuite:
        """Read, parse, type-check, and integrity-check one suite."""

        try:
            size = self._path.stat().st_size
            if size > MAX_SUITE_FILE_BYTES:
                raise EvalSuiteLoadError("eval suite file is too large")
            raw = self._path.read_text(encoding="utf-8")
        except EvalSuiteLoadError:
            raise
        except (OSError, UnicodeError) as exc:
            raise EvalSuiteLoadError("eval suite file is unavailable") from exc
        return self.loads(raw)

    def loads(self, content: str) -> EvalSuite:
        """Parse a JSON string using the same path as file loading."""

        if not isinstance(content, str):
            raise EvalSuiteLoadError("eval suite content is not text")
        if len(content.encode("utf-8")) > MAX_SUITE_FILE_BYTES:
            raise EvalSuiteLoadError("eval suite content is too large")
        try:
            decoded = json.loads(content)
        except (json.JSONDecodeError, TypeError, UnicodeError, RecursionError) as exc:
            raise EvalSuiteLoadError("eval suite JSON is malformed") from exc
        if not isinstance(decoded, dict):
            raise EvalSuiteLoadError("eval suite root must be an object")
        try:
            _validate_json_depth(decoded)
        except (RecursionError, TypeError, ValueError) as exc:
            raise EvalSuiteLoadError("eval suite JSON is outside safe bounds") from exc
        try:
            suite = EvalSuite.model_validate(decoded)
        except (ValidationError, RecursionError, TypeError, ValueError) as exc:
            raise EvalSuiteLoadError("eval suite schema is invalid") from exc
        registry = self._evaluator_registry
        if registry is None:
            from opsmind.evals.evaluators import EvaluatorRegistry

            registry = EvaluatorRegistry()
        unknown = sorted(
            {
                assertion.type
                for case in suite.cases
                for assertion in case.assertions
                if not registry.supports(assertion.type)
            }
        )
        if unknown:
            raise EvalSuiteLoadError("eval suite contains an unknown evaluator")
        validator = getattr(registry, "validate_assertion", None)
        if callable(validator):
            try:
                for case in suite.cases:
                    for assertion in case.assertions:
                        if (
                            assertion.turn_index is not None
                            and assertion.turn_index >= len(case.turns)
                        ):
                            raise ValueError(
                                "assertion turn index is outside the case turns"
                            )
                        validator(assertion, turn_count=len(case.turns))
            except (TypeError, ValueError, RecursionError) as exc:
                raise EvalSuiteLoadError(
                    "eval suite contains an invalid evaluator expectation"
                ) from exc
        else:
            for case in suite.cases:
                for assertion in case.assertions:
                    if (
                        assertion.turn_index is not None
                        and assertion.turn_index >= len(case.turns)
                    ):
                        raise EvalSuiteLoadError(
                            "eval suite contains an invalid evaluator expectation"
                        )
        return suite


__all__ = [
    "DEFAULT_SUITE_PATH",
    "EvalSuiteLoadError",
    "EvalSuiteLoader",
    "MAX_SUITE_FILE_BYTES",
]
