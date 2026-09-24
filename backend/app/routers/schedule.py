from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ScheduleLogOut, ScheduleRuleIn, ScheduleRuleOut, ScheduleRuleSiteOut
from app.services.schedule import (
    clear_logs,
    delete_rule,
    enabled_rule_ids,
    list_logs,
    list_rules,
    list_schedule_sites,
    run_once,
    save_rule,
    start_detached_run,
)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("/rules", response_model=list[ScheduleRuleOut])
def get_schedule_rules(db: Session = Depends(get_db)) -> list[ScheduleRuleOut]:
    return list_rules(db)


@router.get("/sites", response_model=list[ScheduleRuleSiteOut])
def get_schedule_sites(db: Session = Depends(get_db)) -> list[ScheduleRuleSiteOut]:
    return list_schedule_sites(db)


@router.post("/rules", response_model=ScheduleRuleOut)
def create_schedule_rule(payload: ScheduleRuleIn, db: Session = Depends(get_db)) -> ScheduleRuleOut:
    try:
        return save_rule(db, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.put("/rules/{rule_id}", response_model=ScheduleRuleOut)
def update_schedule_rule(rule_id: str, payload: ScheduleRuleIn, db: Session = Depends(get_db)) -> ScheduleRuleOut:
    try:
        return save_rule(db, payload, rule_id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.delete("/rules/{rule_id}")
def delete_schedule_rule(rule_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return delete_rule(db, rule_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/rules/{rule_id}/run", response_model=ScheduleLogOut)
def run_schedule_rule(
    rule_id: str,
    wait: bool = Query(True),
    db: Session = Depends(get_db),
) -> ScheduleLogOut:
    if wait:
        try:
            return run_once("manual", db=db, rule_id=rule_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
    try:
        return start_detached_run("manual", rule_id)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/run", response_model=ScheduleLogOut)
def run_schedule(wait: bool = Query(True), db: Session = Depends(get_db)) -> ScheduleLogOut:
    """立即执行：把当前所有启用的定时配置都扫一轮。"""
    if wait:
        last: ScheduleLogOut | None = None
        for rule_id in enabled_rule_ids(db):
            last = run_once("manual", db=db, rule_id=rule_id)
        if last is None:
            raise HTTPException(400, "还没有启用的定时配置")
        return last
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
