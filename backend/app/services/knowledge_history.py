from pydantic import ValidationError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import KnowledgeConversation, utcnow
from app.schemas import (
    KnowledgeChatMessage,
    KnowledgeConversationListOut,
    KnowledgeConversationOut,
    KnowledgeConversationSummary,
    KnowledgeHit,
)
from app.services.domain import stored_job_domain
from app.services.jsonutil import dumps, loads

TITLE_MAX = 40
PREVIEW_MAX = 48


def conversation_title(messages: list[dict]) -> str:
    for item in messages:
        if item.get("role") != "user":
            continue
        text = " ".join(str(item.get("content") or "").split())
        if not text:
            continue
        if len(text) > TITLE_MAX:
            return text[:TITLE_MAX].rstrip() + "…"
        return text
    return "未命名对话"


def normalize_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in messages:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        row: dict = {"role": role, "content": content}
        if role == "assistant":
            cites = _citation_dicts(item.get("citations") or [])
            if cites:
                row["citations"] = cites
        out.append(row)
    return out


def parse_messages(raw: str) -> list[KnowledgeChatMessage]:
    items = loads(raw, [])
    if not isinstance(items, list):
        return []
    out: list[KnowledgeChatMessage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role not in {"user", "assistant"} or not content.strip():
            continue
        cites: list[KnowledgeHit] = []
        for hit in item.get("citations") or []:
            try:
                cites.append(KnowledgeHit.model_validate(hit))
            except (TypeError, ValueError, ValidationError):
                continue
        out.append(KnowledgeChatMessage(role=role, content=content, citations=cites))
    return out


def list_conversations(
    db: Session,
    domain_id: str | None,
    q: str = "",
    page: int = 1,
    page_size: int = 30,
) -> KnowledgeConversationListOut:
    query = db.query(KnowledgeConversation).filter(KnowledgeConversation.domain_id == stored_job_domain(domain_id))
    keyword = (q or "").strip()
    if keyword:
        pattern = _like_pattern(keyword)
        query = query.filter(
            or_(
                KnowledgeConversation.title.like(pattern, escape="\\"),
                KnowledgeConversation.messages_json.like(pattern, escape="\\"),
            )
        )
    total = query.count()
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    rows = (
        query.order_by(KnowledgeConversation.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return KnowledgeConversationListOut(
        items=[_summary(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_conversation(db: Session, conversation_id: str) -> KnowledgeConversationOut | None:
    row = db.get(KnowledgeConversation, conversation_id)
    if row is None:
        return None
    return _detail(row)


def save_conversation(
    db: Session,
    conversation_id: str,
    domain_id: str | None,
    messages: list[dict],
) -> KnowledgeConversationOut:
    normalized = normalize_messages(messages)
    target = stored_job_domain(domain_id)
    row = db.get(KnowledgeConversation, conversation_id) if conversation_id else None
    if row is None or stored_job_domain(row.domain_id) != target:
        row = KnowledgeConversation(domain_id=target)
        db.add(row)
    row.messages_json = dumps(normalized)
    if not (row.title or "").strip():
        row.title = conversation_title(normalized)
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _detail(row)


def delete_conversation(db: Session, conversation_id: str) -> bool:
    row = db.get(KnowledgeConversation, conversation_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def rename_conversation(db: Session, conversation_id: str, title: str) -> KnowledgeConversationOut | None:
    row = db.get(KnowledgeConversation, conversation_id)
    if row is None:
        return None
    cleaned = " ".join((title or "").split())
    if not cleaned:
        raise ValueError("标题不能为空")
    row.title = cleaned[:255]
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _detail(row)


def _summary(row: KnowledgeConversation) -> KnowledgeConversationSummary:
    messages = parse_messages(row.messages_json)
    return KnowledgeConversationSummary(
        id=row.id,
        domain_id=row.domain_id,
        title=row.title or "未命名对话",
        preview=_preview(messages),
        updated_at=row.updated_at,
        created_at=row.created_at,
        message_count=len(messages),
    )


def _detail(row: KnowledgeConversation) -> KnowledgeConversationOut:
    summary = _summary(row)
    return KnowledgeConversationOut(
        **summary.model_dump(),
        messages=parse_messages(row.messages_json),
    )


def _preview(messages: list[KnowledgeChatMessage]) -> str:
    for item in reversed(messages):
        text = " ".join(item.content.split())
        if text:
            if len(text) > PREVIEW_MAX:
                return text[:PREVIEW_MAX].rstrip() + "…"
            return text
    return ""


def _like_pattern(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _citation_dicts(citations: list) -> list[dict]:
    out: list[dict] = []
    for item in citations:
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif isinstance(item, dict):
            data = item
        else:
            continue
        try:
            out.append(KnowledgeHit.model_validate(data).model_dump())
        except (TypeError, ValueError, ValidationError):
            continue
    return out
