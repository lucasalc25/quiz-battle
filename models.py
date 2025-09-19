# models.py
from sqlalchemy import (create_engine, Column, String, Text, Boolean, Integer, CHAR,
                        CheckConstraint, text)
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///quiz.db")

def make_engine(url: str):
    if url.startswith("sqlite"):
        # SQLite: sem pool e liberando thread check
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
            future=True,
        )
    # Postgres (Neon): pool pequeno e pre_ping
    return create_engine(
        url,
        pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
        pool_pre_ping=True,
        future=True,
    )

engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
Base = declarative_base()

THEMES = ('Esportes','TV/Cinema','Jogos','Música','Lógica','História','Diversos')

class User(Base):
    __tablename__ = 'users'
    nickname = Column(Text, primary_key=True)                 
    has_perfect_medal = Column(Boolean, nullable=False, server_default=text("false"))

class Question(Base):
    __tablename__ = 'questions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    theme = Column(Text, nullable=False)
    statement = Column(Text, nullable=False)
    opt_a = Column(Text, nullable=False)
    opt_b = Column(Text, nullable=False)
    opt_c = Column(Text, nullable=False)
    opt_d = Column(Text, nullable=False)
    correct = Column(CHAR(1), nullable=False)
    image_url = Column(Text)
    __table_args__ = (
        CheckConstraint("correct in ('A','B','C','D')", name='ck_correct'),
        CheckConstraint(
            "theme in ('Esportes','TV/Cinema','Jogos','Música','Lógica','História','Diversos')",
            name='ck_theme'
        ),
    )

class Leaderboard(Base):
    __tablename__ = "leaderboard"
    nickname     = Column(String, primary_key=True)
    best_score   = Column(Integer, nullable=False, default=0)
    total_points = Column(Integer, nullable=False, default=0)
    games_played = Column(Integer, nullable=False, default=0)

class Meta(Base):
    __tablename__ = "meta"
    key   = Column(String, primary_key=True)
    value = Column(String, nullable=False)
