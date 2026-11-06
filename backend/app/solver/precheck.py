"""Проверка совместимости данных до запуска решателя.

Возвращает список проблем с конкретными причинами. Ошибки (level=error) делают
расчёт заведомо невозможным, предупреждения (warning) — нет. Нагрузка проверяется
по каждой неделе: по КУГ она меняется от недели к неделе.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .problem import NO_TEACHER, WEEKDAYS_IN, Problem, Unit


def _issue(level: str, message: str, kind: str = "") -> dict:
    return {"level": level, "kind": kind, "message": message}


def teacher_free_cells(p: Problem, teacher_id: int) -> list[tuple[int, int]]:
    return [(d, n) for d in p.days for n in p.slot_numbers if p.teacher_status(teacher_id, d, n) != "unavailable"]


def cur_cells(p: Problem, x) -> list[tuple[int, int]]:
    """Ячейки «день недели × пара», где занятие (строка плана или поток) в принципе можно поставить."""
    u = x if isinstance(x, Unit) else p.unit_of[x.id]
    gs = set(p.unit_slots(u))
    return [(d, n) for d, n in teacher_free_cells(p, u.teacher_id) if n in gs]


def week_cells(p: Problem, u: Unit, wk: date) -> list[tuple[date, int]]:
    """Конкретные слоты недели wk, доступные занятию: учебные дни, сроки, отгулы, доступность, смена."""
    off = p.days_off.get(u.teacher_id, set())
    gs = p.unit_slots(u)
    return [(d, n) for d in p.unit_dates(u, wk) if d not in off for n in gs
            if p.teacher_status(u.teacher_id, d.weekday(), n) != "unavailable"]


def _wk(wk: date) -> str:
    return f"{wk:%d.%m}–{wk + timedelta(days=6):%d.%m}"


def _worst(bad: list[tuple[date, str]], what: str) -> str:
    """Склеивает однотипные нарушения по неделям в одно сообщение."""
    wk, msg = bad[0]
    more = f" (и ещё {len(bad) - 1} нед.)" if len(bad) > 1 else ""
    return f"{what}: неделя {_wk(wk)} — {msg}{more}."


CARRY_NOTE = " Не поместившиеся пары перенесутся на следующие недели."


def _report(issues: list, bad: list, need: int, cap: int, what: str, kind: str):
    """Перегрузка отдельных недель — предупреждение (недобор переносится дальше),
    нехватка мест за весь период — ошибка."""
    if not bad:
        return
    if need > cap:
        issues.append(_issue("error", _worst(bad, what) + f" За весь период нужно {need} пар, "
                                                         f"а поместится не больше {cap}.", kind))
    else:
        issues.append(_issue("warning", _worst(bad, what) + CARRY_NOTE, kind))


def precheck(p: Problem) -> list[dict]:
    issues: list[dict] = []
    if not p.slots:
        return [_issue("error", "Не заданы пары (время начала и конца каждой пары).", "slots")]
    if not p.curriculum:
        return [_issue("error", "Учебный план пуст — нечего расставлять.", "curriculum")]
    if p.end_date < p.start_date:
        return [_issue("error", "Дата конца периода раньше даты начала.", "term")]
    if not p.weeks:
        return [_issue("error", "В учебном периоде нет ни одного учебного дня.", "term")]

    for g in p.groups.values():
        if not p.group_slots(g.id):
            issues.append(_issue("error", f"Для смены «{g.shift}» группы {g.name} не задано ни одной пары.", "shift"))

    # --- преподаватели не назначены ------------------------------------------
    unassigned: dict[int, list[str]] = defaultdict(list)
    for c in p.curriculum:
        if c.teacher_id == NO_TEACHER and p.expected_total(c.id):
            unassigned[c.group_id].append(p.subjects[c.subject_id].name)
    for gid, names in unassigned.items():
        shown = ", ".join(names[:6]) + (f" и ещё {len(names) - 6}" if len(names) > 6 else "")
        issues.append(_issue("error", f"Группа {p.groups[gid].name}: не назначен преподаватель — {shown}. "
                                      f"Назначьте в «Учебном плане» (можно сразу нескольким строкам).", "no_teacher"))

    # --- потоки: строки одного потока должны совпадать -----------------------
    bad_units = set()
    for u in p.units:
        if len(u.cur_ids) < 2:
            continue
        rows = [p.cur_by_id[cid] for cid in u.cur_ids]
        names = ", ".join(p.groups[c.group_id].name for c in rows)
        checks = [("subject_id", "дисциплина"), ("teacher_id", "преподаватель")]
        if any(c.weekly for c in rows):
            checks.append(("weekly", "нагрузка по неделям (КУГ)"))
        else:
            checks += [("per_week", "пар в неделю"), ("total", "пар всего"), ("start", "начало"), ("end", "окончание")]
        for attr, what in checks:
            vals = [getattr(c, attr) for c in rows]
            if any(v != vals[0] for v in vals):
                bad_units.add(u.id)
                issues.append(_issue("error", f"Поток «{u.stream}» ({names}): у групп разное поле «{what}» — "
                                              f"в потоке оно должно совпадать.", "stream"))
        if len(set(u.group_ids)) < len(u.group_ids):
            bad_units.add(u.id)
            issues.append(_issue("error", f"Поток «{u.stream}»: группа указана дважды.", "stream"))
        if not p.unit_slots(u):
            bad_units.add(u.id)
            issues.append(_issue("error", f"Поток «{u.stream}» ({names}): у групп нет общих пар по сменам.", "stream"))

    active = [u for u in p.units if u.teacher_id != NO_TEACHER and u.id not in bad_units and p.demand.get(u.id)]

    # --- по каждому занятию ---------------------------------------------------
    for u in active:
        label = p.unit_label(u)
        t = p.teachers[u.teacher_id]
        if u.subject_id not in t.subject_ids:
            issues.append(_issue("warning", f"{label}: преподаватель {t.name} не отмечен как ведущий эту дисциплину.",
                                 "teacher_subject"))
        if not p.suitable_rooms(u):
            need = p.subjects[u.subject_id].room_type
            issues.append(_issue("error", f"{label}: нет аудитории типа «{need}» вместимостью от {u.size} человек.", "rooms"))
        bad = []
        dem = p.demand[u.id]
        total_cap = 0
        for wk in p.weeks:
            if wk < min(dem):
                continue
            cells = week_cells(p, u, wk)
            days = len({d for d, _ in cells})
            cap = min(len(cells), days * t.max_per_day)
            total_cap += cap
            need = dem.get(wk, 0)
            if need > cap:
                bad.append((wk, f"нужно {need} пар, а преподаватель {t.name} в смену "
                                f"{'групп' if len(u.group_ids) > 1 else 'группы'} может провести только {cap}"))
        _report(issues, bad, sum(dem.values()), total_cap, label, "availability")

    # Нормы «пар в неделю» против доступности преподавателя (типовая полная неделя).
    short_teachers = {p.unit_by_id[uid].teacher_id for uid in p.shortfall}
    plan_t: dict[int, int] = defaultdict(int)
    for u in p.units:
        if u.teacher_id != NO_TEACHER and u.id not in bad_units and not p.cur_by_id[u.id].weekly:
            plan_t[u.teacher_id] += u.per_week
    for tid, load in plan_t.items():
        t = p.teachers[tid]
        free = len(teacher_free_cells(p, tid))
        level = "error" if tid in short_teachers else "warning"
        tail = "" if level == "error" else CARRY_NOTE.replace("следующие", "другие")
        if load > free:
            issues.append(_issue(level, f"У преподавателя {t.name} {load} пар в неделю при доступности {free} слотов."
                                 + tail, "teacher_load"))
        elif load > t.max_per_week:
            issues.append(_issue(level, f"У преподавателя {t.name} {load} пар в неделю при максимуме {t.max_per_week}."
                                 + tail, "teacher_load"))

    # Строки без КУГ, которые не помещаются в период целиком.
    for uid, left in p.shortfall.items():
        if uid in bad_units:
            continue
        u = p.unit_by_id[uid]
        c = p.cur_by_id[uid]
        placed = c.total - left
        span = ""
        if c.start or c.end:
            span = f" в сроки {c.start:%d.%m.%Y}" if c.start else " в сроки"
            span += f"–{c.end:%d.%m.%Y}" if c.end else ""
        issues.append(_issue(
            "error",
            f"{p.unit_label(u)}: за период{span} с учётом праздников, отгулов, доступности преподавателя "
            f"{p.teachers[u.teacher_id].name} и нагрузки групп помещается не более {placed} пар из {c.total} "
            f"(по {c.per_week} в неделю). Увеличьте пар в неделю, сроки или доступность.", "total"))

    # --- нагрузка по неделям: преподаватели, группы, аудитории --------------
    t_load: dict[tuple[int, date], int] = defaultdict(int)
    g_load: dict[tuple[int, date], int] = defaultdict(int)
    r_load: dict[tuple[str, date], int] = defaultdict(int)
    for u in active:
        for wk, n in p.demand[u.id].items():
            t_load[u.teacher_id, wk] += n
            for g in u.group_ids:
                g_load[g, wk] += n
            r_load[p.subjects[u.subject_id].room_type, wk] += n

    def study_days(wk: date) -> list[date]:
        return [wk + timedelta(days=i) for i in range(p.days_per_week) if p.is_study_day(wk + timedelta(days=i))]

    def teacher_cap(tid: int, wk: date) -> tuple[int, int]:
        t = p.teachers[tid]
        off = p.days_off.get(tid, set())
        days = [d for d in study_days(wk) if d not in off]
        free = sum(1 for d in days for n in p.slot_numbers if p.teacher_status(tid, d.weekday(), n) != "unavailable")
        return min(free, len(days) * t.max_per_day, t.max_per_week), free

    for tid in {tid for tid, _ in t_load}:
        t = p.teachers[tid]
        loads = {wk: n for (t2, wk), n in t_load.items() if t2 == tid}
        start = min(loads)
        bad, need, cap_total = [], sum(loads.values()), 0
        for wk in p.weeks:
            if wk < start:
                continue
            cap, free = teacher_cap(tid, wk)
            cap_total += cap
            if loads.get(wk, 0) > cap:
                bad.append((wk, f"{loads[wk]} пар при возможных {cap} (доступность {free} слотов, "
                                f"максимум {t.max_per_day} в день и {t.max_per_week} в неделю)"))
        _report(issues, bad, need, cap_total, f"У преподавателя {t.name} перегрузка", "teacher_load")

    for gid in {gid for gid, _ in g_load}:
        g = p.groups[gid]
        loads = {wk: n for (g2, wk), n in g_load.items() if g2 == gid}
        start = min(loads)
        bad, warn, cap_total = [], [], 0
        for wk in p.weeks:
            if wk < start:
                continue
            ndays = len(study_days(wk))
            cap = len(p.group_slots(gid)) * ndays
            cap_total += cap
            load = loads.get(wk, 0)
            if load > cap:
                bad.append((wk, f"{load} пар, а в смене «{g.shift}» на {ndays} учебных днях всего {cap} слотов"))
            elif load > p.group_day_limit * ndays:
                warn.append((wk, f"{load} пар — без превышения {p.group_day_limit} пар в день не обойтись"))
        _report(issues, bad, sum(loads.values()), cap_total, f"У группы {g.name} не хватает слотов", "group_load")
        if warn:
            issues.append(_issue("warning", _worst(warn, f"Группа {g.name}"), "group_load"))

    rooms_by_type: dict[str, int] = defaultdict(int)
    for r in p.rooms.values():
        if r.active:
            rooms_by_type[r.room_type] += 1
    for rtype in {rt for rt, _ in r_load}:
        loads = {wk: n for (rt, wk), n in r_load.items() if rt == rtype}
        bad, cap_total = [], 0
        for wk in p.weeks:
            if wk < min(loads):
                continue
            cap = rooms_by_type[rtype] * len(study_days(wk)) * len(p.slots)
            cap_total += cap
            if loads.get(wk, 0) > cap:
                bad.append((wk, f"нужно {loads[wk]} пар, а вместимость по слотам {cap}"))
        _report(issues, bad, sum(loads.values()), cap_total, f"Не хватает аудиторий типа «{rtype}»", "rooms")

    # Занятия, которые можно поставить только в один день недели, — хватит ли аудиторий в этот день.
    forced: dict[tuple[str, int], int] = defaultdict(int)
    for u in active:
        days = {d for d, _ in cur_cells(p, u)}
        if len(days) == 1:
            forced[(p.subjects[u.subject_id].room_type, next(iter(days)))] += p.max_week_demand(u)
    for (rtype, day), need in forced.items():
        cap = rooms_by_type[rtype] * len(p.slots)
        if need > cap:
            issues.append(_issue("error", f"Не хватает аудиторий типа «{rtype}» {WEEKDAYS_IN[day]}: "
                                          f"нужно {need} пар, доступно {cap}.", "rooms"))

    # Строки с нагрузкой вне этого периода — подсказка, а не ошибка.
    idle = [c for c in p.curriculum if c.teacher_id != NO_TEACHER and not p.expected_total(c.id)]
    if idle and len(idle) < len(p.curriculum):
        issues.append(_issue("warning", f"Строк плана без пар в этом периоде: {len(idle)} (по КУГ или срокам они "
                                        f"изучаются в другое время) — они не участвуют в расчёте.", "idle"))
    if not active and not any(i["level"] == "error" for i in issues):
        issues.append(_issue("error", "В этом периоде нет ни одной пары для расстановки.", "curriculum"))
    return issues
