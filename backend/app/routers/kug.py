"""Импорт календарного учебного графика (КУГ) и просмотр/правка нагрузки по неделям."""
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import current_user
from ..db import get_db
from ..kug import KIND_LABELS, KugError, guess_room_type, parse_kug
from ..solver.problem import load_problem, week_start
from .directory import apply_weekly

router = APIRouter(prefix="/api/kug", dependencies=[Depends(current_user)])

MAX_FILE = 10 * 1024 * 1024


async def _parse(file: UploadFile) -> dict:
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(422, "КУГ загружается из файла Excel (.xlsx)")
    content = await file.read()
    if len(content) > MAX_FILE:
        raise HTTPException(422, "Файл больше 10 МБ")
    try:
        return parse_kug(content)
    except KugError as e:
        raise HTTPException(422, str(e))


def _sem_range(sheet: dict, sem: int) -> tuple[date, date] | None:
    mondays = [w["monday"] for w in sheet["weeks"] if w["sem"] == sem]
    if not mondays:
        return None
    start, end = min(mondays), max(mondays) + timedelta(days=6)
    if sem == 1:
        sept1 = date(start.year, 9, 1)
        start = max(start, sept1) if start.month in (8, 9) else start
    return start, end


@router.post("/parse")
async def parse(file: UploadFile = File(...)):
    """Предпросмотр: листы (курсы), недели, дисциплины с часами."""
    data = await _parse(file)
    sheets = []
    for sh in data["sheets"]:
        rows = [{"code": r["code"], "name": r["name"], "kind": r["kind"], "kind_label": KIND_LABELS[r["kind"]],
                 "total": r["total"], "first": min(r["hours"]).isoformat(), "last": max(r["hours"]).isoformat(),
                 "weeks": len(r["hours"])} for r in sh["rows"]]
        sem = {s: _sem_range(sh, s) for s in (1, 2)}
        sheets.append({
            "index": sh["index"], "title": sh["title"], "year": sh["year"], "weeks": len(sh["weeks"]),
            "vacation": [d.isoformat() for d in sh["vacation"]],
            "semesters": [{"sem": s, "start": r[0].isoformat(), "end": r[1].isoformat()} for s, r in sem.items() if r],
            "rows": rows,
        })
    return {"title": data["title"], "profession": data["profession"], "sheets": sheets, "errors": data["errors"]}


def _subject(db: Session, name: str, kind: str, code: str, cache: dict) -> m.Subject:
    """Дисциплина по названию: существующая (если она одна с таким названием) или новая."""
    if kind in ("up", "pp"):
        name = f"{name} ({code})" if code else name
    key = name.lower()
    if key in cache:
        return cache[key]
    found = db.query(m.Subject).filter(m.Subject.name == name).all()
    if len(found) == 1:
        s = found[0]
    else:
        s = next((x for x in found if x.lesson_type == "практика"), None)
        if s is None:
            s = m.Subject(name=name, lesson_type="практика", room_type=guess_room_type(name))
            db.add(s)
            db.flush()
    cache[key] = s
    return s


