from fastapi import APIRouter, Query

from app.schemas import LexiconIn, LexiconOut
from app.services.lexicon import lexicon_payload, reset_user_lexicon, save_user_lexicon

router = APIRouter(prefix="/api/lexicon", tags=["lexicon"])


@router.get("", response_model=LexiconOut)
def get_lexicon(preset: str | None = Query(None, max_length=32)) -> LexiconOut:
    return LexiconOut.model_validate(lexicon_payload(preset))


@router.put("", response_model=LexiconOut)
def put_lexicon(
    payload: LexiconIn,
    preset: str | None = Query(None, max_length=32),
) -> LexiconOut:
    return LexiconOut.model_validate(
        save_user_lexicon(payload.terms, [item.model_dump() for item in payload.fixes], preset)
    )


@router.post("/reset", response_model=LexiconOut)
def reset_lexicon(preset: str | None = Query(None, max_length=32)) -> LexiconOut:
    return LexiconOut.model_validate(reset_user_lexicon(preset))
