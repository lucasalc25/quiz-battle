# models.py
import os
from sqlalchemy import (create_engine, Column, String, Text, Boolean, Integer, CHAR,
                        CheckConstraint)
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import declarative_base
from flask_login import UserMixin

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
        pool_size=int(os.getenv("DB_POOL_SIZE", "5  ")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
        pool_pre_ping=True,
        pool_use_lifo=True,
        future=True,
    )

engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
Base = declarative_base()

THEMES = ('Esportes','TV/Cinema','Jogos','Música','Lógica','História','Diversos')

class User(Base, UserMixin):
    __tablename__ = 'users'
    nickname = Column(String(16), primary_key=True)
    email = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    google_id = Column(String(128), unique=True, nullable=True)
    facebook_id = Column(String(128), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    avatar_url = Column(String(512), nullable=True)
    
    def get_id(self):
        return self.nickname
    
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
