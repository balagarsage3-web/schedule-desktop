"""Расстановка по неделям периода: решатель для каждой недели, аудитории, перенос недобора."""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .problem import NO_TEACHER, Problem, Unit, week_start


@dataclass
class PLesson:
    cur_id: int
    date: date
    slot_number: int
    room_id: int | None
    id: int | None = None
    pinned: bool = False


def unit_lessons(u: Unit, d: date, n: int, room: int | None) -> list[PLesson]:
    """Пара занятия: у потока — по записи на каждую группу, все в одной аудитории."""
    return [PLesson(cid, d, n, room) for cid in u.cur_ids]


def _home_rooms(p: Problem) -> dict[tuple[int, str], int]:
    """«Своя» аудитория группы для каждого типа — чтобы группа реже переходила между кабинетами."""
    home: dict[tuple[int, str], int] = {}
    by_type: dict[str, list] = defaultdict(list)
    for r in p.rooms.values():
        if r.active:
            by_type[r.room_type].append(r)
    for rtype, rooms in by_type.items():
        rooms.sort(key=lambda r: (r.capacity, r.number))
        for i, g in enumerate(sorted(p.groups.values(), key=lambda g: g.id)):
            fit = [r for r in rooms if r.capacity >= g.size]
            if fit:
                home[g.id, rtype] = fit[i % len(fit)].id
    return home


def assign_rooms(p: Problem, template: list[tuple[int, int, int]],
                 prefer: dict[tuple[int, int, int], int] | None = None) -> list[tuple[int, int, int, int | None]]:
    """Жадно назначает аудитории. Занятия обрабатываются от больших к меньшим, поэтому любая
    подходящая аудитория не мешает следующим. Порядок предпочтений: аудитория этой же пары
    на прошлой неделе, аудитория предыдущей пары группы в этот день, «своя» аудитория группы."""
    prefer = prefer or {}
    home = _home_rooms(p)
    by_cell: dict[tuple[int, int], list[int]] = defaultdict(list)
    for uid, d, n in template:
        by_cell[d, n].append(uid)
    last_room: dict[tuple[int, int], int] = {}
    out = []
    for d in range(7):
        for n in p.slot_numbers:
            uids = sorted(by_cell.get((d, n), []), key=lambda uid: -p.unit_by_id[uid].size)
            used: set[int] = set()
            for uid in uids:
                u = p.unit_by_id[uid]
                cand = [r for r in p.suitable_rooms(u) if r.id not in used]
                if not cand:
                    out.append((uid, d, n, None))
                    continue
                g0 = u.group_ids[0]
                wishes = [prefer.get((uid, d, n)), last_room.get((g0, d)),
                          home.get((g0, p.subjects[u.subject_id].room_type))]
                room = next((r for w in wishes if w for r in cand if r.id == w), cand[0])
                used.add(room.id)
                for g in u.group_ids:
                    last_room[g, d] = room.id
                out.append((uid, d, n, room.id))
    return out


class Occupancy:
    """Занятость групп, преподавателей и аудиторий по датам — для ручной правки.
    Пара потока (несколько записей на одно время) учитывается один раз."""

    def __init__(self, p: Problem, lessons: list[PLesson]):
        self.p = p
        self.placed: set[tuple[int, date, int]] = set()
        self.group = set()
        self.teacher = set()
        self.room = set()
        self.teacher_day = defaultdict(int)
        self.group_day = defaultdict(int)
        self.unit_week = defaultdict(int)
        for ls in lessons:
            self.add(ls)

    def add(self, ls: PLesson, sign: int = 1):
        u = self.p.unit_of[ls.cur_id]
        key = (u.id, ls.date, ls.slot_number)
        if sign > 0:
            if key in self.placed:
                return
            self.placed.add(key)
        else:
            if key not in self.placed:
                return
            self.placed.discard(key)
        op = set.add if sign > 0 else set.discard
        for g in u.group_ids:
            op(self.group, (g, ls.date, ls.slot_number))
            self.group_day[g, ls.date] += sign
        op(self.teacher, (u.teacher_id, ls.date, ls.slot_number))
        if ls.room_id:
            op(self.room, (ls.room_id, ls.date, ls.slot_number))
        self.teacher_day[u.teacher_id, ls.date] += sign
        self.unit_week[u.id, week_start(ls.date)] += sign

    def free_room(self, cur, d: date, n: int, prefer: int | None = None) -> int | None:
        cand = [r for r in self.p.suitable_rooms(cur) if (r.id, d, n) not in self.room]
        if not cand:
            return None
        return next((r.id for r in cand if r.id == prefer), cand[0].id)


