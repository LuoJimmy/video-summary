from app.services.httpclient import create_chat_completion, disable_thinking


def test_disable_thinking_always_sets_flag():
    payload = disable_thinking({"model": "deepseek-v4-flash"})
    assert payload["extra_body"]["thinking"] == {"type": "disabled"}


def test_create_chat_completion_retries_without_thinking_when_rejected():
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("extra_body"):
                raise RuntimeError("unknown field thinking")
            return "ok"

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    assert create_chat_completion(FakeClient(), model="deepseek-v4-flash") == "ok"
    assert len(calls) == 2
    assert calls[0]["extra_body"]["thinking"]["type"] == "disabled"
    assert "extra_body" not in calls[1]
