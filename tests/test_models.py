"""The hand-written response envelopes in invoist.models must not fall behind openapi.yaml.

The generated models can't drift (``scripts/generate.py`` rewrites them and CI
checks for a diff), but the envelopes the spec writes inline are typed by
hand, so this test checks them: it fails when the spec gains a property
an envelope lacks.
"""

from __future__ import annotations

from typing import Any

import pydantic
import pytest

from invoist import models as m

from .fakes import SPEC


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    if not SPEC.is_file():
        pytest.skip("openapi.yaml is not next to this checkout")
    import yaml

    loaded: dict[str, Any] = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    return loaded


def _response_schema(spec: dict[str, Any], path: str, method: str, status: str) -> dict[str, Any]:
    schema: dict[str, Any] = spec["paths"][path][method]["responses"][status]["content"][
        "application/json"
    ]["schema"]
    return schema


ENVELOPES: list[tuple[type[pydantic.BaseModel], str, str, list[str]]] = [
    (m.ExtractResult, "/v1/extract", "post", ["200", "201"]),
    (m.BatchResult, "/v1/extract/batch", "post", ["200"]),
    (m.DocumentDetail, "/v1/documents/{id}", "get", ["200"]),
    (m.WebhookEndpointList, "/v1/webhook-endpoints", "get", ["200"]),
]


@pytest.mark.parametrize(
    ("model", "path", "method", "statuses"), ENVELOPES, ids=[e[0].__name__ for e in ENVELOPES]
)
def test_envelope_matches_the_spec(
    spec: dict[str, Any],
    model: type[pydantic.BaseModel],
    path: str,
    method: str,
    statuses: list[str],
) -> None:
    fields = model.model_fields
    schemas = [_response_schema(spec, path, method, status) for status in statuses]
    for schema in schemas:
        missing = set(schema["properties"]) - set(fields)
        assert not missing, f"{model.__name__} lacks {sorted(missing)} from {method} {path}"
    # Required in the model only where every response requires it.
    always = set.intersection(*(set(s.get("required", [])) for s in schemas))
    for name, info in fields.items():
        assert info.is_required() == (name in always), f"{model.__name__}.{name}"


@pytest.mark.parametrize(
    ("path", "method", "key"),
    [
        ("/v1/documents", "get", "documents"),
        ("/v1/review-queue", "get", "review_queue"),
        ("/v1/categories", "get", "categories"),
        ("/v1/bills", "get", "bills"),
        ("/v1/held-emails", "get", "held_emails"),
        ("/v1/review-queue/{id}/resolve", "post", "review_queue_item"),
        ("/v1/bills/{id}/paid", "post", "bill"),
        ("/v1/bills/{id}/paid", "delete", "bill"),
    ],
)
def test_unwrapped_keys_are_the_specs(
    spec: dict[str, Any], path: str, method: str, key: str
) -> None:
    schema = _response_schema(spec, path, method, "200")
    assert schema["required"] == [key]


def test_create_webhook_endpoint_unwraps_endpoint(spec: dict[str, Any]) -> None:
    schema = _response_schema(spec, "/v1/webhook-endpoints", "post", "201")
    assert schema["required"] == ["endpoint"]
