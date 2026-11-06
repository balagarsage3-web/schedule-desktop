"""Генерация, версии расписания, просмотр, ручная правка, отчёт о качестве, публичная ссылка."""
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..auth import current_user
from ..db import get_db
from ..solver.expand import Occupancy, PLesson
from ..solver.jobs import manager
from ..solver.precheck import precheck
from ..solver.problem import load_problem
from ..solver.validate import HARD_LABELS, lesson_conflicts, load_report, soft_report, validate

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
public = APIRouter(prefix="/api/public")


def _version(db: Session, vid: int) -> m.ScheduleVersion:
    v = db.get(m.ScheduleVersion, vid)
    if v is None:
        raise HTTPException(404, "Версия расписания не найдена")
    return v


def plessons(db: Session, vid: int, p, start: date | None = None, end: date | None = None) -> list[PLesson]:
    q = db.query(m.Lesson).filter(m.Lesson.version_id == vid)
    if start:
        q = q.filter(m.Lesson.date >= start)
    if end:
        q = q.filter(m.Lesson.date <= end)
    return [PLesson(ls.curriculum_id, ls.date, p.slot_by_id[ls.slot_id].number, ls.room_id, ls.id, ls.pinned)
            for ls in q.all()]


def lesson_dicts(p, lessons: list[PLesson], conflicts: dict[int, list[str]] | None = None) -> list[dict]:
    conflicts = conflicts or {}
    out = []
    for ls in lessons:
        c = p.cur_by_id.get(ls.cur_id)
        if c is None:
            continue
        subj, slot = p.subjects[c.subject_id], p.slot_by_number[ls.slot_number]
        room = p.rooms.get(ls.room_id) if ls.room_id else None
        u = p.unit_of[c.id]
        out.append({
            "id": ls.id, "date": ls.date.isoformat(), "weekday": ls.date.weekday(), "slot_number": ls.slot_number,
            "time": f"{slot.start:%H:%M}–{slot.end:%H:%M}", "curriculum_id": c.id,
            "unit_id": u.id, "stream": u.stream, "group_ids": u.group_ids,
            "groups": ", ".join(p.groups[g].name for g in u.group_ids),
            "group_id": c.group_id, "group": p.groups[c.group_id].name,
            "subject_id": c.subject_id, "subject": subj.name, "lesson_type": subj.lesson_type,
            "teacher_id": c.teacher_id, "teacher": p.teachers[c.teacher_id].name,
            "room_id": ls.room_id, "room": room.number if room else "—", "pinned": ls.pinned,
            "conflicts": conflicts.get(ls.id, []),
        })
    return out


# --- проверка и генерация ---------------------------------------------------
@router.get("/terms/{term_id}/precheck")
def run_precheck(term_id: int, db: Session = Depends(get_db)):
    try:
        p = load_problem(db, term_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    issues = precheck(p)
    return {"ok": not any(i["level"] == "error" for i in issues), "issues": issues,
            "stats": {"groups": len(p.groups), "teachers": len(p.teachers), "rooms": len(p.rooms),
                      "curriculum": len(p.curriculum), "weekly_lessons": sum(c.per_week for c in p.curriculum)}}


@router.post("/generate")
def generate(data: s.GenerateIn, db: Session = Depends(get_db)):
    term = db.get(m.Term, data.term_id)
    if term is None:
        raise HTTPException(404, "Учебный период не найден")
    try:
        job = manager.start(term.id, data.time_limit or term.time_limit)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return job.to_dict()


@router.get("/jobs/active")
def active_job():
    j = manager.active()
    return j.to_dict() if j else None


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    j = manager.jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "Задача не найдена")
    return j.to_dict()


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str):
    j = manager.jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "Задача не найдена")
    j.stop_event.set()
    return j.to_dict()


# --- версии -----------------------------------------------------------------
def version_out(v: m.ScheduleVersion) -> dict:
    return {"id": v.id, "term_id": v.term_id, "number": v.number, "name": v.name,
            "created_at": v.created_at.isoformat(timespec="minutes"), "score": v.score,
            "hard_count": (v.report or {}).get("hard_count", 0), "public_token": v.public_token}


@router.get("/versions")
def list_versions(term_id: int, db: Session = Depends(get_db)):
    vs = db.query(m.ScheduleVersion).filter_by(term_id=term_id).order_by(m.ScheduleVersion.id.desc()).all()
    return [version_out(v) for v in vs]


@router.patch("/versions/{vid}")
def rename_version(vid: int, data: dict, db: Session = Depends(get_db)):
    v = _version(db, vid)
    if data.get("name"):
        v.name = str(data["name"])[:128]
    db.commit()
    return version_out(v)


