from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import RuleError, assert_can_set_status, latest_peak
from app.models import AshTicket, CookLog, Kettle, User, Workshop
from app.security import make_token, parse_token, verify_password
from app.seed import seed_demo


async def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    username = parse_token(header.split(" ", 1)[1])
    if not username:
        return None
    with get_session() as session:
        return session.exec(select(User).where(User.username == username)).first()


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle).where(Kettle.id == kettle_id).options(selectinload(Kettle.cooks))
    ).first()


def kettle_json(kettle: Kettle) -> dict:
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
    }


def ticket_json(ticket: AshTicket, kettle_code: str = "") -> dict:
    return {
        "id": ticket.id,
        "kettleId": ticket.kettle_id,
        "kettleCode": kettle_code,
        "ticketNo": ticket.ticket_no,
        "cleanedBy": ticket.cleaned_by,
        "cleanedAt": ticket.cleaned_at.isoformat() if ticket.cleaned_at else None,
        "redeemedAt": ticket.redeemed_at.isoformat() if ticket.redeemed_at else None,
    }


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "GlueKettle"})


async def login(request: Request):
    body = await request.json()
    with get_session() as session:
        user = session.exec(select(User).where(User.username == body.get("username", ""))).first()
        if user is None or not verify_password(body.get("password", ""), user.password_hash):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        return JSONResponse(
            {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}
        )


async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return JSONResponse({"username": user.username, "role": user.role})


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop = session.exec(select(Workshop)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {"workshop": shop.name, "alley": shop.alley, "kettles": [kettle_json(k) for k in loaded]}
        )


async def add_cook(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    try:
        peak = float(body.get("peakTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "峰值温度必须是数字"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        has_open_ticket = session.exec(
            select(AshTicket).where(
                AshTicket.kettle_id == kettle.id,
                AshTicket.redeemed_at.is_(None),
            )
        ).first() is not None
        try:
            assert_can_set_status(kettle, body.get("status", ""), has_open_ticket)
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def list_ash_tickets(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_param = request.query_params.get("kettle_id")
    kettle_id = None
    if kettle_param not in (None, ""):
        try:
            kettle_id = int(kettle_param)
        except ValueError:
            return JSONResponse({"detail": "锅号筛选无效"}, status_code=400)
    with get_session() as session:
        stmt = select(AshTicket).where(AshTicket.redeemed_at.is_(None))
        if kettle_id is not None:
            stmt = stmt.where(AshTicket.kettle_id == kettle_id)
        tickets = session.exec(stmt.order_by(AshTicket.kettle_id, AshTicket.id)).all()
        codes = {
            k.id: k.code
            for k in session.exec(select(Kettle)).all()
        }
        return JSONResponse({"tickets": [ticket_json(t, codes.get(t.kettle_id, "")) for t in tickets]})


async def create_ash_ticket(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    raw_no = body.get("ticketNo")
    if isinstance(raw_no, bool) or not isinstance(raw_no, int) or raw_no <= 0:
        return JSONResponse({"detail": "单号必须为正整数"}, status_code=400)
    with get_session() as session:
        kettle = session.exec(select(Kettle).where(Kettle.id == kettle_id)).first()
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        ticket = AshTicket(
            kettle_id=kettle.id,
            ticket_no=raw_no,
            cleaned_by=user.username,
            cleaned_at=datetime.now(timezone.utc),
        )
        session.add(ticket)
        try:
            session.commit()
        except IntegrityError:
            # 两人几乎同时交单：部分唯一索引只放一张进来。
            session.rollback()
            return JSONResponse({"detail": "该锅已有未核销的灶膛清灰单，不能重复开单"}, status_code=400)
        session.refresh(ticket)
        return JSONResponse(ticket_json(ticket, kettle.code), status_code=201)


async def redeem_ash_ticket(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    ticket_id = int(request.path_params["ticket_id"])
    now = datetime.now(timezone.utc)
    with get_session() as session:
        ticket = session.exec(select(AshTicket).where(AshTicket.id == ticket_id)).first()
        if ticket is None:
            return JSONResponse({"detail": "清灰单不存在"}, status_code=404)
        # 条件 UPDATE：并发核销只有一笔能命中未核销行。
        result = session.execute(
            update(AshTicket)
            .where(AshTicket.id == ticket_id, AshTicket.redeemed_at.is_(None))
            .values(redeemed_at=now)
        )
        if result.rowcount == 0:
            session.rollback()
            return JSONResponse({"detail": "该清灰单已核销"}, status_code=400)
        session.commit()
        session.refresh(ticket)
        kettle = session.exec(select(Kettle).where(Kettle.id == ticket.kettle_id)).first()
        return JSONResponse(ticket_json(ticket, kettle.code if kettle else ""))


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/board", board),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
        Route("/api/ash-tickets", list_ash_tickets),
        Route("/api/kettles/{kettle_id:int}/ash-tickets", create_ash_ticket, methods=["POST"]),
        Route("/api/ash-tickets/{ticket_id:int}/redeem", redeem_ash_ticket, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
