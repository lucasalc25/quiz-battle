# app.py
import random, os
import secrets
from flask import Flask, render_template, request, redirect, url_for, session
from sqlalchemy import select, text, func
from models import SessionLocal, User, Question, Leaderboard, THEMES, Base, engine
from contextlib import contextmanager
from models import Meta
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta

TZ = ZoneInfo("America/Manaus")

def next_monday_midnight(dt: datetime | None = None) -> datetime:
    now = dt or datetime.now(TZ)
    days_ahead = (7 - now.weekday()) % 7
    # se já é segunda depois da meia-noite, vai para a próxima segunda
    if days_ahead == 0 and now.time() >= time(0, 0):
        days_ahead = 7
    target_date = (now + timedelta(days=days_ahead)).date()
    return datetime.combine(target_date, time(0, 0), tzinfo=TZ)

def _maybe_reset_week(db):
    now = datetime.now(TZ)
    iso_year, iso_week, _ = now.isocalendar()
    cur = f"{iso_year}-W{iso_week:02d}"

    meta = db.get(Meta, "last_reset_week")
    if not meta or meta.value != cur:
        # zera acumulado semanal; preserva best_score
        db.execute(text("UPDATE leaderboard SET total_points = 0, games_played = 0"))
        if meta:
            meta.value = cur
        else:
            db.add(Meta(key="last_reset_week", value=cur))


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "28a08c230e257781ef22b1d7be9758a0")

Base.metadata.create_all(engine)

THEMES = ["Esportes", "TV/Cinema", "Jogos", "Música", "Lógica", "História", "Diversos"]