@dataclass
class TermResult:
    lessons: list[PLesson] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    weeks: int = 0
    solved: int = 0            # сколько недель решалось заново (остальные — повтор предыдущих)
    optimal: int = 0
    stopped: bool = False
    objective: int = 0
    shortage_weeks: list[str] = field(default_factory=list)


def _week_key(p: Problem, wk: date, demand: dict[int, int]) -> tuple:
    """Недели с одинаковой нагрузкой, учебными днями и отгулами решаются один раз."""
    days = tuple(d.weekday() for d in p.week_dates(wk))
    offs = tuple(sorted((tid, d.weekday()) for tid, ds in p.days_off.items() for d in ds if week_start(d) == wk))
    windows = tuple(sorted((uid, tuple(d.weekday() for d in p.unit_dates(p.unit_by_id[uid], wk))) for uid in demand
                           if p.cur_by_id[uid].start or p.cur_by_id[uid].end))
    return tuple(sorted(demand.items())), days, offs, windows


def schedule_term(p: Problem, time_limit: float, on_progress=None,
                  stop_event: threading.Event | None = None) -> TermResult:
    """Расставляет все недели периода по очереди. Недопоставленные пары переходят на следующую неделю."""
    from .cpsat import solve_week

    import time

    res = TermResult()
    units = [u for u in p.units if u.teacher_id != NO_TEACHER]
    base = {wk: {u.id: p.demand[u.id][wk] for u in units if p.demand[u.id].get(wk)} for wk in p.weeks}
    first = next((i for i, wk in enumerate(p.weeks) if base[wk]), len(p.weeks))
    weeks = p.weeks[first:]  # все недели до конца периода: недобор может переехать и в «пустые»
    res.weeks = sum(1 for wk in weeks if base[wk])
    deadline = time.time() + float(time_limit)
    # Ключи недель без учёта переноса — по ним делится время: одинаковые недели решаются один раз.
    planned = [_week_key(p, wk, base[wk]) if base[wk] else None for wk in weeks]

    cache: dict[tuple, list] = {}
    carry: dict[int, int] = defaultdict(int)
    prev: set = set()
    prev_rooms: dict[tuple[int, int, int], int] = {}
    for i, wk in enumerate(weeks):
        demand = dict(base[wk])
        for uid, n in carry.items():
            if n:
                demand[uid] = demand.get(uid, 0) + n
        carry = defaultdict(int)
        if not demand:
            if on_progress:
                on_progress(i + 1, len(weeks))
            continue
        key = _week_key(p, wk, demand)
        if key in cache:
            template, shortages = cache[key]
        else:
            stopped = stop_event is not None and stop_event.is_set()
            # Общий лимит времени делится между оставшимися неделями; повторные недели берутся из кэша мгновенно.
            left_keys = {k for k in planned[i:] if k is not None and k not in cache} | {key}
            budget = max(1.5, (deadline - time.time()) / len(left_keys))
            r = solve_week(p, wk, demand, prev, time_limit=0.5 if stopped else budget,
                           stop_event=None if stopped else stop_event)
            if r.status == "stopped" and not r.template:  # остановили до первого решения — быстро добираем
                r = solve_week(p, wk, demand, prev, time_limit=1.0)
            res.stopped = res.stopped or (stop_event is not None and stop_event.is_set())
            template, shortages = r.template, (r.shortages if r.template else dict(demand))
            res.solved += 1
            res.optimal += r.status == "optimal"
            res.objective += r.objective or 0
            cache[key] = (template, shortages)
        for uid, n in shortages.items():
            carry[uid] += n
        if shortages:
            res.shortage_weeks.append(f"{wk:%d.%m}")
        rooms = assign_rooms(p, template, prev_rooms)
        for uid, d, n, room in rooms:
            res.lessons += unit_lessons(p.unit_by_id[uid], wk + timedelta(days=d), n, room)
        prev = set(template)
        prev_rooms = {(uid, d, n): room for uid, d, n, room in rooms if room}
        if on_progress:
            on_progress(i + 1, len(weeks))

    for uid, n in carry.items():
        if n:
            u = p.unit_by_id[uid]
            res.problems.append(f"{p.unit_label(u)}: не удалось поставить {n} пар — в их неделях не хватило "
                                f"свободных слотов (недобор переносился на следующие недели до конца периода).")
    res.lessons.sort(key=lambda ls: (ls.date, ls.slot_number))
    return res
