# models.py
from sqlalchemy import (create_engine, Column, String, Text, Boolean, Integer, CHAR,
                        CheckConstraint, text)
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///quiz.db")

# Render/Postgres virá como postgres://...  (às vezes sem o +psycopg)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False} if is_sqlite else {}
)
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
