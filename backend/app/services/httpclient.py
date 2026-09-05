import httpx
from openai import OpenAI


def http_client(**kwargs) -> httpx.Client:
    # 本机 Python / 代理环境经常缺中间证书，严格校验会拦掉站点跳转和模型接口
    kwargs.setdefault("verify", False)
    kwargs.setdefault("timeout", 20.0)
    return httpx.Client(**kwargs)


def openai_client(api_key: str, base_url: str | None = None, timeout: float = 120.0) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url or None,
        http_client=http_client(timeout=timeout),
    )


def disable_thinking(kwargs: dict) -> dict:
    payload = dict(kwargs)
    extra = dict(payload.get("extra_body") or {})
    extra["thinking"] = {"type": "disabled"}
    payload["extra_body"] = extra
    return payload


def create_chat_completion(client: OpenAI, **kwargs):
    """聊天调用一律关掉 thinking；接口不认该字段时再退回原参数。"""
    payload = disable_thinking(kwargs)
    try:
        return client.chat.completions.create(**payload)
    except Exception as exc:
        message = str(exc).lower()
        if "thinking" not in message and "extra_body" not in message:
            raise
        return client.chat.completions.create(**kwargs)
