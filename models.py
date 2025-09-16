# models.py
from sqlalchemy import (create_engine, Column, Text, Boolean, Integer, CHAR,
                        CheckConstraint, text)
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
import os

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # fallback local
    DATABASE_URL = "sqlite:///quiz.db"

def make_engine(url: str):
    if url.startswith("sqlite"):
        # Ambiente local simples
        return create_engine(
            url,
            connect_args={"check_same_thread": False}
        )
    else:
        # Postgres (Neon)
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_timeout=30,
            pool_recycle=1800, 
        )

engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

THEMES = ('Esportes','TV/Cinema','Jogos','Música','Lógica','História','Diversos')

class User(Base):
    __tablename__ = 'users'
    nickname = Column(Text, primary_key=True)                  # UNIQUE implícito
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
    __tablename__ = 'leaderboard'
    nickname = Column(Text, primary_key=True)
    best_score = Column(Integer, nullable=False, server_default=text("0"))
