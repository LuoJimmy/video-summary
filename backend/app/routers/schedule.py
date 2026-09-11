from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ScheduleIn, ScheduleLogOut, ScheduleOut
from app.services.schedule import clear_logs, list_logs, load_schedule, run_once, save_schedule, start_detached_run

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("", response_model=ScheduleOut)
def get_schedule(db: Session = Depends(get_db)) -> ScheduleOut:
    return load_schedule(db)


@router.put("", response_model=ScheduleOut)
def put_schedule(payload: ScheduleIn, db: Session = Depends(get_db)) -> ScheduleOut:
    try:
        return save_schedule(db, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/run", response_model=ScheduleLogOut)
def run_schedule(wait: bool = Query(True), db: Session = Depends(get_db)) -> ScheduleLogOut:
    if wait:
        return run_once("manual", db=db)
    try:
        return start_detached_run("manual")
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/logs", response_model=list[ScheduleLogOut])
def get_schedule_logs(limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)) -> list[ScheduleLogOut]:
    return list_logs(db, limit=limit)


@router.delete("/logs")
def delete_schedule_logs(db: Session = Depends(get_db)) -> dict:
    return clear_logs(db)
