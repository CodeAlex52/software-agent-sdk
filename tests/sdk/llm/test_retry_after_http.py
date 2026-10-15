import json
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from pydantic import SecretStr

from openhands.sdk.llm import LLM, Message, TextContent


SUCCESS = {
    "id": "chat-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "ok"},
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}
RATE_LIMITED = {
    "error": {"type": "rate_limit_error", "message": "Rate limit hit", "code": "429"}
}
MESSAGES = [
    Message(role="system", content=[TextContent(text="You are a helpful assistant.")]),
    Message(role="user", content=[TextContent(text="continue")]),
]


@pytest.fixture
def provider():
    replies: deque[tuple[int, dict, dict[str, str]]] = deque()
    request_times: list[float] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            request_times.append(time.monotonic())
            status, body, headers = replies.popleft()
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", replies, request_times
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _llm_without_backoff(base_url: str) -> LLM:
    return LLM(
        model="openai/gpt-4o",
        base_url=base_url,
        api_key=SecretStr("test-key"),
        usage_id="retry-after",
        num_retries=2,
        retry_min_wait=0,
        retry_max_wait=0,
        retry_multiplier=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    "headers",
    [
        {"Retry-After": "1"},
        {"retry-after-ms": "1000"},
        {"llm_provider-retry-after": "1"},
    ],
    ids=["retry-after", "retry-after-ms", "litellm-proxy"],
)
async def test_rate_limit_retry_waits_for_retry_after(provider, headers, use_async):
    base_url, replies, request_times = provider
    replies.extend([(429, RATE_LIMITED, headers), (200, SUCCESS, {})])
    llm = _llm_without_backoff(base_url)

    response = await llm.agenerate(MESSAGES) if use_async else llm.generate(MESSAGES)

    assert response.message.content == [TextContent(text="ok")]
    assert request_times[1] - request_times[0] >= 0.9


def test_rate_limit_retry_ignores_retry_after_beyond_a_minute(provider):
    base_url, replies, request_times = provider
    replies.extend([(429, RATE_LIMITED, {"Retry-After": "3600"}), (200, SUCCESS, {})])

    _llm_without_backoff(base_url).generate(MESSAGES)

    assert request_times[1] - request_times[0] < 0.9