@router.post("/import")
async def import_kug(file: UploadFile = File(...), sheet: int = Form(...), group_ids: str = Form(...),
                     include_self: bool = Form(False), include_practice: bool = Form(False),
                     make_stream: bool = Form(False), create_terms: bool = Form(True),
                     db: Session = Depends(get_db)):
    """Создаёт/обновляет строки учебного плана выбранных групп по листу КУГ.

    Нагрузка по неделям заменяется только в пределах учебного года этого листа;
    назначенные преподаватели сохраняются."""
    data = await _parse(file)
    sh = next((s for s in data["sheets"] if s["index"] == sheet), None)
    if sh is None:
        raise HTTPException(422, "Лист не найден в файле")
    try:
        gids = [int(x) for x in group_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "Неверный список групп")
    groups = db.query(m.Group).filter(m.Group.id.in_(gids)).all()
    if not groups:
        raise HTTPException(422, "Выберите хотя бы одну группу")

    kinds = {"class"} | ({"self"} if include_self else set()) | ({"up"} if include_practice else set())
    # Аудиторная нагрузка и самостоятельная работа одной дисциплины складываются в одну строку плана.
    merged: dict[tuple[str, str, str], dict] = {}
    for r in sh["rows"]:
        if r["kind"] not in kinds:
            continue
        kind = "up" if r["kind"] == "up" else "class"
        key = (r["code"], r["name"], kind)
        item = merged.setdefault(key, {"code": r["code"], "name": r["name"], "kind": kind, "hours": defaultdict(float)})
        for wk, h in r["hours"].items():
            item["hours"][wk] += h

    year_start = min(w["monday"] for w in sh["weeks"])
    year_end = max(w["monday"] for w in sh["weeks"])
    ref = f"КУГ {data['profession'] or ''}, {sh['title']} ({sh['year']})".strip()
    cache: dict = {}
    created = updated = 0
    names = ", ".join(sorted(g.name for g in groups))
    for item in merged.values():
        subj = _subject(db, item["name"], item["kind"], item["code"], cache)
        for g in groups:
            c = db.query(m.Curriculum).filter_by(group_id=g.id, subject_id=subj.id).first()
            weekly = {}
            if c is None:
                c = m.Curriculum(group_id=g.id, subject_id=subj.id, total=0, per_week=0)
                db.add(c)
                created += 1
            else:
                updated += 1
                # Нагрузку других учебных лет сохраняем, этот год заменяем целиком.
                weekly = {k: v for k, v in (c.weekly or {}).items()
                          if not (year_start <= date.fromisoformat(k) <= year_end)}
            weekly.update({wk.isoformat(): h for wk, h in item["hours"].items()})
            apply_weekly(c, weekly)
            c.start_date = c.end_date = None
            c.kug_ref = f"{ref}, {item['code']}"[:256]
            if make_stream and len(groups) > 1:
                c.stream = f"{item['name'][:40]} ({names})"[:64]
            db.flush()

    terms_created = []
    if create_terms:
        template = db.query(m.Term).order_by(m.Term.id.desc()).first()
        for sem in (1, 2):
            rng = _sem_range(sh, sem)
            if not rng:
                continue
            name = f"{sh['year']}, {'1-е' if sem == 1 else '2-е'} полугодие"
            if db.query(m.Term).filter_by(name=name).first():
                continue
            t = m.Term(name=name, start_date=rng[0], end_date=rng[1],
                       days_per_week=template.days_per_week if template else 5,
                       time_limit=template.time_limit if template else 120,
                       group_day_limit=template.group_day_limit if template else 4,
                       weights=dict(template.weights) if template else dict(m.DEFAULT_WEIGHTS),
                       shift_slots=dict(template.shift_slots) if template else dict(m.DEFAULT_SHIFT_SLOTS))
            db.add(t)
            terms_created.append(name)
    db.commit()
    return {"ok": True, "created": created, "updated": updated, "disciplines": len(merged),
            "groups": [g.name for g in groups], "terms_created": terms_created}


@router.get("/grid")
def grid(group_id: int, term_id: int, db: Session = Depends(get_db)):
    """Нагрузка группы по неделям периода: часы КУГ (редактируемые) и пары, которые поставит решатель."""
    term = db.get(m.Term, term_id)
    if term is None:
        raise HTTPException(404, "Учебный период не найден")
    p = load_problem(db, term_id)
    weeks = []
    wk = week_start(term.start_date)
    while wk <= term.end_date:
        weeks.append(wk)
        wk += timedelta(days=7)
    study = set(p.weeks)
    rows = []
    for c in sorted((c for c in p.curriculum if c.group_id == group_id),
                    key=lambda c: (p.cur_by_id[c.id].weekly is None, p.subjects[c.subject_id].name)):
        u = p.unit_of.get(c.id)
        dem = p.demand.get(u.id, {}) if u else {}
        hours = {k.isoformat(): v for k, v in (c.weekly or {}).items() if weeks and weeks[0] <= k <= weeks[-1]}
        if not dem and not hours:
            continue
        rows.append({
            "id": c.id, "subject": p.subjects[c.subject_id].name, "teacher": p.teachers[c.teacher_id].name,
            "teacher_missing": c.teacher_id == 0, "kug": c.weekly is not None, "stream": c.stream,
            "hours": hours, "pairs": {k.isoformat(): v for k, v in dem.items()},
            "total_pairs": sum(dem.values()),
        })
    totals = defaultdict(int)
    for r in rows:
        for k, v in r["pairs"].items():
            totals[k] += v
    return {
        "weeks": [{"monday": w.isoformat(), "label": f"{w:%d.%m}", "study": w in study} for w in weeks],
        "rows": rows, "totals": dict(totals),
        "capacity": len(p.group_slots(group_id)) * p.days_per_week if group_id in p.groups else 0,
    }


@router.get("/kinds")
def kinds():
    return KIND_LABELS
