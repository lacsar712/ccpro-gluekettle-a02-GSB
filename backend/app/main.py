from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import RuleError, assert_can_set_status, latest_peak
from app.models import AshTicket, CookLog, Kettle, User, Workshop, utcnow
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
        select(Kettle)
        .where(Kettle.id == kettle_id)
        .options(selectinload(Kettle.cooks), selectinload(Kettle.ash_tickets))
    ).first()


def find_open_ticket(session, kettle_id: int) -> AshTicket | None:
    return session.exec(
        select(AshTicket).where(
            AshTicket.kettle_id == kettle_id,
            AshTicket.redeemed_at.is_(None),
        )
    ).first()


def ticket_json(ticket: AshTicket) -> dict:
    return {
        "id": ticket.id,
        "kettleId": ticket.kettle_id,
        "kettleCode": ticket.kettle.code if ticket.kettle else None,
        "ticketNo": ticket.ticket_no,
        "cleaner": ticket.cleaner,
        "cleanedAt": ticket.cleaned_at.isoformat() if ticket.cleaned_at else None,
        "redeemedAt": ticket.redeemed_at.isoformat() if ticket.redeemed_at else None,
        "redeemedBy": ticket.redeemed_by,
    }


def kettle_json(kettle: Kettle) -> dict:
    open_ticket = next(
        (t for t in (kettle.ash_tickets or []) if t.redeemed_at is None), None
    )
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "openAshTicket": ticket_json(open_ticket) if open_ticket else None,
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
            .options(selectinload(Kettle.cooks), selectinload(Kettle.ash_tickets))
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
        # 冷锅改熬煮中时，读取该锅是否挂着未核销清灰单。
        open_ticket = find_open_ticket(session, kettle_id)
        try:
            assert_can_set_status(
                kettle, body.get("status", ""), open_ash_ticket=open_ticket is not None
            )
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
    stmt = (
        select(AshTicket)
        .where(AshTicket.redeemed_at.is_(None))
        .options(selectinload(AshTicket.kettle))
    )
    raw_filter = request.query_params.get("kettle_id")
    if raw_filter:
        try:
            filter_kettle = int(raw_filter)
        except ValueError:
            return JSONResponse({"detail": "锅号筛选无效"}, status_code=400)
        stmt = stmt.where(AshTicket.kettle_id == filter_kettle)
    with get_session() as session:
        tickets = session.exec(stmt.order_by(AshTicket.cleaned_at.desc(), AshTicket.id.desc())).all()
        return JSONResponse({"tickets": [ticket_json(t) for t in tickets]})


async def create_ash_ticket(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    body = await request.json()
    try:
        kettle_id = int(body.get("kettleId"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "锅号无效"}, status_code=400)
    ticket_no = body.get("ticketNo")
    # 单号须为正整数：拒绝布尔、浮点串、非数字。
    if isinstance(ticket_no, bool) or not isinstance(ticket_no, int) or ticket_no <= 0:
        return JSONResponse({"detail": "单号须为正整数"}, status_code=400)
    cleaner = (body.get("cleaner") or user.username or "").strip() or user.username
    with get_session() as session:
        kettle = session.exec(select(Kettle).where(Kettle.id == kettle_id)).first()
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        if find_open_ticket(session, kettle_id) is not None:
            return JSONResponse({"detail": "该锅已有未核销的灶膛清灰单"}, status_code=409)
        ticket = AshTicket(
            kettle_id=kettle_id, ticket_no=ticket_no, cleaner=cleaner
        )
        session.add(ticket)
        try:
            session.commit()
        except IntegrityError:
            # 并发抢开：部分唯一索引只放行一张。
            session.rollback()
            existing = find_open_ticket(session, kettle_id)
            detail = "该锅已有未核销的灶膛清灰单"
            if existing is not None:
                detail = f"该锅已有未核销清灰单（单号 {existing.ticket_no}）"
            return JSONResponse({"detail": detail}, status_code=409)
        session.refresh(ticket)
        ticket.kettle = kettle
        return JSONResponse(ticket_json(ticket), status_code=201)


async def redeem_ash_ticket(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    ticket_id = int(request.path_params["ticket_id"])
    with get_session() as session:
        ticket = session.get(AshTicket, ticket_id)
        if ticket is None:
            return JSONResponse({"detail": "清灰单不存在"}, status_code=404)
        if ticket.redeemed_at is not None:
            return JSONResponse({"detail": "该清灰单已核销"}, status_code=409)
        ticket.redeemed_at = utcnow()
        ticket.redeemed_by = user.username
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        ticket = session.exec(
            select(AshTicket)
            .where(AshTicket.id == ticket.id)
            .options(selectinload(AshTicket.kettle))
        ).first()
        return JSONResponse(ticket_json(ticket))


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
        Route("/api/ash-tickets", create_ash_ticket, methods=["POST"]),
        Route("/api/ash-tickets/{ticket_id:int}/redeem", redeem_ash_ticket, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
