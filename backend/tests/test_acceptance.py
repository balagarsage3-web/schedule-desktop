"""Критерии приёмки MVP из раздела 12 ТЗ."""
import io
import time
from datetime import date

from openpyxl import load_workbook

from app import models as m
from app.seed import seed
from app.solver.expand import PLesson
from app.solver.jobs import Job, run_pipeline
from app.solver.precheck import precheck
from app.solver.problem import load_problem
from app.solver.validate import validate


def _generate(db, n_groups=18, time_limit=60):
    term = seed(db, n_groups)
    p = load_problem(db, term.id)
    job = Job(id="t", term_id=term.id, time_limit=time_limit)
    t0 = time.time()
    run_pipeline(p, job, db)
    return term, p, job, time.time() - t0


def _lessons(db, p, version_id):
    return [PLesson(x.curriculum_id, x.date, p.slot_by_id[x.slot_id].number, x.room_id, x.id)
            for x in db.query(m.Lesson).filter_by(version_id=version_id).all()]


def test_real_size_builds_fast_without_hard_violations(db):
    term, p, job, elapsed = _generate(db, 18)
    assert len(p.groups) >= 10 and len(p.teachers) >= 20
    assert job.status == "done", (job.message, job.issues)
    assert elapsed < 120
    lessons = _lessons(db, p, job.version_id)
    assert validate(p, lessons) == []
    # Все пары по плану поставлены, ни одной — в праздник.
    assert len(lessons) == sum(c.total for c in p.curriculum)
    assert not [ls for ls in lessons if ls.date == date(2026, 11, 4)]
    # Пары каждого преподавателя — только в его доступное время.
    for ls in lessons:
        c = p.cur_by_id[ls.cur_id]
        assert p.teacher_status(c.teacher_id, ls.date.weekday(), ls.slot_number) != "unavailable"


def test_contradictory_data_named_reason(db):
    term = seed(db, 6)
    t = db.query(m.Teacher).filter(m.Teacher.full_name.like("Иванов%")).first()
    db.query(m.TeacherAvailability).filter_by(teacher_id=t.id).delete()
    for wd in range(5):
        for n in range(1, 7):
            if not (wd == 0 and n <= 2):
                db.add(m.TeacherAvailability(teacher_id=t.id, weekday=wd, slot_number=n, status="unavailable"))
    db.commit()
    issues = precheck(load_problem(db, term.id))
    msgs = [i["message"] for i in issues if i["level"] == "error"]
    assert any(t.full_name in msg and "при доступности 2 слотов" in msg for msg in msgs), msgs


def test_rooms_shortage_named(db):
    term = seed(db, 6)
    db.query(m.Room).filter_by(room_type="лаборатория").delete()
    db.commit()
    msgs = [i["message"] for i in precheck(load_problem(db, term.id)) if i["level"] == "error"]
    assert any("лаборатория" in msg for msg in msgs), msgs


def test_drag_into_busy_slot_is_blocked_with_reason(client, db):
    term, p, job, _ = _generate(db, 6, 20)
    lessons = sorted(_lessons(db, p, job.version_id), key=lambda x: (x.date, x.slot_number))
    a = lessons[0]
    group = p.cur_by_id[a.cur_id].group_id
    b = next(x for x in lessons if x.id != a.id and p.cur_by_id[x.cur_id].group_id == group
             and x.date != a.date)
    r = client.post(f"/api/lessons/{a.id}/move", json={"date": b.date.isoformat(), "slot_number": b.slot_number})
    body = r.json()
    assert r.status_code == 200 and body["applied"] is False
    assert any("У группы" in msg for c in body["conflicts"] for msg in c["messages"])
    # Принудительный перенос сохраняется, и пара подсвечивается конфликтной.
    r = client.post(f"/api/lessons/{a.id}/move",
                    json={"date": b.date.isoformat(), "slot_number": b.slot_number, "force": True})
    assert r.json()["applied"] is True
    data = client.get(f"/api/versions/{job.version_id}/lessons",
                      params={"start": b.date.isoformat(), "end": b.date.isoformat()}).json()
    moved = next(x for x in data["lessons"] if x["id"] == a.id)
    assert moved["conflicts"]


def test_export_contains_all_group_lessons(client, db):
    term, p, job, _ = _generate(db, 4, 20)
    gid = next(iter(p.groups))
    expected = sum(1 for ls in _lessons(db, p, job.version_id) if p.cur_by_id[ls.cur_id].group_id == gid)
    r = client.get(f"/api/export/{job.version_id}/xlsx", params={"mode": "group", "entity_id": gid})
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content)).active
    rows = [row for row in ws.iter_rows(min_row=7, values_only=True) if row[0] and row[2]]
    assert len(rows) == expected
    head = " ".join(str(ws.cell(i, 1).value) for i in range(1, 5))
    assert "Период" in head and "Версия" in head and "Дата формирования" in head

    r = client.get(f"/api/export/{job.version_id}/pdf", params={"mode": "group", "entity_id": gid})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    r = client.get(f"/api/export/{job.version_id}/ics", params={"mode": "group", "entity_id": gid})
    assert r.status_code == 200 and r.text.count("BEGIN:VEVENT") == expected


def test_import_reports_row_and_reason(client):
    csv_text = "Название;Курс/направление;Численность;Смена\nИС-11;1 курс;25;утро\nИС-12;1 курс;много;утро\n" \
               "ИС-13;1 курс;20;ночь\nИС-11;1 курс;25;утро\n"
    r = client.post("/api/import/groups", files={"file": ("groups.csv", csv_text.encode("utf-8"), "text/csv")})
    body = r.json()
    assert body["ok"] is False
    rows = {e["row"]: e["message"] for e in body["errors"]}
    assert set(rows) == {3, 4, 5}
    assert "не число" in rows[3] and "Смена" in rows[4] and "Повтор" in rows[5]
    assert client.get("/api/groups").json() == []  # при ошибках ничего не сохраняется

    good = "Название;Курс/направление;Численность;Смена\nИС-11;1 курс;25;утро\n"
    r = client.post("/api/import/groups", files={"file": ("groups.csv", good.encode("utf-8"), "text/csv")})
    assert r.json()["created"] == 1


def test_auth_required(db):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/groups").status_code == 401
        assert c.post("/api/auth/login", json={"login": "admin", "password": "wrong"}).status_code == 401


def test_generation_via_api_with_stop(client, db):
    term = seed(db, 4)
    r = client.post("/api/generate", json={"term_id": term.id, "time_limit": 20})
    assert r.status_code == 200
    job_id = r.json()["id"]
    for _ in range(300):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] not in ("queued", "precheck", "solving", "saving"):
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    rep = client.get(f"/api/versions/{j['version_id']}/report").json()
    assert rep["hard"]["count"] == 0
    assert {i["key"] for i in rep["soft"]["items"]} >= {"gaps", "group_day_limit"}