@router.delete("/versions/{vid}")
def delete_version(vid: int, db: Session = Depends(get_db)):
    db.delete(_version(db, vid))
    db.commit()
    return {"ok": True}


@router.get("/versions/{vid}/lessons")
def version_lessons(vid: int, start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    v = _version(db, vid)
    p = load_problem(db, v.term_id)
    lessons = plessons(db, vid, p)
    conflicts: dict[int, list[str]] = {}
    for c in validate(p, lessons):
        if c["type"] == "count_mismatch" and not c["lesson_ids"]:
            continue
        for lid in c["lesson_ids"]:
            conflicts.setdefault(lid, []).append(c["message"])
    shown = [ls for ls in lessons if (not start or ls.date >= start) and (not end or ls.date <= end)]
    shown.sort(key=lambda x: (x.date, x.slot_number))
    return {"version": version_out(v), "lessons": lesson_dicts(p, shown, conflicts)}


@router.get("/versions/{vid}/context")
def version_context(vid: int, db: Session = Depends(get_db)):
    """Всё, что нужно сетке: пары, дни, праздники, доступность преподавателей."""
    v = _version(db, vid)
    p = load_problem(db, v.term_id)
    return {
        "term": {"id": v.term_id, "name": p.term_name, "start_date": p.start_date.isoformat(),
                 "end_date": p.end_date.isoformat(), "days_per_week": p.days_per_week},
        "slots": [{"number": x.number, "time": f"{x.start:%H:%M}–{x.end:%H:%M}"} for x in p.slots],
        "non_working": sorted(d.isoformat() for d in p.non_working),
        "unavailable": {tid: [[wd, n] for (wd, n), st in cells.items() if st == "unavailable"]
                        for tid, cells in p.availability.items()},
        "days_off": {tid: sorted(d.isoformat() for d in ds) for tid, ds in p.days_off.items()},
        "group_slots": {g: p.group_slots(g) for g in p.groups},
    }


@router.post("/lessons/{lesson_id}/move")
def move_lesson(lesson_id: int, data: s.MoveIn, db: Session = Depends(get_db)):
    """Перенос пары с проверкой конфликтов. series — вместе с такими же парами в последующие недели."""
    row = db.get(m.Lesson, lesson_id)
    if row is None:
        raise HTTPException(404, "Пара не найдена")
    v = _version(db, row.version_id)
    p = load_problem(db, v.term_id)
    if data.slot_number not in p.slot_by_number:
        raise HTTPException(422, "Нет такой пары")
    all_ls = plessons(db, v.id, p)
    by_id = {ls.id: ls for ls in all_ls}
    src = by_id[lesson_id]
    unit = p.unit_of[src.cur_id]
    delta = (data.date - src.date).days

    # Пара потока переносится целиком — у всех групп сразу.
    def same_session(ls, d):
        return p.unit_of[ls.cur_id].id == unit.id and ls.date == d and ls.slot_number == src.slot_number

    if data.series:
        dates = sorted({ls.date for ls in all_ls if p.unit_of[ls.cur_id].id == unit.id and ls.date >= src.date
                        and ls.date.weekday() == src.date.weekday() and ls.slot_number == src.slot_number})
    else:
        dates = [src.date]
    sessions = [[ls for ls in all_ls if same_session(ls, d)] for d in dates]
    moved_ids = {ls.id for s in sessions for ls in s}
    others = [ls for ls in all_ls if ls.id not in moved_ids]
    occ = Occupancy(p, others)

    plan, problems = [], []
    for sess in sessions:
        head = sess[0]
        new_date = head.date + timedelta(days=delta)
        room = data.room_id or occ.free_room(unit, new_date, data.slot_number, prefer=head.room_id) or head.room_id
        news = [PLesson(ls.cur_id, new_date, data.slot_number, room, ls.id, ls.pinned) for ls in sess]
        issues = lesson_conflicts(p, news[0], others)
        for extra in news[1:]:  # смена и численность проверяются по каждой группе потока
            issues += [i for i in lesson_conflicts(p, extra, others) if i["type"] == "shift"]
        if issues:
            problems.append({"date": new_date.isoformat(), "messages": list(dict.fromkeys(i["message"] for i in issues))})
        plan += news
        others += news
        occ.add(news[0])

    if data.dry_run or (problems and not data.force):
        return {"ok": not problems, "applied": False, "count": len(plan), "conflicts": problems}

    slot_id = p.slot_by_number[data.slot_number].id
    for new in plan:
        r = db.get(m.Lesson, new.id)
        r.date, r.slot_id, r.room_id = new.date, slot_id, new.room_id
    db.commit()
    return {"ok": not problems, "applied": True, "count": len(plan), "conflicts": problems}


@router.post("/lessons/{lesson_id}/pin")
def pin_lesson(lesson_id: int, data: dict, db: Session = Depends(get_db)):
    row = db.get(m.Lesson, lesson_id)
    if row is None:
        raise HTTPException(404, "Пара не найдена")
    row.pinned = bool(data.get("pinned", True))
    db.commit()
    return {"ok": True, "pinned": row.pinned}


@router.get("/rooms/free")
def free_rooms(version_id: int, curriculum_id: int, day: date, slot_number: int, db: Session = Depends(get_db)):
    v = _version(db, version_id)
    p = load_problem(db, v.term_id)
    c = p.cur_by_id.get(curriculum_id)
    if c is None:
        raise HTTPException(404, "Строка плана не найдена")
    busy = {ls.room_id for ls in plessons(db, v.id, p, day, day) if ls.slot_number == slot_number}
    return [{"id": r.id, "number": r.number, "capacity": r.capacity} for r in p.suitable_rooms(c) if r.id not in busy]


# --- отчёт о качестве -------------------------------------------------------
@router.get("/versions/{vid}/report")
def version_report(vid: int, db: Session = Depends(get_db)):
    v = _version(db, vid)
    p = load_problem(db, v.term_id)
    lessons = plessons(db, vid, p)
    soft = soft_report(p, lessons)
    hard = validate(p, lessons)
    if v.score != soft["score"]:
        v.score = soft["score"]
        rep = dict(v.report or {})
        rep["hard_count"] = len(hard)
        v.report = rep
        db.commit()
    by_type: dict[str, int] = {}
    for h in hard:
        by_type[h["type"]] = by_type.get(h["type"], 0) + 1
    return {
        "version": version_out(v), "soft": soft,
        "hard": {"count": len(hard), "by_type": [{"label": HARD_LABELS[k], "count": n} for k, n in by_type.items()],
                 "items": [h["message"] for h in hard[:200]]},
        "load": load_report(p, lessons),
        "solver": {k: (v.report or {}).get(k) for k in ("solver_status", "solver_time", "weeks", "weeks_solved",
                                                        "weeks_optimal")},
        "expand_problems": (v.report or {}).get("expand_problems", []),
        "lessons": len(lessons),
    }


# --- публичная ссылка -------------------------------------------------------
@router.post("/versions/{vid}/publish")
def publish(vid: int, data: dict, db: Session = Depends(get_db)):
    v = _version(db, vid)
    if data.get("enabled", True):
        # Для периода публикуется одна версия: прежняя ссылка остаётся и начинает показывать эту версию.
        token = v.public_token
        for other in db.query(m.ScheduleVersion).filter_by(term_id=v.term_id).all():
            if other.id != v.id and other.public_token:
                token = token or other.public_token
                other.public_token = None
        db.flush()
        v.public_token = token or secrets.token_urlsafe(12)
    else:
        v.public_token = None
    db.commit()
    return version_out(v)


@public.get("/{token}")
def public_meta(token: str, db: Session = Depends(get_db)):
    v = db.query(m.ScheduleVersion).filter_by(public_token=token).first()
    if v is None:
        raise HTTPException(404, "Ссылка недействительна")
    p = load_problem(db, v.term_id)
    used_groups = {c.group_id for c in p.curriculum}
    used_teachers = {c.teacher_id for c in p.curriculum}
    return {
        "term": {"name": p.term_name, "start_date": p.start_date.isoformat(), "end_date": p.end_date.isoformat(),
                 "days_per_week": p.days_per_week},
        "version": {"number": v.number, "name": v.name, "created_at": v.created_at.isoformat(timespec="minutes")},
        "slots": [{"number": x.number, "time": f"{x.start:%H:%M}–{x.end:%H:%M}"} for x in p.slots],
        "groups": sorted(({"id": g.id, "name": g.name} for g in p.groups.values() if g.id in used_groups),
                         key=lambda x: x["name"]),
        "teachers": sorted(({"id": t.id, "name": t.name} for t in p.teachers.values() if t.id in used_teachers),
                           key=lambda x: x["name"]),
    }


@public.get("/{token}/lessons")
def public_lessons(token: str, start: date, end: date, db: Session = Depends(get_db)):
    v = db.query(m.ScheduleVersion).filter_by(public_token=token).first()
    if v is None:
        raise HTTPException(404, "Ссылка недействительна")
    if (end - start).days > 62:
        raise HTTPException(422, "Слишком большой диапазон дат")
    p = load_problem(db, v.term_id)
    out = lesson_dicts(p, sorted(plessons(db, v.id, p, start, end), key=lambda x: (x.date, x.slot_number)))
    for x in out:
        x.pop("conflicts", None)
        x.pop("pinned", None)
    return out
