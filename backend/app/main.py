from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models as m
from . import schemas as s
from .auth import current_user, ensure_admin, hash_password, make_token, verify_password
from .config import FRONTEND_DIST
from .db import Base, SessionLocal, engine, get_db
from .routers import directory, export, importer, kug, schedule


def migrate():
    """Приводит таблицу curriculum старых баз к текущей схеме (create_all существующие таблицы не меняет)."""
    from sqlalchemy import MetaData, inspect, text  # noqa: F401

    info = {c["name"]: c for c in inspect(engine).get_columns("curriculum")}
    needed = {"stream", "start_date", "end_date", "weekly", "kug_ref"}
    teacher_required = not info["teacher_id"]["nullable"]
    if needed <= set(info) and not teacher_required:
        return
    table = m.Curriculum.__table__
    if engine.dialect.name == "sqlite":
        # SQLite не умеет менять столбцы — пересобираем таблицу, сохраняя данные.
        # Внешние ключи отключаются вне транзакции, иначе DROP каскадно удалил бы пары расписания.
        from sqlalchemy.schema import CreateTable

        md = MetaData()
        for ref in ("groups", "subjects", "teachers"):  # для внешних ключей нужны и связанные таблицы
            Base.metadata.tables[ref].to_metadata(md)
        tmp = table.to_metadata(md, name="curriculum_new")
        ddl_new = str(CreateTable(tmp).compile(engine))
        cols = ", ".join(c.name for c in table.columns if c.name in info)
        raw = engine.raw_connection()
        try:
            con = raw.driver_connection
            con.isolation_level = None
            cur = con.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")
            cur.execute("BEGIN")
            cur.execute(ddl_new)
            cur.execute(f"INSERT INTO curriculum_new ({cols}) SELECT {cols} FROM curriculum")
            cur.execute("DROP TABLE curriculum")
            cur.execute("ALTER TABLE curriculum_new RENAME TO curriculum")
            cur.execute("COMMIT")
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            raw.invalidate()  # соединение с изменёнными настройками в пул не возвращаем
        return
    ddl = {"stream": "VARCHAR(64) NOT NULL DEFAULT ''", "start_date": "DATE", "end_date": "DATE",
           "weekly": "JSON", "kug_ref": "VARCHAR(256) NOT NULL DEFAULT ''"}
    with engine.begin() as conn:
        for name in needed - set(info):
            conn.execute(text(f"ALTER TABLE curriculum ADD COLUMN {name} {ddl[name]}"))
        if teacher_required:
            conn.execute(text("ALTER TABLE curriculum ALTER COLUMN teacher_id DROP NOT NULL"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    migrate()
    with SessionLocal() as db:
        ensure_admin(db)
    yield


app = FastAPI(title="Сервис составления расписания", version="1.0.0", lifespan=lifespan)
app.include_router(directory.router)
app.include_router(importer.router)
app.include_router(kug.router)
app.include_router(schedule.router)
app.include_router(schedule.public)
app.include_router(export.router)


@app.post("/api/auth/login")
def login(data: s.LoginIn, db: Session = Depends(get_db)):
    user = db.query(m.User).filter(m.User.login == data.login).first()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    return {"token": make_token(user.id), "login": user.login, "role": user.role}


@app.get("/api/auth/me")
def me(user: m.User = Depends(current_user)):
    return {"login": user.login, "role": user.role}


@app.post("/api/auth/password")
def change_password(data: dict, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(str(data.get("old", "")), user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")
    new = str(data.get("new", ""))
    if len(new) < 6:
        raise HTTPException(400, "Новый пароль — не короче 6 символов")
    db_user = db.get(m.User, user.id)
    db_user.password_hash = hash_password(new)
    db.commit()
    return {"ok": True}


@app.post("/api/demo", dependencies=[Depends(current_user)])
def load_demo(data: dict, db: Session = Depends(get_db)):
    """Заменяет все данные демонстрационным набором (для знакомства с системой)."""
    from .seed import seed

    n = max(3, min(60, int(data.get("groups", 12))))
    term = seed(db, n)
    return {"ok": True, "term_id": term.id}


@app.get("/api/health")
def health():
    return {"ok": True}


# Собранный фронтенд (frontend/dist) раздаётся тем же сервером; все неизвестные пути — в SPA.
DIST = FRONTEND_DIST.resolve()
if (DIST / "index.html").exists():
    if (DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
