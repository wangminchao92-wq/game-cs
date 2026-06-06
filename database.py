"""Game Customer Service - Database Setup
支持 SQLite（开发环境）和 PostgreSQL（生产环境）双模式。
通过 DATABASE_URL 环境变量切换，为空则使用 SQLite。
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # PostgreSQL / 生产模式
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    # SQLite / 开发模式（默认）
    DB_PATH = os.path.join(os.path.dirname(__file__), "game_cs.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import models
    Base.metadata.create_all(bind=engine)
