"""Демонстрационные данные: колледж с n_groups группами.

Запуск: python -m app.seed [число_групп]
"""
from __future__ import annotations

import random
import sys
from datetime import date, time

from . import models as m
from .db import Base, SessionLocal, engine

SLOTS = [(1, time(9, 0), time(10, 30)), (2, time(10, 40), time(12, 10)), (3, time(12, 40), time(14, 10)),
         (4, time(14, 20), time(15, 50)), (5, time(16, 0), time(17, 30)), (6, time(17, 40), time(19, 10))]

# (название, тип занятия, тип аудитории, пар в неделю)
PLAN = [
    ("Информатика", "лекция", "обычная", 1),
    ("Информатика", "практика", "компьютерный класс", 1),
    ("Математика", "лекция", "обычная", 1),
    ("Математика", "практика", "обычная", 2),
    ("Программирование", "лекция", "обычная", 1),
    ("Программирование", "практика", "компьютерный класс", 2),
    ("Физика", "лекция", "обычная", 1),
    ("Физика", "лаба", "лаборатория", 1),
    ("Английский язык", "практика", "обычная", 2),
    ("История", "лекция", "обычная", 1),
    ("Базы данных", "практика", "компьютерный класс", 1),
]

# Лекции, которые читаются потоком (общая пара для нескольких групп).
STREAM_SUBJECTS = {("История", "лекция"), ("Физика", "лекция")}

LAST = ["Иванов", "Петрова", "Сидоров", "Кузнецова", "Смирнов", "Попова", "Васильев", "Соколова", "Михайлов",
        "Новикова", "Фёдоров", "Морозова", "Волков", "Алексеева", "Лебедев", "Семёнова", "Егоров", "Павлова",
        "Козлов", "Степанова", "Николаев", "Орлова", "Андреев", "Макарова", "Захаров", "Зайцева", "Борисов",
        "Яковлева", "Григорьев", "Романова", "Воробьёв", "Сергеева", "Кузьмин", "Фролова", "Александров",
        "Дмитриева", "Королёв", "Гусева", "Киселёв", "Ильина"]
INIT = ["А.А.", "Б.В.", "В.Г.", "Г.Д.", "Д.Е.", "Е.Ж.", "И.К.", "К.Л.", "Л.М.", "М.Н.", "Н.О.", "О.П."]


