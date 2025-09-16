# app.py
import random, os
from flask import Flask, render_template, request, redirect, url_for, session
from sqlalchemy import select, func, text
from models import SessionLocal, User, Question, Leaderboard, THEMES, Base, engine
from contextlib import contextmanager

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "troque-esta-chave")

# cria tabelas em cold start (seguro: idempotente)
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

def _next_qid_from_queue():
    """Pega o próximo ID da fila que ainda não foi perguntado; atualiza a fila na sessão."""
    queue = session.get("queue_ids") or []
    asked = set(session.get("asked_ids") or [])
    qid = None
    while queue and qid is None:
        cand = queue.pop(0)  # FIFO
        if cand not in asked:
            qid = cand
    session["queue_ids"] = queue
    return qid

def _load_ranking(db):
    return db.execute(
        select(Leaderboard).order_by(
            Leaderboard.best_score.desc(), Leaderboard.nickname.asc()
        )
    ).scalars().all()

def _find_position(rows, nickname):
    for i, r in enumerate(rows, start=1):
        if r.nickname == nickname:
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
    session.pop("roulette_shown", None)

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
    )

@app.post("/answer")
def answer():
    picked  = (request.form.get("picked") or "").upper()
    correct = (request.form.get("correct") or "").upper()
    qid     = int(request.form.get("qid"))

    timed_out  = (picked == "TIMEOUT")
    was_correct = (picked == correct) and not timed_out

    asked = session.get("asked_ids") or []
    if was_correct and (qid not in asked):
        asked.append(qid)
        session["asked_ids"] = asked

    session["feedback_state"] = {
        "qid": qid,
        "was_correct": was_correct,
        "timed_out": timed_out,
        "picked": picked if picked in ["A","B","C","D"] else None,
        "correct": correct,
    }
    return redirect(url_for("game", fb=1))


@app.post("/continue")
def go_next():
    last = request.form.get("last", "correct")
    if last in ("wrong", "timeout"):           # << aceita timeout como fim
        return redirect(url_for("end", reason=last))

    asked = session.get("asked_ids") or []
    if len(asked) >= 30:
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
        rows_before = _load_ranking(db)
        existed     = any(r.nickname == nickname for r in rows_before)
        old_pos     = _find_position(rows_before, nickname)

        if score > 0:
            db.execute(text("""
                INSERT INTO leaderboard (nickname, best_score)
                VALUES (:nick, :score)
                ON CONFLICT(nickname) DO UPDATE SET
                  best_score = CASE
                    WHEN excluded.best_score > leaderboard.best_score
                    THEN excluded.best_score
                    ELSE leaderboard.best_score
                  END
            """), {"nick": nickname, "score": score})

            if score >= 30:
                u = db.get(User, nickname)
                if u:
                    u.has_perfect_medal = True

        if score == 0:
            return render_template("end.html",
                                   score=score, perfect=False, reason=reason,
                                   title="Fim da partida", body_class="end")

        rows_after = _load_ranking(db)
        new_pos    = _find_position(rows_after, nickname)

    if not existed:
        return render_template("leaderboard.html",
                               rows=rows_after[:30],
                               just_added=nickname,
                               body_class="rank", title="Ranking")

    moved_up = (old_pos is not None and new_pos is not None and new_pos < old_pos)
    if moved_up:
        return render_template("leaderboard.html",
                               rows=rows_after[:30],
                               promoted_nick=nickname,
                               positions_up=(old_pos - new_pos),
                               new_rank=new_pos,
                               body_class="rank", title="Ranking")

    return render_template("end.html",
                           score=score, perfect=(score >= 30),
                           reason=reason, title="Fim da partida", body_class="end")


@app.get("/leaderboard")
def leaderboard():
    with db_readonly() as db:
        rows = db.execute(
            select(Leaderboard).order_by(Leaderboard.best_score.desc(), Leaderboard.nickname.asc()).limit(20)
        ).scalars().all()
        
    return render_template("leaderboard.html", rows=rows, body_class="rank", title="Ranking")


if __name__ == "__main__":
    app.run(debug=True)
