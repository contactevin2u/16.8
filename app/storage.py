
from sqlalchemy import create_engine, String, Float, DateTime
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, sessionmaker
import os
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
class Base(DeclarativeBase): pass
class Order(Base):
    __tablename__ = "orders"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=False))
class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(64))
    amount: Mapped[float] = mapped_column(Float)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=False))
class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(64))
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=False))
def init_db(): Base.metadata.create_all(engine)
