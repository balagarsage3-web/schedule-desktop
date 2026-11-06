"""Проверка готового расписания: жёсткие правила (конфликты) и мягкие (штрафы).

Пара потока хранится как несколько записей (по одной на группу) с одинаковыми датой,
парой и аудиторией; для преподавателя и аудитории такие записи — одна пара.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .expand import PLesson
from .problem import NO_TEACHER, WEEKDAYS, Problem, week_start

SOFT_LABELS = {
    "gaps": "«Окна» между парами у группы",
    "teacher_gaps": "«Окна» между парами у преподавателя",
    "group_day_limit": "Больше допустимого числа пар в день у группы",
    "even_days": "Неравномерное распределение по дням",
    "same_slot": "Дисциплина в одном и том же слоте в разные дни",
    "teacher_pref": "Не занято желательное время преподавателя",
    "room_changes": "Смены аудитории у группы в течение дня",
    "lecture_morning": "Лекция во второй половине дня",
    "stability": "Пара переехала относительно прошлой недели",
}

HARD_LABELS = {
    "teacher_clash": "Преподаватель ведёт две пары одновременно",
    "group_clash": "У группы две пары одновременно",
    "room_clash": "Аудитория занята двумя парами",
    "teacher_unavailable": "Пара вне доступного времени преподавателя",
    "room_unsuitable": "Аудитория не подходит по типу или вместимости",
    "count_mismatch": "Количество пар не совпадает с планом",
    "non_working": "Пара в нерабочий день",
    "shift": "Пара вне смены группы",
    "teacher_day_limit": "Превышен лимит пар преподавателя",
    "stream_split": "Общая пара потока стоит у групп по-разному",
}


def _fmt(ls: PLesson) -> str:
    return f"{ls.date:%d.%m} ({WEEKDAYS[ls.date.weekday()]}), {ls.slot_number}-я пара"


def _same(a: PLesson, b: PLesson) -> bool:
    return a is b or (a.id is not None and a.id == b.id)


def _sessions(p: Problem, lessons: list[PLesson]) -> dict[tuple[int, date, int], list[PLesson]]:
    """Пары как события: (занятие, дата, номер пары) -> записи групп."""
    out: dict[tuple[int, date, int], list[PLesson]] = defaultdict(list)
    for ls in lessons:
        out[p.unit_of[ls.cur_id].id, ls.date, ls.slot_number].append(ls)
    return out


def lesson_conflicts(p: Problem, ls: PLesson, others: list[PLesson]) -> list[dict]:
    """Конфликты одной пары (для потока — всей общей пары) относительно остальных (для ручной правки)."""
    u = p.unit_of[ls.cur_id]
    groups = set(u.group_ids)
    out = []
    rest = [o for o in others if not _same(o, ls) and p.unit_of[o.cur_id].id != u.id]
    seen = set()
    for o in rest:
        if o.date != ls.date or o.slot_number != ls.slot_number:
            continue
        ou = p.unit_of[o.cur_id]
        oc = p.cur_by_id[o.cur_id]
        if ou.teacher_id == u.teacher_id and u.teacher_id != NO_TEACHER and ("t", ou.id) not in seen:
            seen.add(("t", ou.id))
            out.append({"type": "teacher_clash", "message": f"Преподаватель {p.teachers[u.teacher_id].name} в это время "
                                                         f"ведёт {p.unit_label(ou)}."})
        if oc.group_id in groups:
            out.append({"type": "group_clash", "message": f"У группы {p.groups[oc.group_id].name} в это время уже "
                                                       f"стоит «{p.subjects[oc.subject_id].name}»."})
        if ls.room_id and o.room_id == ls.room_id and ("r", ou.id) not in seen:
            seen.add(("r", ou.id))
            out.append({"type": "room_clash", "message": f"Аудитория {p.rooms[ls.room_id].number} занята: "
                                                      f"{p.unit_label(ou)}."})
    out += _single_checks(p, ls)
    t = p.teachers[u.teacher_id]
    day_load = len({(p.unit_of[o.cur_id].id, o.slot_number) for o in rest
                    if o.date == ls.date and p.unit_of[o.cur_id].teacher_id == u.teacher_id}) + 1
    if day_load > t.max_per_day:
        out.append({"type": "teacher_day_limit", "message": f"У преподавателя {t.name} будет {day_load} пар в этот день "
                                                         f"при максимуме {t.max_per_day}."})
    return out


def _single_checks(p: Problem, ls: PLesson) -> list[dict]:
    u = p.unit_of[ls.cur_id]
    c = p.cur_by_id[ls.cur_id]
    t = p.teachers[u.teacher_id]
    out = []
    wd = ls.date.weekday()
    if u.teacher_id == NO_TEACHER:
        out.append({"type": "teacher_unavailable", "message": "Не назначен преподаватель."})
    if not p.is_study_day(ls.date):
        out.append({"type": "non_working", "message": f"{ls.date:%d.%m.%Y} — нерабочий день или вне периода."})
    if p.teacher_status(u.teacher_id, wd, ls.slot_number) == "unavailable":
        out.append({"type": "teacher_unavailable", "message": f"Преподаватель {t.name} недоступен "
                                                           f"в {WEEKDAYS[wd]} на {ls.slot_number}-й паре."})
    if ls.date in p.days_off.get(u.teacher_id, set()):
        out.append({"type": "teacher_unavailable", "message": f"У преподавателя {t.name} отгул {ls.date:%d.%m.%Y}."})
    if ls.slot_number not in p.group_slots(c.group_id):
        g = p.groups[c.group_id]
        out.append({"type": "shift", "message": f"{ls.slot_number}-я пара не входит в смену «{g.shift}» группы {g.name}."})
    if ls.room_id is None:
        out.append({"type": "room_unsuitable", "message": "Не назначена аудитория."})
    else:
        r = p.rooms.get(ls.room_id)
        subj = p.subjects[u.subject_id]
        if r is None or not r.active:
            out.append({"type": "room_unsuitable", "message": "Аудитория недоступна."})
        else:
            if r.room_type != subj.room_type:
                out.append({"type": "room_unsuitable", "message": f"Аудитория {r.number} — «{r.room_type}», "
                                                               f"а нужна «{subj.room_type}»."})
            if r.capacity < u.size:
                who = f"потоке {', '.join(p.groups[g].name for g in u.group_ids)}" if len(u.group_ids) > 1 \
                    else f"группе {p.groups[c.group_id].name}"
                out.append({"type": "room_unsuitable", "message": f"В аудитории {r.number} {r.capacity} мест, "
                                                               f"а в {who} {u.size} человек."})
    return out


def validate(p: Problem, lessons: list[PLesson]) -> list[dict]:
    """Все нарушения жёстких правил. Каждое — {type, message, lesson_ids}."""
    out: list[dict] = []
    sessions = _sessions(p, lessons)
    by_teacher, by_room = defaultdict(list), defaultdict(list)
    for (uid, d, n), ls_ in sessions.items():
        u = p.unit_by_id[uid]
        by_teacher[u.teacher_id, d, n].append(ls_)
        for room in {x.room_id for x in ls_ if x.room_id}:
            by_room[room, d, n].append([x for x in ls_ if x.room_id == room])
    for (tid, d, n), ss in by_teacher.items():
        if len(ss) > 1 and tid != NO_TEACHER:
            ids = [x.id for s in ss for x in s]
            out.append({"type": "teacher_clash", "lesson_ids": ids,
                        "message": f"Преподаватель {p.teachers[tid].name}: {len(ss)} пары одновременно, {_fmt(ss[0][0])}."})
    for (rid, d, n), ss in by_room.items():
        if len(ss) > 1:
            out.append({"type": "room_clash", "lesson_ids": [x.id for s in ss for x in s],
                        "message": f"Аудитория {p.rooms[rid].number}: {len(ss)} пары одновременно, {_fmt(ss[0][0])}."})
    by_group = defaultdict(list)
    for ls in lessons:
        by_group[p.cur_by_id[ls.cur_id].group_id, ls.date, ls.slot_number].append(ls)
    for (gid, d, n), ls_ in by_group.items():
        if len(ls_) > 1:
            out.append({"type": "group_clash", "lesson_ids": [x.id for x in ls_],
                        "message": f"Группа {p.groups[gid].name}: {len(ls_)} пары одновременно, {_fmt(ls_[0])}."})
    for ls in lessons:
        for issue in _single_checks(p, ls):
            issue["lesson_ids"] = [ls.id]
            issue["message"] = f"{p.cur_label(p.cur_by_id[ls.cur_id])}, {_fmt(ls)}: {issue['message']}"
            out.append(issue)

    # Поток: у всех групп общая пара должна стоять в одно время и в одной аудитории.
    for (uid, d, n), ls_ in sessions.items():
        u = p.unit_by_id[uid]
        if len(u.cur_ids) < 2:
            continue
        present = {x.cur_id for x in ls_}
        missing = [p.groups[p.cur_by_id[c].group_id].name for c in u.cur_ids if c not in present]
        rooms = {x.room_id for x in ls_}
        if missing or len(rooms) > 1:
            why = f"нет у групп {', '.join(missing)}" if missing else "группы в разных аудиториях"
            out.append({"type": "stream_split", "lesson_ids": [x.id for x in ls_],
                        "message": f"{p.unit_label(u)}, {_fmt(ls_[0])}: общая пара разделена — {why}."})

    tday = defaultdict(set)
    tweek = defaultdict(set)
    for (uid, d, n) in sessions:
        tid = p.unit_by_id[uid].teacher_id
        tday[tid, d].add((uid, n))
        tweek[tid, week_start(d)].add((uid, d, n))
    for (tid, d), s in tday.items():
        t = p.teachers[tid]
        if len(s) > t.max_per_day and tid != NO_TEACHER:
            out.append({"type": "teacher_day_limit", "lesson_ids": [],
                        "message": f"Преподаватель {t.name}: {len(s)} пар {d:%d.%m.%Y} при максимуме {t.max_per_day}."})
    for (tid, wk), s in tweek.items():
        t = p.teachers[tid]
        if len(s) > t.max_per_week and tid != NO_TEACHER:
            out.append({"type": "teacher_day_limit", "lesson_ids": [],
                        "message": f"Преподаватель {t.name}: {len(s)} пар в неделю с {wk:%d.%m} при максимуме {t.max_per_week}."})

    # Количество пар за период — как в плане (по КУГ или «пар всего» с учётом сроков).
    total = defaultdict(int)
    for ls in lessons:
        total[ls.cur_id] += 1
    for c in p.curriculum:
        need = p.expected_total(c.id)
        if total[c.id] != need and (need or total[c.id]):
            out.append({"type": "count_mismatch", "lesson_ids": [],
                        "message": f"{p.cur_label(c)}, группа {p.groups[c.group_id].name}: поставлено "
                                   f"{total[c.id]} пар из {need}."})
    return out


def _gaps(nums: list[int]) -> int:
    nums = sorted(set(nums))
    return (nums[-1] - nums[0] + 1) - len(nums) if nums else 0


def soft_report(p: Problem, lessons: list[PLesson]) -> dict:
    """Число нарушений мягких правил за весь период и итоговый штраф."""
    counts = {k: 0 for k in SOFT_LABELS}
    half = (len(p.slots) + 1) // 2
    study_by_week: dict[date, set[int]] = defaultdict(set)
    for d in p.term_dates():
        if p.is_study_day(d):
            study_by_week[week_start(d)].add(d.weekday())

    gday: dict[tuple[int, date], list[PLesson]] = defaultdict(list)
    for ls in lessons:
        gday[p.cur_by_id[ls.cur_id].group_id, ls.date].append(ls)
    gweek_loads: dict[tuple[int, date], dict[date, int]] = defaultdict(dict)
    for (gid, d), ls_ in gday.items():
        ls_.sort(key=lambda x: x.slot_number)
        counts["gaps"] += _gaps([x.slot_number for x in ls_])
        counts["group_day_limit"] += max(0, len(ls_) - p.group_day_limit)
        counts["room_changes"] += sum(1 for a, b in zip(ls_, ls_[1:]) if a.room_id != b.room_id)
        gweek_loads[gid, week_start(d)][d] = len(ls_)
    # Неравномерность: разброс нагрузки группы по учебным дням недели (разница в одну пару допустима).
    for (gid, wk), loads in gweek_loads.items():
        by_wd = {d.weekday(): v for d, v in loads.items()}
        vals = [by_wd.get(wd, 0) for wd in study_by_week[wk]]
        if len(vals) > 1:
            counts["even_days"] += max(0, max(vals) - min(vals) - 1)

    sessions = _sessions(p, lessons)
    uweek: dict[tuple[int, date], list[tuple[date, int]]] = defaultdict(list)
    tday: dict[tuple[int, date], list[int]] = defaultdict(list)
    tweek: dict[tuple[int, date], list[tuple[date, int]]] = defaultdict(list)
    for (uid, d, n) in sessions:
        u = p.unit_by_id[uid]
        uweek[uid, week_start(d)].append((d, n))
        tday[u.teacher_id, d].append(n)
        tweek[u.teacher_id, week_start(d)].append((d, n))
        if p.subjects[u.subject_id].lesson_type == "лекция" and n > half:
            counts["lecture_morning"] += 1
    for (uid, wk), items in uweek.items():
        per_day, per_slot = defaultdict(int), defaultdict(int)
        for d, n in items:
            per_day[d] += 1
            per_slot[n] += 1
        ndays = max(1, len(study_by_week[wk]))
        ok = -(-len(items) // ndays)  # при большой нагрузке несколько пар в день неизбежны
        counts["even_days"] += sum(v - ok for v in per_day.values() if v > ok)
        if 2 <= len(items) <= ndays:
            counts["same_slot"] += sum(v - 1 for v in per_slot.values() if v > 1)
    # Стабильность: пары, которые стоят не там, где неделей раньше (по дню недели и номеру пары).
    by_week: dict[date, set] = defaultdict(set)
    for (uid, d, n) in sessions:
        by_week[week_start(d)].add((uid, d.weekday(), n))
    weeks_sorted = sorted(by_week)
    for a, b in zip(weeks_sorted, weeks_sorted[1:]):
        prev_units = {k[0] for k in by_week[a]}
        counts["stability"] += sum(1 for k in by_week[b] if k[0] in prev_units and k not in by_week[a])
    for nums in tday.values():
        counts["teacher_gaps"] += _gaps(nums)
    # Пожелания: сколько желательных слотов недели осталось незанятыми, хотя пар хватало.
    for (tid, wk), items in tweek.items():
        if not p.teacher_has_preferences(tid):
            continue
        npref = sum(1 for (wd, _), st in p.availability.get(tid, {}).items()
                    if st == "preferred" and wd in study_by_week[wk])
        used = sum(1 for d, n in items if p.teacher_status(tid, d.weekday(), n) == "preferred")
        counts["teacher_pref"] += max(0, min(len(items), npref) - used)

    score = sum(counts[k] * int(p.weights.get(k, 0)) for k in counts)
    items = [{"key": k, "label": SOFT_LABELS[k], "count": counts[k], "weight": int(p.weights.get(k, 0)),
              "penalty": counts[k] * int(p.weights.get(k, 0))} for k in SOFT_LABELS]
    return {"score": score, "items": items}


def load_report(p: Problem, lessons: list[PLesson]) -> dict:
    """Загрузка преподавателей и аудиторий (в среднем за учебную неделю)."""
    weeks = {week_start(d) for d in p.term_dates() if p.is_study_day(d)} or {p.start_date}
    nweeks = len(weeks)
    t_cnt, r_cnt = defaultdict(int), defaultdict(int)
    for (uid, d, n), ls_ in _sessions(p, lessons).items():
        t_cnt[p.unit_by_id[uid].teacher_id] += 1
        for room in {x.room_id for x in ls_ if x.room_id}:
            r_cnt[room] += 1
    cells = len(p.days) * len(p.slots) or 1
    teachers = [{"name": t.name, "per_week": round(t_cnt[t.id] / nweeks, 1), "max_per_week": t.max_per_week,
                 "total": t_cnt[t.id]} for t in p.teachers.values()]
    rooms = [{"name": r.number, "type": r.room_type, "per_week": round(r_cnt[r.id] / nweeks, 1),
              "utilization": round(100 * r_cnt[r.id] / nweeks / cells)} for r in p.rooms.values() if r.active]
    teachers.sort(key=lambda x: -x["per_week"])
    rooms.sort(key=lambda x: -x["utilization"])
    return {"weeks": nweeks, "teachers": teachers, "rooms": rooms}
