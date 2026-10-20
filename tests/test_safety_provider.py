"""The safety screen prefers Google Vertex but may fall back, so a Vertex blip never
leaves the screen unavailable; it never lets the provider keep the caller's text."""

import json

import httpx2

from app.safety.service import OpenRouterSafetyClassifier


def test_safety_request_prefers_vertex_with_fallback():
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"verdict":"safe","reason":"no_hazard"}'}}
                ]
            },
        )

    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    OpenRouterSafetyClassifier("k", "google/gemini-3.1-flash-lite", client).classify(
        [{"role": "user", "content": "hi"}], 5
    )
    assert json.loads(seen[0].content)["provider"] == {
        "order": ["google-vertex"],
        "data_collection": "deny",
    }
