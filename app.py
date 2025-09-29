# app.py
import random, os
import secrets
import unicodedata
import re
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from sqlalchemy import select, text, func
from models import SessionLocal, User, Question, Leaderboard, THEMES, Base, engine
from contextlib import contextmanager
from models import Meta
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta
from dotenv import load_dotenv


load_dotenv() 

TZ = ZoneInfo("America/Manaus")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "28a08c230e257781ef22b1d7be9758a0")

Base.metadata.create_all(engine)

login_manager = LoginManager(app)
login_manager.login_view = "login"   # rota que mostra tela de login quando exige auth

# Carrega usuário por id (no nosso caso, 'nickname')
@login_manager.user_loader
def load_user(user_id: str):
    with db_readonly() as db:
        return db.get(User, user_id)

# OAuth (Authlib)
oauth = OAuth(app)

# Google OpenID Connect (usa discovery)
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    client_kwargs={"scope": "openid email profile"},
)

THEMES = ["Esportes", "TV/Cinema", "Jogos", "Música", "Lógica", "História", "Diversos"]

MAINTENANCE_MODE = os.getenv("MAINTENANCE", "0")

@app.before_request
def check_maintenance():
    if MAINTENANCE_MODE == "1" and request.path != "/maintenance":
        return redirect(url_for("maintenance"))


@app.get("/maintenance")
def maintenance():
    return render_template("maintenance.html",
                           title="Em atualização",
                           body_class="maintenance"), 503


@app.get("/version.json")
def version_json():
    """
    Retorna metadados de versão do app para o banner e pop-up automático.
    Se quiser, troque o conteúdo abaixo a cada release.
    """
    payload = {
        "version": "1.0.3",
        "released_at": "2025-09-29 22:00-00:00",  # America/Manaus"
        "notes": [
            "Pop-up de novidades",
            "Página de manutenção",
            "Correção do reset do ranking semanal",
            "Sistema de login e cadastro",
            "Mudanças visuais na página inicial",
        ],
        "cta": {"label": "Ver novidades", "action": "#whats-new"},
    }
    resp = make_response(jsonify(payload))
    # Evita cache agressivo do navegador/CDN
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return render_template("login.html", title="Entrar", body_class="home")

@app.post("/login/email")
def login_email():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    if not email or not password:
        flash("Informe email e senha.", "warn")
        return redirect(url_for("login"))

    with db_readonly() as db:
        user = db.query(User).filter(User.email == email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
        flash("Credenciais inválidas.", "error")
        return redirect(url_for("login"))

    login_user(user)
    flash(f"Bem-vindo(a), {user.nickname}!", "ok")
    return redirect(url_for("home"))

@app.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return render_template("register.html", title="Criar conta", body_class="home")

@app.post("/register")
def register_post():
    nickname = (request.form.get("nickname") or "").strip()
    email    = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    errs = validate_registration(nickname, email, password)

    with db_session() as db:
        if not errs and db.get(User, nickname):
            errs["nickname"] = "Esse nickname já está em uso."
        if not errs and db.query(User).filter(User.email == email).first():
            errs["email"] = "Esse email já está em uso."

        if errs:
            # Re-exibe o formulário com erros e valores preenchidos
            return render_template(
                "register.html",
                title="Criar conta",
                form={"nickname": nickname, "email": email},
                errors=errs,
                success=None
            ), 400

        # Sem erros → cria usuário
        user = User(
            nickname=nickname,
            email=email,
            password_hash=generate_password_hash(password),
            is_active=True,
        )
        db.add(user)

    # Já loga o usuário e manda pra home (igual Google)
    login_user(user)
    flash("Conta criada com sucesso!", "ok")
    return redirect(url_for("home"))

# --- Google OAuth ---
@app.get("/auth/google")
def auth_google():
    redirect_uri = url_for("auth_google_cb", _external=True)
    # Cria o redirect e, ANTES de retornar, loga as chaves da sessão
    resp = oauth.google.authorize_redirect(redirect_uri)
    try:
        app.logger.info("SESSION KEYS BEFORE REDIRECT: %s", list(session.keys()))
    except Exception:
        pass
    return resp


@app.get("/auth/google/callback")
def auth_google_cb():
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo") or {}
    except Exception as e:
        app.logger.exception("Falha no OAuth Google: %s", e)
        flash("Falha ao autenticar com o Google. Tente novamente.", "error")
        return redirect(url_for("login"))

    sub = userinfo.get("sub")
    email = (userinfo.get("email") or "").lower()
    display_name = beautify_name(userinfo.get("name") or (email.split("@")[0] if email else "Jogador"))

    with db_session() as db:
        user = db.query(User).filter(User.google_id == sub).first()
        if not user and email:
            user = db.query(User).filter(User.email == email).first()

        if not user:
            nick = unique_nickname_human(db, display_name)
            user = User(nickname=nick, email=email, google_id=sub, is_active=True)
            db.add(user)
        else:
            if not user.google_id:
                user.google_id = sub
            if email and not user.email:
                user.email = email
            # opcional: atualizar nickname para a versão “bonita” se hoje for vazio/padrão
            # (comente se você preferir nunca mexer em nickname já existente)
            if user.nickname and user.nickname.lower() == (email.split("@")[0] if email else "").lower():
                new_nick = unique_nickname_human(db, display_name)
                user.nickname = new_nick

    login_user(user)
    flash(f"Olá, {user.nickname}!", "ok")
    nxt = session.pop("post_auth_next", "") or url_for("home")
    return redirect(nxt)

@app.post("/logout")
def do_logout():
    logout_user()
    session.clear()
    flash("Você saiu da conta.", "ok")
    return redirect(url_for("login"))


LOWER_WORDS_PT = {"de","da","do","das","dos","e"}


def beautify_name(name: str) -> str:
    """Normaliza acentos (NFC), espaçamentos e capitaliza iniciais em PT-BR."""
    if not name:
        return "Jogador"
    s = unicodedata.normalize("NFC", name).strip()
    s = re.sub(r"\s+", " ", s)
    parts = s.split(" ")
    out = []
    for i, p in enumerate(parts):
        w = p.lower()
        if i > 0 and w in LOWER_WORDS_PT:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)

