from datetime import datetime, timezone
from typing import ClassVar, Optional

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = "worker"


class Workshop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    alley: str = ""
    kettles: list["Kettle"] = Relationship(back_populates="workshop")


class Kettle(SQLModel, table=True):
    STATUS_COLD: ClassVar[str] = "cold"
    STATUS_BOILING: ClassVar[str] = "boiling"
    STATUS_DRAWN: ClassVar[str] = "drawn"

    id: Optional[int] = Field(default=None, primary_key=True)
    workshop_id: int = Field(foreign_key="workshop.id")
    code: str
    status: str = STATUS_COLD
    bench: int = 0
    workshop: Optional[Workshop] = Relationship(back_populates="kettles")
    cooks: list["CookLog"] = Relationship(back_populates="kettle")
    ash_tickets: list["AshTicket"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")


class AshTicket(SQLModel, table=True):
    """灶膛清灰单。同一锅同时最多挂一张未核销单（见部分唯一索引）。"""

    __tablename__ = "ash_tickets"

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id", index=True)
    ticket_no: int = Field(index=True)
    cleaner: str = ""
    cleaned_at: datetime = Field(default_factory=utcnow)
    redeemed_at: Optional[datetime] = Field(default=None, index=True)
    redeemed_by: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="ash_tickets")

    __table_args__ = (
        Index(
            "uq_ash_open_per_kettle",
            "kettle_id",
            unique=True,
            postgresql_where=text("redeemed_at IS NULL"),
            sqlite_where=text("redeemed_at IS NULL"),
        ),
    )