def seed(db, n_groups: int = 12, rng_seed: int = 7, wipe: bool = True) -> m.Term:
    rng = random.Random(rng_seed)
    if wipe:
        for model in (m.Lesson, m.ScheduleVersion, m.NonWorkingDay, m.Term, m.TimeSlot, m.Curriculum,
                      m.TeacherDayOff, m.TeacherAvailability, m.Room):
            db.query(model).delete()
        db.execute(m.teacher_subjects.delete())
        db.query(m.Teacher).delete()
        db.query(m.Subject).delete()
        db.query(m.Group).delete()
        db.commit()

    for n, s, e in SLOTS:
        db.add(m.TimeSlot(number=n, start=s, end=e))
    term = m.Term(name="Осенний семестр 2026", start_date=date(2026, 9, 1), end_date=date(2026, 12, 31),
                  days_per_week=5, time_limit=60, group_day_limit=4, weights=dict(m.DEFAULT_WEIGHTS),
                  shift_slots={"утро": [1, 2, 3, 4], "день": [3, 4, 5, 6], "вечер": [5, 6]})
    db.add(term)
    db.flush()
    db.add(m.NonWorkingDay(term_id=term.id, date=date(2026, 11, 4), reason="День народного единства"))

    subjects = []
    for name, ltype, rtype, _ in PLAN:
        s = m.Subject(name=name, lesson_type=ltype, room_type=rtype)
        db.add(s)
        subjects.append(s)

    groups = []
    directions = [("ИС", "Информационные системы"), ("ПО", "Программное обеспечение"), ("СА", "Сетевое администрирование")]
    for i in range(n_groups):
        code, direction = directions[i % len(directions)]
        course = 1 + (i // len(directions)) % 3
        g = m.Group(name=f"{code}-{course}{i // 9 + 1}", course=f"{course} курс, {direction}", size=rng.randint(18, 28),
                    shift="утро" if i % 3 != 2 else "день")
        db.add(g)
        groups.append(g)
    db.flush()

    # Преподаватели: по каждой дисциплине (по названию) — столько, чтобы нагрузка была не выше ~16 пар.
    load_by_name: dict[str, int] = {}
    for name, _, _, pw in PLAN:
        load_by_name[name] = load_by_name.get(name, 0) + pw * n_groups
    teachers_by_name: dict[str, list[m.Teacher]] = {}
    names = iter(f"{last} {INIT[i % len(INIT)]}" for i, last in enumerate(LAST * 5))
    for name, load in load_by_name.items():
        cnt = max(1, -(-load // 12))
        lst = []
        for _ in range(cnt):
            t = m.Teacher(full_name=next(names), max_per_day=4, max_per_week=18)
            t.subjects = [s for s in subjects if s.name == name]
            db.add(t)
            lst.append(t)
        teachers_by_name[name] = lst
    db.flush()

    # Потоки: общие лекции для 2–3 групп одного курса и одной смены.
    by_course: dict[tuple[str, str], list[int]] = {}
    for gi, g in enumerate(groups):
        by_course.setdefault((g.course.split(",")[0], g.shift), []).append(gi)
    stream_of: dict[int, tuple[str, int]] = {}  # индекс группы -> (метка, номер потока)
    n_streams = 0
    for (course, shift), idxs in by_course.items():
        for k in range(0, len(idxs), 3):
            chunk = idxs[k:k + 3]
            if len(chunk) < 2:
                continue
            n_streams += 1
            for gi in chunk:
                stream_of[gi] = (f"{course}, {shift}, поток {k // 3 + 1}", n_streams)

    # Учебный план: дисциплину (лекцию и практику) у группы ведёт один преподаватель.
    for gi, g in enumerate(groups):
        for s, (_, _, _, pw) in zip(subjects, PLAN):
            lst = teachers_by_name[s.name]
            stream = ""
            t = lst[gi % len(lst)]
            if (s.name, s.lesson_type) in STREAM_SUBJECTS and gi in stream_of:
                label, num = stream_of[gi]
                stream = f"{s.name}: {label}"
                t = lst[num % len(lst)]
            db.add(m.Curriculum(group_id=g.id, subject_id=s.id, teacher_id=t.id, total=pw * 16, per_week=pw,
                                stream=stream))

    # Доступность по мотивам примера из ТЗ: первый преподаватель информатики доступен только пн/ср/пт, 1–4 пары.
    ivanov = teachers_by_name["Информатика"][0]
    for wd in range(5):
        for n, *_ in SLOTS:
            ok = wd in (0, 2, 4) and n <= 4
            db.add(m.TeacherAvailability(teacher_id=ivanov.id, weekday=wd, slot_number=n,
                                         status="available" if ok else "unavailable"))
    all_t = [t for lst in teachers_by_name.values() for t in lst if t.id != ivanov.id]
    for t in rng.sample(all_t, k=min(len(all_t), max(2, len(all_t) // 4))):
        off_day = rng.randrange(5)
        pref_day = (off_day + 2) % 5
        for n, *_ in SLOTS:
            db.add(m.TeacherAvailability(teacher_id=t.id, weekday=off_day, slot_number=n, status="unavailable"))
            if n <= 3:
                db.add(m.TeacherAvailability(teacher_id=t.id, weekday=pref_day, slot_number=n, status="preferred"))
    db.add(m.TeacherDayOff(teacher_id=all_t[0].id, date=date(2026, 10, 14), reason="Повышение квалификации"))

    # Аудитории с запасом под нагрузку.
    def rooms_needed(rtype: str) -> int:
        need = sum(pw for _, _, rt, pw in PLAN if rt == rtype) * n_groups
        return max(2, -(-need // 16))
    idx = 100
    for rtype, cap in (("обычная", 30), ("компьютерный класс", 30), ("лаборатория", 30)):
        for _ in range(rooms_needed(rtype)):
            idx += 1
            db.add(m.Room(number=str(idx), capacity=cap, room_type=rtype))
    # Лекционные залы под потоки.
    stream_lessons = n_streams * sum(pw for name, lt, _, pw in PLAN if (name, lt) in STREAM_SUBJECTS)
    for k in range(max(1, -(-stream_lessons // 12))):
        db.add(m.Room(number=f"Лекционный зал {k + 1}", capacity=90, room_type="обычная"))
    db.commit()
    return term


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        t = seed(s, int(sys.argv[1]) if len(sys.argv) > 1 else 12)
        print(f"Демо-данные загружены: {t.name}")