@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@contextmanager
def db_readonly():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.after_request
def no_cache(resp):
    if request.path in ("/game", "/answer", "/continue"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

def _next_qid_from_queue():
    # respeita pergunta corrente
    current = session.get("current_qid")
    if current:
        return current

    queue = session.get("queue_ids") or []
    asked = set(session.get("asked_ids") or [])

    # pega o primeiro ainda não perguntado
    for cand in queue:
        if cand not in asked:
            session["current_qid"] = cand
            session["current_token"] = secrets.token_urlsafe(16)
            return cand
    return None

def _load_ranking(db):
    res = db.execute(
    select(
        Leaderboard.nickname,
        Leaderboard.best_score,
        Leaderboard.total_points,
        Leaderboard.games_played
    ).order_by(
        Leaderboard.best_score.desc(),
        Leaderboard.nickname.asc()
    )
    ).all()
    return [
        {
            "nickname": n,
            "best_score": b or 0,
            "total_points": t or 0,
            "games_played": g or 0,
        }
        for (n, b, t, g) in res
    ]

def _find_position(rows, nickname):
    for i, r in enumerate(rows, start=1):
        if r["nickname"] == nickname:
            return i
    return None

@app.get("/")
def home():
    return render_template("home.html", body_class="home")

@app.post("/start")
def start():
    nickname = (request.form.get("nickname") or "").strip()
    if not nickname:
        return redirect(url_for("home"))

    with db_session() as db:
        user = db.get(User, nickname)
        if not user:
            db.add(User(nickname=nickname))

    theme = random.choice(THEMES)

    # Carrega todos os IDs do tema e embaralha
    with db_readonly() as db:
        ids = [row[0] for row in db.query(Question.id).filter(Question.theme == theme).all()]
    random.shuffle(ids)

    # Estado inicial da partida
    session.update(
        nickname=nickname,
        theme=theme,
        asked_ids=[],
        score=0,
        queue_ids=ids,
    )

    # LIMPE estados de rodada/pergunta
    for k in ("roulette_shown", "current_qid", "current_token", "ended", "feedback_state"):
        session.pop(k, None)

    return redirect(url_for("game"))

@app.get("/game")
def game():
    nickname = session.get("nickname")
    theme    = session.get("theme")
    asked_ids = session.get("asked_ids") or []
    if not nickname or not theme:
        return redirect(url_for("home"))

    # MOSTRAR ROLETA só na primeira pergunta
    show_roulette = (len(asked_ids) == 0 and not session.get("roulette_shown"))
    if show_roulette:
        session["roulette_shown"] = True

    # ----- MODO FEEDBACK (após POST/redirect) -----
    if request.args.get("fb") == "1":
        fb = session.get("feedback_state")
        if fb:
            with db_readonly() as db:
                q = db.get(Question, fb["qid"])
            score = len(asked_ids)
            session.pop("feedback_state", None)
            return render_template(
                "game.html",
                q=q,
                theme=theme,
                score=score,
                feedback=True,
                was_correct=fb["was_correct"],
                timed_out=fb["timed_out"],
                picked=fb["picked"],
                correct=fb["correct"],
                themes=THEMES,
                show_roulette=False,
                body_class="game",
                title="Jogo",
                qtoken=session.get("current_token"),
            )
        # sem fb → cai no modo pergunta normal

    # ----- MODO PERGUNTA NORMAL -----
    qid = _next_qid_from_queue()
    if qid is None:
        return redirect(url_for("end", reason="completou"))

    with db_readonly() as db:
        q = db.get(Question, qid)
    if not q:
        # (raro) se id “órfão”, tenta novamente
        return redirect(url_for("game"))

    return render_template(
        "game.html",
        q=q,
        theme=theme,
        score=len(asked_ids),
        feedback=False,
        themes=THEMES,
        show_roulette=show_roulette,
        body_class="game",
        title="Jogo",
        qtoken=session.get("current_token"),
    )

@app.post("/answer")
def answer():
    picked   = (request.form.get("picked") or "").upper()
    correct  = (request.form.get("correct") or "").upper()
    qid_str  = request.form.get("qid")
    qtoken   = request.form.get("qtoken")

    # valida qid
    try:
        qid = int(qid_str)
    except Exception:
        return redirect(url_for("game"))

    # valida instância (qid + token)
    current_qid   = session.get("current_qid")
    current_token = session.get("current_token")
    if not current_qid or not current_token or qid != current_qid or qtoken != current_token:
        # tentativa de reuso/volta → reabre jogo (não processa)
        return redirect(url_for("game"))

    timed_out   = (picked == "TIMEOUT")
    was_correct = (picked == correct) and not timed_out

    # CONSUME a pergunta (remove da fila) e limpa instância
    queue = session.get("queue_ids") or []
    try:
        queue.remove(qid)
    except ValueError:
        pass
    session["queue_ids"] = queue
    session["current_qid"] = None
    session["current_token"] = None

    asked = session.get("asked_ids") or []
    if was_correct and (qid not in asked):
        asked.append(qid)
        session["asked_ids"] = asked

    session["feedback_state"] = {
        "qid": qid,
        "was_correct": bool(was_correct),
        "timed_out": bool(timed_out),
        "picked": picked if picked in ["A","B","C","D"] else None,
        "correct": correct,
    }
    return redirect(url_for("game", fb=1))


@app.post("/continue")
def go_next():
    last = request.form.get("last", "correct")
    if last in ("wrong", "timeout"):
        session["ended"] = True
        return redirect(url_for("end", reason=last))

    asked = session.get("asked_ids") or []
    if len(asked) >= 50:
        session["ended"] = True
        return redirect(url_for("end", reason="completou"))
    return redirect(url_for("game"))


@app.get("/end")
def end():
    reason   = request.args.get("reason", "")
    nickname = session.get("nickname")
    score    = len(session.get("asked_ids") or [])
    if not nickname:
        return redirect(url_for("home"))

    with db_session() as db:
        _maybe_reset_week(db)

        rows_before = _load_ranking(db)  # lista de dicts
        existed     = any(r["nickname"] == nickname for r in rows_before)
        old_pos     = _find_position(rows_before, nickname)

        if score > 0:
            db.execute(text("""
                INSERT INTO leaderboard (nickname, best_score, total_points, games_played)
                VALUES (:nick, :score, :score, 1)
                ON CONFLICT(nickname) DO UPDATE SET
                  best_score = CASE
                      WHEN EXCLUDED.best_score > leaderboard.best_score
                      THEN EXCLUDED.best_score ELSE leaderboard.best_score END,
                  total_points = leaderboard.total_points + EXCLUDED.total_points,
                  games_played = leaderboard.games_played + EXCLUDED.games_played
            """), {"nick": nickname, "score": score})

            if score >= 50:
                u = db.get(User, nickname)
                if u:
                    u.has_perfect_medal = True

        if score == 0:
            # LIMPA estado da rodada ANTES de retornar
            for k in ("asked_ids","current_qid","current_token","ended","roulette_shown","feedback_state"):
                session.pop(k, None)

            return render_template("end.html",
                                   score=score, perfect=False, reason=reason,
                                   title="Fim da partida", body_class="end")

        rows_after = _load_ranking(db)
        new_pos    = _find_position(rows_after, nickname)

    # LIMPA estado da rodada antes dos returns seguintes
    for k in ("asked_ids","current_qid","current_token","ended","roulette_shown","feedback_state"):
        session.pop(k, None)

    if not existed:
        return render_template("leaderboard.html",
                               rows=rows_after[:50],
                               just_added=nickname,
                               body_class="rank", title="Ranking")

    moved_up = (old_pos is not None and new_pos is not None and new_pos < old_pos)
    if moved_up:
        return render_template("leaderboard.html",
                               rows=rows_after[:50],
                               promoted_nick=nickname,
                               positions_up=(old_pos - new_pos),
                               new_rank=new_pos,
                               body_class="rank", title="Ranking")

    return render_template("end.html",
                           score=score, perfect=(score >= 50),
                           reason=reason, title="Fim da partida", body_class="end")



@app.get("/leaderboard")
def leaderboard():
    mode = request.args.get("mode", "total")
    if mode not in ("total", "best"):
        mode = "total"

    with db_session() as db:
        _maybe_reset_week(db)

        if mode == "best":
            order_cols = (
                func.coalesce(Leaderboard.best_score, 0).desc(),
                Leaderboard.nickname.asc(),
            )
        else:  # total (semanal acumulado)
            order_cols = (
                func.coalesce(Leaderboard.total_points, 0).desc(),
                Leaderboard.nickname.asc(),
            )

        rows = db.execute(
            select(Leaderboard).order_by(*order_cols).limit(10)
        ).scalars().all()

    deadline = next_monday_midnight()
    deadline_ms = int(deadline.timestamp() * 1000)

    return render_template(
        "leaderboard.html",
        rows=rows, body_class="rank", title="Ranking",
        deadline_ms=deadline_ms, mode=mode
    )

if __name__ == "__main__":
    app.run(debug=True)
