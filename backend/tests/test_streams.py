"""Общие пары (потоки) и минимизация окон."""
from collections import defaultdict

from app import models as m
from app.seed import seed
from app.solver.expand import PLesson
from app.solver.jobs import Job, run_pipeline
from app.solver.precheck import precheck
from app.solver.problem import load_problem
from app.solver.validate import soft_report, validate


def _run(db, n=9, limit=30):
    term = seed(db, n)
    p = load_problem(db, term.id)
    job = Job(id="s", term_id=term.id, time_limit=limit)
    run_pipeline(p, job, db)
    lessons = [PLesson(x.curriculum_id, x.date, p.slot_by_id[x.slot_id].number, x.room_id, x.id)
               for x in db.query(m.Lesson).filter_by(version_id=job.version_id).all()]
    return p, job, lessons


def test_stream_is_one_shared_lesson(db):
    p, job, lessons = _run(db)
    assert job.status == "done", job.message
    streams = [u for u in p.units if len(u.group_ids) > 1]
    assert streams, "в демо-данных должны быть потоки"
    assert validate(p, lessons) == []
    by_cur = defaultdict(set)
    rooms = defaultdict(set)
    for ls in lessons:
        by_cur[ls.cur_id].add((ls.date, ls.slot_number))
        rooms[p.unit_of[ls.cur_id].id, ls.date, ls.slot_number].add(ls.room_id)
    for u in streams:
        times = [by_cur[c] for c in u.cur_ids]
        assert all(t == times[0] for t in times), "у групп потока пары должны совпадать по времени"
        for d, n in times[0]:
            (room,) = rooms[u.id, d, n]  # одна аудитория на весь поток
            assert p.rooms[room].capacity >= u.size


def test_no_group_gaps_in_typical_week(db):
    p, job, lessons = _run(db)
    # Окна в семестре могут появиться только из-за переносов с праздников — единицы на весь период.
    gaps = next(i for i in soft_report(p, lessons)["items"] if i["key"] == "gaps")
    assert gaps["count"] <= len(p.groups)


def test_stream_mismatch_reported(db):
    term = seed(db, 6)
    row = db.query(m.Curriculum).filter(m.Curriculum.stream != "").first()
    row.per_week += 1
    db.commit()
    msgs = [i["message"] for i in precheck(load_problem(db, term.id)) if i["level"] == "error"]
    assert any("Поток" in x and "пар в неделю" in x for x in msgs), msgs


def test_moving_stream_moves_all_groups(client, db):
    p, job, lessons = _run(db, 6, 20)
    u = next(u for u in p.units if len(u.group_ids) > 1)
    src = next(ls for ls in lessons if ls.cur_id == u.cur_ids[0])
    r = client.post(f"/api/lessons/{src.id}/move",
                    json={"date": src.date.isoformat(), "slot_number": src.slot_number, "dry_run": True})
    assert r.status_code == 200
    # Перенос в тот же слот — без конфликтов и затрагивает все группы потока.
    assert r.json()["count"] == len(u.group_ids)
