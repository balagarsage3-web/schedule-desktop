"""Справочники, учебный план, параметры периода, доступность преподавателей."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..auth import current_user
from ..db import get_db
from ..solver.problem import weekly_pairs

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _commit(db: Session, what: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"{what} с такими данными уже существует")


def _get(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, "Запись не найдена")
    return obj


def simple_crud(path: str, model, schema_in, schema_out, what: str, order):
    @router.get(f"/{path}", response_model=list[schema_out], name=f"list_{path}")
    def list_(db: Session = Depends(get_db)):
        return db.query(model).order_by(order).all()

    @router.post(f"/{path}", response_model=schema_out, name=f"create_{path}")
    def create(data: schema_in, db: Session = Depends(get_db)):
        obj = model(**data.model_dump())
        db.add(obj)
        _commit(db, what)
        return obj

    @router.put(f"/{path}/{{obj_id}}", response_model=schema_out, name=f"update_{path}")
    def update(obj_id: int, data: schema_in, db: Session = Depends(get_db)):
        obj = _get(db, model, obj_id)
        for k, v in data.model_dump().items():
            setattr(obj, k, v)
        _commit(db, what)
        return obj

    @router.delete(f"/{path}/{{obj_id}}", name=f"delete_{path}")
    def delete(obj_id: int, db: Session = Depends(get_db)):
        db.delete(_get(db, model, obj_id))
        db.commit()
        return {"ok": True}


simple_crud("groups", m.Group, s.GroupIn, s.GroupOut, "Группа", m.Group.name)
simple_crud("subjects", m.Subject, s.SubjectIn, s.SubjectOut, "Дисциплина", m.Subject.name)
simple_crud("rooms", m.Room, s.RoomIn, s.RoomOut, "Аудитория", m.Room.number)
simple_crud("time-slots", m.TimeSlot, s.TimeSlotIn, s.TimeSlotOut, "Пара", m.TimeSlot.number)


# --- преподаватели ----------------------------------------------------------
def teacher_out(t: m.Teacher) -> dict:
    return {"id": t.id, "full_name": t.full_name, "max_per_day": t.max_per_day, "max_per_week": t.max_per_week,
            "subject_ids": [x.id for x in t.subjects]}


@router.get("/teachers", response_model=list[s.TeacherOut])
def list_teachers(db: Session = Depends(get_db)):
    return [teacher_out(t) for t in db.query(m.Teacher).order_by(m.Teacher.full_name).all()]


def _apply_teacher(db: Session, t: m.Teacher, data: s.TeacherIn):
    t.full_name, t.max_per_day, t.max_per_week = data.full_name, data.max_per_day, data.max_per_week
    t.subjects = db.query(m.Subject).filter(m.Subject.id.in_(data.subject_ids)).all() if data.subject_ids else []


@router.post("/teachers", response_model=s.TeacherOut)
def create_teacher(data: s.TeacherIn, db: Session = Depends(get_db)):
    t = m.Teacher()
    _apply_teacher(db, t, data)
    db.add(t)
    _commit(db, "Преподаватель")
    return teacher_out(t)


@router.put("/teachers/{obj_id}", response_model=s.TeacherOut)
def update_teacher(obj_id: int, data: s.TeacherIn, db: Session = Depends(get_db)):
    t = _get(db, m.Teacher, obj_id)
    _apply_teacher(db, t, data)
    _commit(db, "Преподаватель")
    return teacher_out(t)


@router.delete("/teachers/{obj_id}")
def delete_teacher(obj_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, m.Teacher, obj_id))
    db.commit()
    return {"ok": True}


@router.get("/teachers/{obj_id}/availability", response_model=list[s.AvailabilityCell])
def get_availability(obj_id: int, db: Session = Depends(get_db)):
    _get(db, m.Teacher, obj_id)
    return db.query(m.TeacherAvailability).filter_by(teacher_id=obj_id).all()


@router.put("/teachers/{obj_id}/availability")
def put_availability(obj_id: int, cells: list[s.AvailabilityCell], db: Session = Depends(get_db)):
    _get(db, m.Teacher, obj_id)
    db.query(m.TeacherAvailability).filter_by(teacher_id=obj_id).delete()
    for c in cells:
        if c.status != "available":  # «доступен» — значение по умолчанию, его не храним
            db.add(m.TeacherAvailability(teacher_id=obj_id, weekday=c.weekday, slot_number=c.slot_number, status=c.status))
    db.commit()
    return {"ok": True}


@router.get("/teachers/{obj_id}/days-off", response_model=list[s.DayOffOut])
def list_days_off(obj_id: int, db: Session = Depends(get_db)):
    return db.query(m.TeacherDayOff).filter_by(teacher_id=obj_id).order_by(m.TeacherDayOff.date).all()


@router.post("/teachers/{obj_id}/days-off", response_model=s.DayOffOut)
def add_day_off(obj_id: int, data: s.DayOffIn, db: Session = Depends(get_db)):
    _get(db, m.Teacher, obj_id)
    d = m.TeacherDayOff(teacher_id=obj_id, **data.model_dump())
    db.add(d)
    db.commit()
    return d


@router.delete("/days-off/{obj_id}")
def delete_day_off(obj_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, m.TeacherDayOff, obj_id))
    db.commit()
    return {"ok": True}


# --- учебный план -----------------------------------------------------------
def cur_out(c: m.Curriculum) -> dict:
    return {"id": c.id, "group_id": c.group_id, "subject_id": c.subject_id, "teacher_id": c.teacher_id,
            "total": c.total, "per_week": c.per_week, "stream": c.stream or "",
            "start_date": c.start_date, "end_date": c.end_date,
            "group_name": c.group.name, "subject_name": c.subject.name, "lesson_type": c.subject.lesson_type,
            "teacher_name": c.teacher.full_name if c.teacher else "",
            "has_kug": bool(c.weekly), "kug_ref": c.kug_ref or "",
            "kug_hours": int(sum((c.weekly or {}).values()))}


def apply_weekly(c: m.Curriculum, weekly: dict | None):
    """Сохраняет недельную нагрузку КУГ и пересчитывает итоговые «пар всего» и «пар в неделю (макс.)»."""
    clean = {k: float(v) for k, v in (weekly or {}).items() if v and float(v) > 0}
    c.weekly = clean or None
    if clean:
        pairs = weekly_pairs(clean)
        c.total = sum(pairs.values())
        c.per_week = max(pairs.values()) if pairs else 0


@router.get("/curriculum", response_model=list[s.CurriculumOut])
def list_curriculum(db: Session = Depends(get_db)):
    rows = db.query(m.Curriculum).join(m.Group).join(m.Subject).order_by(m.Group.name, m.Subject.name).all()
    return [cur_out(c) for c in rows]


def _check_refs(db: Session, data: s.CurriculumIn):
    refs = [(m.Group, data.group_id, "Группа"), (m.Subject, data.subject_id, "Дисциплина")]
    if data.teacher_id is not None:
        refs.append((m.Teacher, data.teacher_id, "Преподаватель"))
    for model, oid, what in refs:
        if db.get(model, oid) is None:
            raise HTTPException(422, f"{what} не найден(а)")
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise HTTPException(422, "Дата окончания дисциплины раньше даты начала")


@router.post("/curriculum", response_model=s.CurriculumOut)
def create_curriculum(data: s.CurriculumIn, db: Session = Depends(get_db)):
    _check_refs(db, data)
    if not data.total or not data.per_week:
        raise HTTPException(422, "Укажите пар всего и пар в неделю (больше нуля)")
    c = m.Curriculum(**data.model_dump())
    db.add(c)
    _commit(db, "Строка плана для этой группы и дисциплины")
    db.refresh(c)
    return cur_out(c)


@router.put("/curriculum/{obj_id}", response_model=s.CurriculumOut)
def update_curriculum(obj_id: int, data: s.CurriculumIn, db: Session = Depends(get_db)):
    _check_refs(db, data)
    c = _get(db, m.Curriculum, obj_id)
    values = data.model_dump()
    if c.weekly:  # у строк из КУГ количество пар задаётся графиком по неделям
        values.pop("total")
        values.pop("per_week")
    elif not data.total or not data.per_week:
        raise HTTPException(422, "Укажите пар всего и пар в неделю (больше нуля)")
    for k, v in values.items():
        setattr(c, k, v)
    _commit(db, "Строка плана для этой группы и дисциплины")
    db.refresh(c)
    return cur_out(c)


@router.post("/curriculum/assign-teacher")
def assign_teacher(data: s.AssignTeacherIn, db: Session = Depends(get_db)):
    """Назначает одного преподавателя сразу нескольким строкам плана."""
    if data.teacher_id is not None:
        t = _get(db, m.Teacher, data.teacher_id)
    rows = db.query(m.Curriculum).filter(m.Curriculum.id.in_(data.ids)).all()
    for c in rows:
        c.teacher_id = data.teacher_id
        if data.teacher_id is not None and c.subject not in t.subjects:
            t.subjects.append(c.subject)  # отмечаем, что преподаватель ведёт эту дисциплину
    db.commit()
    return {"updated": len(rows)}


@router.get("/curriculum/{obj_id}/weekly")
def get_weekly(obj_id: int, db: Session = Depends(get_db)):
    c = _get(db, m.Curriculum, obj_id)
    return {"weekly": c.weekly or {}}


@router.put("/curriculum/{obj_id}/weekly", response_model=s.CurriculumOut)
def put_weekly(obj_id: int, data: s.WeeklyIn, db: Session = Depends(get_db)):
    """Правка нагрузки КУГ по неделям (часы)."""
    c = _get(db, m.Curriculum, obj_id)
    for k, v in data.weekly.items():
        try:
            date.fromisoformat(k)
        except ValueError:
            raise HTTPException(422, f"Неверная дата недели: {k}")
        if v < 0 or v > 60:
            raise HTTPException(422, "Часы в неделю — от 0 до 60")
    merged = dict(c.weekly or {})
    merged.update({k: v for k, v in data.weekly.items()})
    apply_weekly(c, merged)
    if not c.weekly:
        raise HTTPException(422, "В графике не осталось ни одного часа — удалите строку плана, если она не нужна")
    db.commit()
    db.refresh(c)
    return cur_out(c)


@router.delete("/curriculum/{obj_id}")
def delete_curriculum(obj_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, m.Curriculum, obj_id))
    db.commit()
    return {"ok": True}


# --- учебные периоды --------------------------------------------------------
@router.get("/terms", response_model=list[s.TermOut])
def list_terms(db: Session = Depends(get_db)):
    return db.query(m.Term).order_by(m.Term.start_date.desc()).all()


def _term_data(data: s.TermIn) -> dict:
    if data.end_date < data.start_date:
        raise HTTPException(422, "Дата конца периода раньше даты начала")
    d = data.model_dump()
    w = dict(m.DEFAULT_WEIGHTS)
    w.update({k: v for k, v in d["weights"].items() if k in w})
    d["weights"] = w
    d["shift_slots"] = d["shift_slots"] or dict(m.DEFAULT_SHIFT_SLOTS)
    return d


@router.post("/terms", response_model=s.TermOut)
def create_term(data: s.TermIn, db: Session = Depends(get_db)):
    t = m.Term(**_term_data(data))
    db.add(t)
    db.commit()
    return t


@router.put("/terms/{obj_id}", response_model=s.TermOut)
def update_term(obj_id: int, data: s.TermIn, db: Session = Depends(get_db)):
    t = _get(db, m.Term, obj_id)
    for k, v in _term_data(data).items():
        setattr(t, k, v)
    db.commit()
    return t


@router.delete("/terms/{obj_id}")
def delete_term(obj_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, m.Term, obj_id))
    db.commit()
    return {"ok": True}


@router.get("/terms/{obj_id}/non-working-days", response_model=list[s.NonWorkingOut])
def list_non_working(obj_id: int, db: Session = Depends(get_db)):
    return db.query(m.NonWorkingDay).filter_by(term_id=obj_id).order_by(m.NonWorkingDay.date).all()


@router.post("/terms/{obj_id}/non-working-days", response_model=s.NonWorkingOut)
def add_non_working(obj_id: int, data: s.NonWorkingIn, db: Session = Depends(get_db)):
    _get(db, m.Term, obj_id)
    d = m.NonWorkingDay(term_id=obj_id, **data.model_dump())
    db.add(d)
    _commit(db, "Нерабочий день")
    return d


@router.delete("/non-working-days/{obj_id}")
def delete_non_working(obj_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, m.NonWorkingDay, obj_id))
    db.commit()
    return {"ok": True}


BULK_MODELS = {
    "groups": m.Group, "subjects": m.Subject, "teachers": m.Teacher, "rooms": m.Room,
    "curriculum": m.Curriculum, "time-slots": m.TimeSlot, "versions": m.ScheduleVersion,
}


@router.post("/bulk-delete/{entity}")
def bulk_delete(entity: str, data: dict, db: Session = Depends(get_db)):
    """Удаляет выбранные записи (ids) или все записи справочника (all=true)."""
    model = BULK_MODELS.get(entity)
    if model is None:
        raise HTTPException(404, "Нет такого справочника")
    q = db.query(model)
    if not data.get("all"):
        ids = [int(i) for i in data.get("ids", [])]
        if not ids:
            return {"deleted": 0}
        q = q.filter(model.id.in_(ids))
    objs = q.all()
    for obj in objs:  # через ORM, чтобы удалились и связи (например, дисциплины преподавателя)
        db.delete(obj)
    db.commit()
    return {"deleted": len(objs)}


@router.get("/meta")
def meta():
    return {"lesson_types": m.LESSON_TYPES, "room_types": m.ROOM_TYPES, "shifts": m.SHIFTS,
            "default_weights": m.DEFAULT_WEIGHTS}
