"""Фоновая генерация расписания (встроенная очередь на потоках)."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field

from .. import models as m
from ..db import SessionLocal
from .expand import schedule_term
from .precheck import precheck
from .problem import Problem, load_problem
from .validate import soft_report, validate


@dataclass
class Job:
    id: str
    term_id: int
    time_limit: int
    status: str = "queued"   # queued|precheck|solving|saving|done|invalid|infeasible|timeout|stopped|failed
    started: float = field(default_factory=time.time)
    finished: float | None = None
    issues: list = field(default_factory=list)
    hints: list = field(default_factory=list)
    message: str = ""
    version_id: int | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    solve_started: float | None = None

    weeks_done: int = 0
    weeks_total: int = 0

    def to_dict(self) -> dict:
        now = self.finished or time.time()
        progress = 0
        if self.status in ("done", "invalid", "infeasible", "timeout", "stopped", "failed"):
            progress = 100
        elif self.weeks_total:
            progress = min(99, int(100 * self.weeks_done / self.weeks_total))
        return {
            "id": self.id, "term_id": self.term_id, "status": self.status, "progress": progress,
            "elapsed": round(now - self.started, 1), "time_limit": self.time_limit,
            "weeks_done": self.weeks_done, "weeks_total": self.weeks_total,
            "issues": self.issues, "hints": self.hints, "message": self.message, "version_id": self.version_id,
        }


def save_version(db, term_id: int, p: Problem, lessons, extra_report: dict | None = None,
                 name: str | None = None) -> m.ScheduleVersion:
    number = (db.query(m.ScheduleVersion).filter_by(term_id=term_id).count() or 0) + 1
    soft = soft_report(p, lessons)
    hard = validate(p, lessons)
    report = {"soft": soft, "hard_count": len(hard), **(extra_report or {})}
    v = m.ScheduleVersion(term_id=term_id, number=number, name=name or f"Версия {number}",
                          score=soft["score"], report=report)
    db.add(v)
    db.flush()
    slot_id = {s.number: s.id for s in p.slots}
    db.bulk_save_objects([
        m.Lesson(version_id=v.id, curriculum_id=ls.cur_id, date=ls.date, slot_id=slot_id[ls.slot_number],
                 room_id=ls.room_id, pinned=ls.pinned)
        for ls in lessons
    ])
    db.commit()
    return v


def run_pipeline(p: Problem, job: Job, db=None) -> None:
    job.status = "precheck"
    job.issues = precheck(p)
    if any(i["level"] == "error" for i in job.issues):
        job.status = "invalid"
        job.message = "Данные противоречивы — расчёт невозможен. Исправьте ошибки из списка."
        return

    def on_progress(done, total):
        job.weeks_done, job.weeks_total = done, total

    job.status = "solving"
    job.solve_started = time.time()
    res = schedule_term(p, job.time_limit, on_progress=on_progress, stop_event=job.stop_event)

    job.status = "saving"
    status = "optimal" if res.solved and res.optimal == res.solved else "feasible"
    extra = {"solver_status": "stopped" if res.stopped else status,
             "solver_time": round(time.time() - job.solve_started, 1),
             "weeks": res.weeks, "weeks_solved": res.solved, "weeks_optimal": res.optimal,
             "expand_problems": res.problems}
    if db is not None:
        v = save_version(db, job.term_id, p, res.lessons, extra)
        job.version_id = v.id
    job.status = "done"
    job.message = (f"Расставлено недель: {res.weeks} (решено заново {res.solved}, из них оптимально {res.optimal}). "
                   + ("Расчёт остановлен — оставшиеся недели достроены быстро. " if res.stopped else ""))
    if res.problems:
        job.message += "Есть недопоставленные пары — см. отчёт."


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def active(self) -> Job | None:
        for j in self.jobs.values():
            if j.status in ("queued", "precheck", "solving", "saving"):
                return j
        return None

    def start(self, term_id: int, time_limit: int) -> Job:
        with self.lock:
            if self.active():
                raise RuntimeError("Генерация уже идёт")
            job = Job(id=uuid.uuid4().hex, term_id=term_id, time_limit=time_limit)
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job):
        db = SessionLocal()
        try:
            p = load_problem(db, job.term_id)
            run_pipeline(p, job, db)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.status = "failed"
            job.message = f"Ошибка при расчёте: {e}"
        finally:
            job.finished = time.time()
            db.close()


manager = JobManager()
