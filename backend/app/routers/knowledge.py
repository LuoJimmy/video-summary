from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job
from app.schemas import (
    KnowledgeChatIn,
    KnowledgeChatOut,
    KnowledgeConversationListOut,
    KnowledgeConversationOut,
    KnowledgeConversationRenameIn,
    KnowledgeSearchOut,
)
from app.services.knowledge import (
    KnowledgeError,
    answer_from_knowledge,
    jobs_in_domain,
    knowledge_content_filter,
    knowledge_jobs_filter,
    search_knowledge,
)
from app.services.knowledge_history import (
    delete_conversation,
    get_conversation,
    list_conversations,
    rename_conversation,
    save_conversation,
)
from app.services.settings_store import load_settings

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _jobs(db: Session) -> list[Job]:
    return knowledge_content_filter(db.query(Job)).order_by(Job.updated_at.desc()).all()


def _listed_jobs_query(db: Session, domain_id: str):
    return knowledge_jobs_filter(knowledge_content_filter(db.query(Job)), domain_id)


@router.get("", response_model=KnowledgeSearchOut)
def knowledge(
    q: str = Query("", max_length=80),
    domain_id: str = Query("a-share", max_length=32),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> KnowledgeSearchOut:
    if not q.strip():
        total = _listed_jobs_query(db, domain_id).with_entities(func.count(Job.id)).scalar() or 0
        rows = (
            _listed_jobs_query(db, domain_id)
            .order_by(Job.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return search_knowledge(rows, "", page=page, page_size=page_size, total=total)
    return search_knowledge(jobs_in_domain(_jobs(db), domain_id), q, page=page, page_size=page_size)


@router.get("/conversations", response_model=KnowledgeConversationListOut)
def knowledge_conversations(
    q: str = Query("", max_length=80),
    domain_id: str = Query("a-share", max_length=32),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> KnowledgeConversationListOut:
    return list_conversations(db, domain_id, q=q, page=page, page_size=page_size)


@router.get("/conversations/{conversation_id}", response_model=KnowledgeConversationOut)
def knowledge_conversation(conversation_id: str, db: Session = Depends(get_db)) -> KnowledgeConversationOut:
    row = get_conversation(db, conversation_id)
    if row is None:
        raise HTTPException(404, "对话不存在")
    return row


@router.patch("/conversations/{conversation_id}", response_model=KnowledgeConversationOut)
def knowledge_conversation_rename(
    conversation_id: str,
    payload: KnowledgeConversationRenameIn,
    db: Session = Depends(get_db),
) -> KnowledgeConversationOut:
    try:
        row = rename_conversation(db, conversation_id, payload.title)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "对话不存在")
    return row


@router.delete("/conversations/{conversation_id}")
def knowledge_conversation_delete(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    if not delete_conversation(db, conversation_id):
        raise HTTPException(404, "对话不存在")
    return {"ok": True}


@router.post("/chat", response_model=KnowledgeChatOut)
def knowledge_chat(payload: KnowledgeChatIn, db: Session = Depends(get_db)) -> KnowledgeChatOut:
    try:
        answer, citations = answer_from_knowledge(
            _jobs(db),
            [item.model_dump() for item in payload.messages],
            load_settings(db),
            domain_id=payload.domain_id,
        )
    except KnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    stored = [item.model_dump() for item in payload.messages]
    stored.append({"role": "assistant", "content": answer, "citations": [item.model_dump() for item in citations]})
    conversation = save_conversation(db, payload.conversation_id, payload.domain_id, stored)
    return KnowledgeChatOut(
        answer=answer,
        citations=citations,
        conversation_id=conversation.id,
        title=conversation.title,
    )