def unique_nickname_human(db, base_name: str) -> str:
    """
    Tenta manter o nome 'bonito' como nickname. Se já existir, anexa um número.
    Ex.: 'Lucas Silva', 'Lucas Silva 2', 'Lucas Silva 3', ...
    """
    base = beautify_name(base_name)
    if not db.get(User, base):
        return base
    i = 2
    while True:
        cand = f"{base} {i}"
        if not db.get(User, cand):
            return cand
        i += 1


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

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def validate_registration(nickname: str, email: str, password: str):
    errors = {}
    nn = (nickname or "").strip()
    em = (email or "").strip().lower()
    pw = password or ""

    if not nn:
        errors["nickname"] = "Informe um nickname."
    elif len(nn) < 3:
        errors["nickname"] = "Nickname precisa ter pelo menos 3 caracteres."
    elif len(nn) > 50:
        errors["nickname"] = "Nickname muito longo (máx. 50)."

    if not em:
        errors["email"] = "Informe um email."
    elif not EMAIL_RE.match(em):
        errors["email"] = "Email inválido."

    if not pw:
        errors["password"] = "Informe uma senha."
    elif len(pw) < 6:
        errors["password"] = "Senha muito curta (mín. 6)."

    return errors

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
@login_required
def home():
    return render_template("home.html", body_class="home")

THEMES = ["Esportes", "TV/Cinema", "Jogos", "Música", "Lógica", "História", "Diversos"]

@app.post("/start")
@login_required
def start():
    # Se estiver logado, o nickname vem do current_user
    if current_user.is_authenticated:
        nickname = current_user.nickname
    else:
        nickname = (request.form.get("nickname") or "").strip()

    if not nickname:
        return redirect(url_for("home"))

    with db_session() as db:
        user = db.get(User, nickname)
        if not user:
            # Se for convidado criando nickname "solto", cria registro mínimo (sem email/senha)
            db.add(User(nickname=nickname, is_active=True))

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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
            where_cond = (func.coalesce(Leaderboard.best_score, 0) > 0)
        else:  # total (semanal acumulado)
            order_cols = (
                func.coalesce(Leaderboard.total_points, 0).desc(),
                Leaderboard.nickname.asc(),
                
            )
            where_cond = (func.coalesce(Leaderboard.total_points, 0) > 0)

        rows = db.execute(
            select(Leaderboard).where(where_cond).order_by(*order_cols).limit(10)
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