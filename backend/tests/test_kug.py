"""Импорт КУГ из реальных шаблонов колледжа (папка «куг» рядом с проектом)."""
from datetime import date, time
from pathlib import Path

import pytest

from app import models as m
from app.kug import parse_kug
from app.solver.expand import PLesson
from app.solver.jobs import Job, run_pipeline
from app.solver.problem import load_problem, weekly_pairs
from app.solver.validate import validate

KUG_DIR = Path(__file__).resolve().parents[2] / "куг"
GD = next(iter(sorted(KUG_DIR.glob("*ГД*.xlsx"))), None) if KUG_DIR.exists() else None
pytestmark = pytest.mark.skipif(GD is None, reason="нет файлов КУГ в папке «куг»")


def test_parse_dates_follow_month_days_not_week_numbers():
    data = parse_kug(GD.read_bytes())
    assert "Графический дизайнер" in data["profession"]
    sheets = {s["title"]: s for s in data["sheets"]}
    # IV курс: в шаблоне «неделя 36», но по числам месяца первая неделя — 30.08–05.09.2027.
    iv = sheets["IV курс"]
    assert iv["weeks"][0]["monday"] == date(2027, 8, 30)
    assert iv["vacation"] == [date(2027, 12, 27), date(2028, 1, 3)]
    i = sheets["I курс"]
    rus = next(r for r in i["rows"] if r["name"] == "Русский язык")
    assert rus["total"] == 102 and rus["kind"] == "class"
    # Физика начинается только во втором полугодии.
    phys = next(r for r in i["rows"] if r["name"] == "Физика")
    assert min(phys["hours"]) >= date(2025, 1, 1)


def test_odd_hours_accumulate_into_pairs():
    pairs = weekly_pairs({"2025-09-01": 3, "2025-09-08": 3, "2025-09-15": 1, "2025-09-22": 1})
    assert list(pairs.values()) == [1, 2, 1] and sum(pairs.values()) == 4


def _setup(db):
    for n, (h, mi) in enumerate([(9, 0), (10, 40), (12, 40), (14, 20), (16, 0), (17, 40)], start=1):
        db.add(m.TimeSlot(number=n, start=time(h, mi), end=time(h + 1, (mi + 30) % 60)))
    for i in range(8):
        db.add(m.Room(number=f"1{i:02d}", capacity=30, room_type="обычная"))
    for i in range(5):
        db.add(m.Room(number=f"2{i:02d}", capacity=30, room_type="компьютерный класс"))
    g1 = m.Group(name="ГД-11", size=25, shift="утро")
    g2 = m.Group(name="ГД-12", size=24, shift="утро")
    db.add_all([g1, g2])
    db.commit()
    return g1, g2


def test_import_kug_and_generate_semester(client, db):
    g1, g2 = _setup(db)
    files = {"file": (GD.name, GD.read_bytes(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    prev = client.post("/api/kug/parse", files=files).json()
    first = next(s for s in prev["sheets"] if s["title"] == "I курс")
    assert first["year"] == "2024-2025" and len(first["semesters"]) == 2

    r = client.post("/api/kug/import", files=files,
                    data={"sheet": first["index"], "group_ids": f"{g1.id},{g2.id}", "create_terms": "true"}).json()
    assert r["ok"] and r["created"] == 40 and len(r["terms_created"]) == 2

    # Преподаватели не назначены — генерация должна это назвать.
    term = db.query(m.Term).filter(m.Term.name.like("%1-е полугодие")).one()
    pre = client.get(f"/api/terms/{term.id}/precheck").json()
    assert not pre["ok"] and any("не назначен преподаватель" in i["message"] for i in pre["issues"])

    # Массовое назначение: по преподавателю на дисциплину, обеим группам сразу.
    rows = client.get("/api/curriculum").json()
    by_subject: dict[int, list[int]] = {}
    for row in rows:
        by_subject.setdefault(row["subject_id"], []).append(row["id"])
    for k, (sid, ids) in enumerate(by_subject.items()):
        t = client.post("/api/teachers", json={"full_name": f"Преподаватель {k:02d}", "max_per_week": 30}).json()
        assert client.post("/api/curriculum/assign-teacher", json={"ids": ids, "teacher_id": t["id"]}).json()["updated"] == 2

    db.expire_all()
    p = load_problem(db, term.id)
    job = Job(id="k", term_id=term.id, time_limit=60)
    run_pipeline(p, job, db)
    assert job.status == "done", (job.message, [i for i in job.issues if i["level"] == "error"])
    lessons = [PLesson(x.curriculum_id, x.date, p.slot_by_id[x.slot_id].number, x.room_id, x.id)
               for x in db.query(m.Lesson).filter_by(version_id=job.version_id).all()]
    assert validate(p, lessons) == []
    # Русский язык в 1-м полугодии: 34 часа по КУГ = 17 пар у каждой группы, неделя в неделю.
    rus = next(c for c in p.curriculum if p.subjects[c.subject_id].name == "Русский язык" and c.group_id == g1.id)
    assert sum(1 for ls in lessons if ls.cur_id == rus.id) == 17
    # Физики в 1-м полугодии нет — ни одной пары.
    phys = next(c for c in p.curriculum if p.subjects[c.subject_id].name == "Физика" and c.group_id == g1.id)
    assert not [ls for ls in lessons if ls.cur_id == phys.id]
    # Каникулы (30.12–12.01) — без пар.
    assert not [ls for ls in lessons if date(2024, 12, 30) <= ls.date <= date(2025, 1, 12)]


def test_weekly_edit_recalculates_totals(client, db):
    g1, _ = _setup(db)
    s = client.post("/api/subjects", json={"name": "Химия", "lesson_type": "практика", "room_type": "обычная"}).json()
    c = client.post("/api/curriculum", json={"group_id": g1.id, "subject_id": s["id"], "total": 10, "per_week": 2}).json()
    r = client.put(f"/api/curriculum/{c['id']}/weekly", json={"weekly": {"2026-09-07": 4, "2026-09-14": 6}}).json()
    assert r["has_kug"] and r["total"] == 5 and r["per_week"] == 3
