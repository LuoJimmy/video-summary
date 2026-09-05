import ast
import json
import re
from typing import Any


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


_OVERVIEW_MARKERS = ("一句话总结", "论证结构", "辨立场", "主题与核心观点")
_OPEN_QUOTES = {
    '"': '"',
    "'": "'",
    "\u201c": "\u201d",
    "\u2018": "\u2019",
    "「": "」",
    "『": "』",
    "＂": "＂",
    "＇": "＇",
}


def coerce_model_text(content: Any) -> str:
    """把聊天接口的 content 收成字符串。json_object 模式有时直接返回 dict/list。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item or "content" in item:
                    nested = item.get("text")
                    if nested is None:
                        nested = item.get("content")
                    parts.append(coerce_model_text(nested))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(coerce_model_text(item))
        return "".join(parts).strip()
    return str(content).strip()


def looks_like_json_payload(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.startswith("```"):
        return True
    brace = 0 if raw.startswith("{") else raw.find("{")
    if brace < 0:
        return False
    snippet = raw[brace : brace + 240]
    return any(
        marker in snippet
        for marker in ('"title"', "'title'", '"overview"', '"chapters"', '"key_points"', '"edits"', "title:")
    )


def parse_model_json(text: Any) -> dict:
    """解析模型输出的 JSON，兼容 markdown 围栏、尾部多余文本和被截断的末尾。"""
    if isinstance(text, dict):
        return text
    raw = coerce_model_text(text)
    last_error: Exception | None = None
    for payload in iter_json_payloads(raw):
        try:
            return _loads_object(payload)
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("未找到 JSON 对象", raw, 0)


def _loads_object(payload: str) -> dict:
    leftover = ""
    data = None
    last_error: Exception | None = None
    for candidate in _json_candidates(payload):
        try:
            data, end = json.JSONDecoder().raw_decode(candidate)
            leftover = candidate[end:]
            break
        except json.JSONDecodeError as exc:
            last_error = exc
        try:
            data = json.loads(close_truncated_json(candidate))
            leftover = ""
            break
        except json.JSONDecodeError as exc:
            last_error = exc
        python_data = _python_dict(candidate)
        if python_data is not None:
            data = python_data
            leftover = ""
            break
    if data is None:
        if last_error is not None:
            raise last_error
        raise json.JSONDecodeError("模型输出不是 JSON 对象", payload, 0)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("模型输出不是 JSON 对象", payload, 0)
    if leftover.strip():
        data = merge_trailing_payload(data, leftover)
    return data


def _json_candidates(payload: str) -> list[str]:
    payload = (payload or "").strip().lstrip("\ufeff")
    seen: set[str] = set()
    out: list[str] = []
    quoted = normalize_json_quotes(payload)
    keyed = _quote_unquoted_keys(quoted)
    extras = []
    if payload.startswith("{{"):
        extras.append(payload[1:])
    if quoted.startswith("{{"):
        extras.append(quoted[1:])
    for item in [payload, quoted, keyed, *extras]:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_json_quotes(text: str) -> str:
    """把单引号、中文引号收成 JSON 双引号，不破坏字符串内部的撇号。"""
    out: list[str] = []
    in_string = False
    closer = ""
    escape = False
    for ch in text:
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                continue
            if ch == closer:
                out.append('"')
                in_string = False
                continue
            if ch == '"':
                out.append('\\"')
                continue
            out.append(ch)
            continue
        pair = _OPEN_QUOTES.get(ch)
        if pair is not None:
            in_string = True
            closer = pair
            out.append('"')
            continue
        out.append(ch)
    return "".join(out)


def _quote_unquoted_keys(text: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch in "{,":
            out.append(ch)
            i += 1
            while i < n and text[i] in " \t\r\n":
                out.append(text[i])
                i += 1
            if i < n and text[i] not in "\"'{[":
                start = i
                while i < n and (text[i].isalnum() or text[i] in "_-" or "\u4e00" <= text[i] <= "\u9fff"):
                    i += 1
                key = text[start:i]
                j = i
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if key and j < n and text[j] == ":":
                    out.append('"')
                    out.append(key)
                    out.append('"')
                    continue
                out.append(key)
                continue
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _python_dict(text: str) -> dict | None:
    try:
        data = ast.literal_eval(text)
    except (SyntaxError, ValueError, MemoryError):
        return None
    return data if isinstance(data, dict) else None


def _strip_code_fence(text: str) -> str:
    text = (text or "").strip()
    fence = re.match(r"```(?:json)?\s*", text, flags=re.IGNORECASE)
    if fence:
        text = text[fence.end() :]
        if text.endswith("```"):
            text = text[:-3].strip()
    return text.strip()


def _looks_like_overview_markdown(text: str) -> bool:
    return any(marker in text for marker in _OVERVIEW_MARKERS) or bool(re.search(r"^##\s+", text, flags=re.M))


def _overview_body_is_thin(text: str) -> bool:
    body = re.sub(r"^#{1,4}\s+.*$", "", text or "", flags=re.M)
    body = re.sub(r"[\s|.\-*…·]+", "", body)
    return len(re.findall(r"[\u4e00-\u9fff]", body)) < 40


def merge_trailing_payload(data: dict, leftover: str) -> dict:
    leftover = _strip_code_fence(leftover)
    if not leftover:
        return data
    current = str(data.get("overview") or "").strip()
    if leftover.startswith("{"):
        try:
            extra, _end = json.JSONDecoder().raw_decode(leftover)
        except json.JSONDecodeError:
            extra = None
        if isinstance(extra, dict):
            extra_overview = str(extra.get("overview") or "").strip()
            if extra_overview and (_overview_body_is_thin(current) or len(extra_overview) > len(current)):
                data["overview"] = extra_overview
            extra_title = str(extra.get("title") or "").strip()
            if extra_title and not str(data.get("title") or "").strip():
                data["title"] = extra_title
            return data
    if _looks_like_overview_markdown(leftover) and (
        _overview_body_is_thin(current) or len(leftover) > len(current)
    ):
        data["overview"] = leftover
    return data


def extract_json_object(text: str) -> str:
    for payload in iter_json_payloads(text):
        return payload
    raise json.JSONDecodeError("未找到 JSON 对象", text or "", 0)


def iter_json_payloads(text: str):
    text = (text or "").strip()
    fence = re.match(r"```(?:json)?\s*", text, flags=re.IGNORECASE)
    if fence:
        text = text[fence.end():]
        if text.endswith("```"):
            text = text[:-3].strip()
    if "\uff5b" in text:
        text = text.replace("\uff5b", "{").replace("\uff5d", "}")
    start = 0
    while True:
        brace = text.find("{", start)
        if brace < 0:
            return
        yield text[brace:].strip()
        start = brace + 1


def close_truncated_json(text: str) -> str:
    in_string = False
    escape = False
    stack: list[str] = []
    for ch in text:
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    if escape:
        text = text[:-1]
        in_string = True
    if in_string:
        text += '"'
    text = text.rstrip()
    while text.endswith(","):
        text = text[:-1].rstrip()
    closers = {"{": "}", "[": "]"}
    for opener in reversed(stack):
        text += closers[opener]
    return text
