# app.py
import random, os
from flask import Flask, render_template, request, redirect, url_for, session
from sqlalchemy import select, func, text
from models import SessionLocal, User, Question, Leaderboard, THEMES, Base, engine

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "troque-esta-chave")

# cria tabelas em cold start (seguro: idempotente)
Base.metadata.create_all(engine)

THEMES = ["Esportes", "TV/Cinema", "Jogos", "Música", "Lógica", "História", "Diversos"]

def db_session():
    db = SessionLocal()
    try: yield db
    finally: db.close()

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

    db = next(db_session())
    user = db.get(User, nickname)
    if not user:
        user = User(nickname=nickname)
        db.add(user); db.commit()

    theme = random.choice(THEMES)

    # zera estado da nova partida
    session.update(nickname=nickname, theme=theme, asked_ids=[], score=0)
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
    show_roulette = False
    if len(asked_ids) == 0 and not session.get("roulette_shown"):
        show_roulette = True
        session["roulette_shown"] = True

    db = next(db_session())

    # ----- MODO FEEDBACK (após POST/redirect) -----
    if request.args.get("fb") == "1":
        fb = session.get("feedback_state")
        if fb:
            q = db.get(Question, fb["qid"])
            score = len(asked_ids)
            # opcional: limpar para evitar reexibir em refresh
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
                title="Jogo"
            )
        # se não houver fb na sessão, cai pro fluxo normal

    # ----- MODO PERGUNTA NORMAL -----
    q = db.execute(
        select(Question)
        .where(Question.theme == theme)
        .where(~Question.id.in_(asked_ids) if asked_ids else True)
        .order_by(func.random())
        .limit(1)
    ).scalar_one_or_none()
    if not q:
        return redirect(url_for("end", reason="completou"))

    return render_template(
        "game.html",
        q=q,
        theme=theme,
        score=len(asked_ids),
        feedback=False,
        themes=THEMES,
        show_roulette=show_roulette,
        body_class="game",
        title="Jogo"
    )

@app.post("/answer")
def answer():
    picked  = (request.form.get("picked") or "").upper()
    correct = (request.form.get("correct") or "").upper()
    qid     = int(request.form.get("qid"))

    db = next(db_session())
    q  = db.get(Question, qid)

    asked = session.get("asked_ids") or []
    timed_out  = (picked == "TIMEOUT")
    was_correct = (picked == correct) and not timed_out

    if was_correct and (qid not in asked):
        asked.append(qid)
        session["asked_ids"] = asked

    # guarda feedback na sessão (para a próxima GET)
    session["feedback_state"] = {
        "qid": qid,
        "was_correct": was_correct,
        "timed_out": timed_out,
        "picked": picked if picked in ["A","B","C","D"] else None,
        "correct": correct,
    }

    # Turbo exige redirect após POST
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

    db = next(db_session())

    # --- estado ANTES ---
    rows_before = _load_ranking(db)
    existed     = any(r.nickname == nickname for r in rows_before)
    old_pos     = _find_position(rows_before, nickname)

    # Upsert só com score > 0
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

        # medalha opcional (ajuste o limiar)
        if score >= 30:
            u = db.get(User, nickname)
            if u:
                u.has_perfect_medal = True

        db.commit()

    # 0 acertos → tela padrão
    if score == 0:
        return render_template("end.html",
                               score=score,
                               perfect=False,
                               reason=reason,
                               title="Fim da partida",
                               body_class="end")

    # --- estado DEPOIS ---
    rows_after = _load_ranking(db)
    new_pos    = _find_position(rows_after, nickname)

    # 1) Primeira vez no ranking
    if not existed:
        return render_template("leaderboard.html",
                               rows=rows_after[:30],
                               just_added=nickname,
                               body_class="rank",
                               title="Ranking",)

    # 2) mostra promoção se SUBIU posição
    moved_up = (old_pos is not None and new_pos is not None and new_pos < old_pos)
    if moved_up:
        return render_template("leaderboard.html",
                               rows=rows_after[:30],
                               promoted_nick=nickname,
                               positions_up=(old_pos - new_pos),
                               new_rank=new_pos,
                               body_class="rank",
                               title="Ranking")

    # 3) Sem mudança de posição
    return render_template("end.html",
                           score=score,
                           perfect=(score >= 30),
                           reason=reason,
                           title="Fim da partida",
                           body_class="end")



@app.get("/leaderboard")
def leaderboard():
    db = next(db_session())
    rows = db.execute(
        select(Leaderboard).order_by(Leaderboard.best_score.desc(), Leaderboard.nickname.asc()).limit(20)
    ).scalars().all()
    
    return render_template("leaderboard.html", rows=rows, body_class="rank", title="Ranking")


if __name__ == "__main__":
    app.run(debug=True)
