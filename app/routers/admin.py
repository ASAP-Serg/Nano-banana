"""
Админ-роутер: управление пользователями, обзор генераций и метрики.
"""

from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_

from app.models.base import Generation, User
from app.models.token import TokenPayload
from app.services.AuthService import auth_service
from app.services.DBService import db_service

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: TokenPayload):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ только для админов")


def _infer_provider(gen: Generation) -> str:
    metadata = gen.generation_metadata or {}
    provider = (metadata.get("provider") or "").strip().lower()
    if provider in ("replicate", "bananalab"):
        return provider
    model_name = (gen.model_name or "").lower()
    if model_name.startswith("imagen") or "gemini" in model_name:
        return "replicate"
    if "nano-banana" in model_name:
        return "hybrid"
    return "unknown"


def _estimate_cost_usd(gen: Generation) -> float:
    model = (gen.model_name or "nano-banana-pro").lower()
    resolution = (gen.resolution or "1K").upper()
    metadata = gen.generation_metadata or {}

    model_price = {
        "nano-banana": 0.015,
        "nano-banana-2": 0.02,
        "nano-banana-pro": 0.03,
        "gemini-2.5-flash-image": 0.02,
        "imagen-4": 0.04,
        "imagen-4-fast": 0.02,
        "imagen-4-ultra": 0.06,
    }.get(model, 0.02)
    resolution_multiplier = {"1K": 1.0, "2K": 1.6, "4K": 2.5}.get(resolution, 1.0)
    refs_count = int(metadata.get("reference_images_count") or 0)
    refs_fee = min(refs_count, 14) * 0.002
    return round(model_price * resolution_multiplier + refs_fee, 6)


@router.get("/users")
async def admin_list_users(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    with db_service.get_session() as session:
        query = session.query(User)
        if search:
            needle = f"%{search.strip()}%"
            query = query.filter(or_(User.username.ilike(needle), User.email.ilike(needle)))
        total = query.count()
        rows = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "is_admin": bool(u.is_admin),
                    "is_active": bool(u.is_active),
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_login": u.last_login.isoformat() if u.last_login else None,
                }
                for u in rows
            ],
            "meta": {"total": total, "limit": limit, "offset": offset},
        }


@router.post("/users/{target_user_id}/grant-admin")
async def admin_grant_role(
    target_user_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    _require_admin(user)
    with db_service.get_session() as session:
        target = session.query(User).filter(User.id == target_user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        target.is_admin = True
        session.commit()
        return {"message": f"Пользователь {target.username} назначен админом"}


@router.post("/users/{target_user_id}/revoke-admin")
async def admin_revoke_role(
    target_user_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    _require_admin(user)
    with db_service.get_session() as session:
        target = session.query(User).filter(User.id == target_user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        if target.id == user.user_id:
            raise HTTPException(status_code=400, detail="Нельзя снять права у самого себя")

        admins_count = session.query(User).filter(User.is_admin.is_(True)).count()
        if admins_count <= 1 and target.is_admin:
            raise HTTPException(status_code=400, detail="Нельзя снять права у последнего админа")

        target.is_admin = False
        session.commit()
        return {"message": f"Права админа сняты у пользователя {target.username}"}


@router.get("/generations")
async def admin_list_generations(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    user_id: Optional[int] = None,
    status: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    search: Optional[str] = None,
    error_only: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    with db_service.get_session() as session:
        query = session.query(Generation)
        if user_id is not None:
            query = query.filter(Generation.user_id == user_id)
        if status:
            query = query.filter(Generation.status == status)
        if model:
            query = query.filter(Generation.model_name == model)
        if search:
            needle = f"%{search.strip()}%"
            query = query.filter(Generation.prompt.ilike(needle))
        if error_only:
            query = query.filter(Generation.status == "failed")
        if date_from:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(Generation.created_at >= dt_from)
        if date_to:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(Generation.created_at <= dt_to)

        rows = query.order_by(Generation.created_at.desc()).offset(offset).limit(limit).all()
        total = query.count()

        payload = []
        for gen in rows:
            inferred_provider = _infer_provider(gen)
            if provider and inferred_provider != provider:
                continue
            metadata = gen.generation_metadata or {}
            payload.append(
                {
                    "id": gen.id,
                    "user_id": gen.user_id,
                    "prompt": gen.prompt,
                    "status": gen.status,
                    "model_name": gen.model_name,
                    "resolution": gen.resolution,
                    "result_url": gen.result_url,
                    "error": metadata.get("error"),
                    "created_at": gen.created_at.isoformat() if gen.created_at else None,
                    "provider": inferred_provider,
                }
            )

        return {"generations": payload, "meta": {"total": total, "limit": limit, "offset": offset}}


@router.get("/overview")
async def admin_overview(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    period_days: int = Query(30, ge=1, le=365),
):
    _require_admin(user)
    cutoff = datetime.utcnow() - timedelta(days=period_days)

    with db_service.get_session() as session:
        users_total = session.query(User).count()
        active_users = (
            session.query(User)
            .filter(User.last_login.isnot(None))
            .filter(User.last_login >= cutoff)
            .count()
        )

        gens = session.query(Generation).filter(Generation.created_at >= cutoff).all()
        generations_total = len(gens)
        failed_total = sum(1 for g in gens if g.status == "failed")
        completed_total = sum(1 for g in gens if g.status == "completed")
        running_total = sum(1 for g in gens if g.status in ("pending", "running", "paused"))

        spend_by_user = {}
        for g in gens:
            amount = 0.0
            source = "estimated"
            metadata = g.generation_metadata or {}
            if metadata.get("provider_cost_usd") is not None:
                amount = float(metadata.get("provider_cost_usd") or 0)
                source = "fact"
            elif g.status in ("completed", "failed"):
                amount = _estimate_cost_usd(g)
            if g.user_id not in spend_by_user:
                spend_by_user[g.user_id] = {"amount": 0.0, "fact": 0, "estimated": 0}
            spend_by_user[g.user_id]["amount"] += amount
            spend_by_user[g.user_id][source] += 1

        top_users = []
        if spend_by_user:
            users = session.query(User).filter(User.id.in_(list(spend_by_user.keys()))).all()
            users_map = {u.id: u for u in users}
            for uid, spend in spend_by_user.items():
                u = users_map.get(uid)
                top_users.append(
                    {
                        "user_id": uid,
                        "username": u.username if u else f"user-{uid}",
                        "email": u.email if u else None,
                        "amount_usd": round(spend["amount"], 4),
                        "fact_points": spend["fact"],
                        "estimated_points": spend["estimated"],
                    }
                )
            top_users.sort(key=lambda x: x["amount_usd"], reverse=True)
            top_users = top_users[:20]

        total_spend = round(sum(v["amount"] for v in spend_by_user.values()), 4)

        return {
            "period_days": period_days,
            "users_total": users_total,
            "active_users": active_users,
            "generations_total": generations_total,
            "completed_total": completed_total,
            "failed_total": failed_total,
            "running_total": running_total,
            "spend_total_usd": total_spend,
            "spend_source": "hybrid",
            "top_users": top_users,
        }

