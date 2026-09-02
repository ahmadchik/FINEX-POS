from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .ai import service
from .ai.service import AiUnavailable
from .db import get_db
from .deps import get_current_user
from .models import User
from .security import rate_limit
from .config import settings

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    context: dict | None = None


class ReportIn(BaseModel):
    question: str = ""
    answer: str = ""
    context: dict | None = None


@router.get("/status")
def ai_status(user: User = Depends(get_current_user)):
    _ = user
    return service.provider_status()


@router.post("/chat")
def ai_chat(body: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        rate_limit(f"ai:{user.id}", limit=settings.ai_rate_limit, window=settings.ai_rate_window)
    try:
        return service.chat(db, user, body.message, body.context)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AiUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/history")
def ai_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.history_payload(db, user)


@router.delete("/history")
def ai_history_clear(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.clear_history(db, user)
    return {"ok": True}


@router.post("/report")
def ai_report(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.report_problem(db, user, body.model_dump())
