"""Расстановка одной учебной недели на Google OR-Tools CP-SAT.

Переменная x[u, d, n] = 1, если занятие u стоит в день недели d на паре n. Занятие — это
строка учебного плана или поток (общая пара нескольких групп): у потока одна переменная
на слот, она занимает сразу все его группы, одного преподавателя и одну аудиторию.

Нагрузка недели берётся из КУГ (или из «пар в неделю»), поэтому недели решаются по очереди.
Чтобы расписание не «прыгало», решение прошлой недели служит подсказкой, а каждая пара,
оставшаяся на прежнем месте, уменьшает штраф (правило «стабильность»).

Аудитории в модель входят агрегированно — через условие Холла для каждого типа
аудиторий и порога вместимости. Для «вложенных» множеств подходящих аудиторий
это условие точное, поэтому конкретные аудитории потом всегда расставляются без конфликтов.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ortools.sat.python import cp_model

from .precheck import week_cells
from .problem import Problem

SHORTAGE_PENALTY = 1000  # за каждую пару, которую не удалось поставить на этой неделе


@dataclass
class SolveResult:
    status: str                                    # optimal | feasible | stopped | timeout
    template: list[tuple[int, int, int]] = field(default_factory=list)   # (unit_id, weekday, slot_number)
    shortages: dict[int, int] = field(default_factory=dict)              # unit_id -> недопоставлено пар
    objective: int | None = None
    wall_time: float = 0.0


class _Progress(cp_model.CpSolverSolutionCallback):
    def __init__(self, on_solution):
        super().__init__()
        self.on_solution = on_solution
        self.count = 0

    def on_solution_callback(self):
        self.count += 1
        if self.on_solution:
            self.on_solution(self.count, int(self.objective_value), self.wall_time)


def _gap_penalties(m: cp_model.CpModel, occ: list, name: str) -> list:
    """Булевы «окна» в дне: пара i пустая, а до и после неё есть занятия.
    occ — занятость по порядку пар (None — слот заведомо пуст)."""
    k = len(occ)
    lits = [o if o is not None else m.new_constant(0) for o in occ]
    pre = [m.new_bool_var(f"pre_{name}_{i}") for i in range(k)]
    suf = [m.new_bool_var(f"suf_{name}_{i}") for i in range(k)]
    m.add(pre[0] == 0)
    for i in range(1, k):
        m.add_max_equality(pre[i], [pre[i - 1], lits[i - 1]])
    m.add(suf[k - 1] == 0)
    for i in range(k - 2, -1, -1):
        m.add_max_equality(suf[i], [suf[i + 1], lits[i + 1]])
    gaps = []
    for i in range(1, k - 1):
        gap = m.new_bool_var(f"gap_{name}_{i}")
        m.add(gap >= pre[i] + suf[i] - lits[i] - 1)
        gaps.append(gap)
    return gaps


def _occupancy(m: cp_model.CpModel, cells: dict, key, slots: list[int], d: int, name: str) -> list:
    occ = []
    for n in slots:
        vs = cells.get((key, d, n), [])
        if not vs:
            occ.append(None)
            continue
        if len(vs) == 1:
            occ.append(vs[0])
            continue
        o = m.new_bool_var(f"o_{name}_{d}_{n}")
        m.add(o == sum(vs))
        occ.append(o)
    return occ


def build_model(p: Problem, wk: date, demand: dict[int, int], prev: set | None = None, strict: bool = False):
    """Модель недели wk. demand — сколько пар каждого занятия нужно в эту неделю.
    strict — все пары обязательны (решается быстрее); иначе недобор допускается со штрафом."""
    prev = prev or set()
    m = cp_model.CpModel()
    w = p.weights
    x: dict[tuple[int, int, int], cp_model.IntVar] = {}
    by_unit: dict[int, list] = defaultdict(list)
    by_group_cell: dict[tuple[int, int, int], list] = defaultdict(list)
    by_teacher_cell: dict[tuple[int, int, int], list] = defaultdict(list)
    terms = []  # слагаемые целевой функции
    shorts: dict[int, cp_model.IntVar] = {}
    study_wd = [d.weekday() for d in p.week_dates(wk)]

    units = [p.unit_by_id[uid] for uid, n in demand.items() if n > 0]
    for u in units:
        for d, n in week_cells(p, u, wk):
            wd = d.weekday()
            v = m.new_bool_var(f"x_{u.id}_{wd}_{n}")
            x[u.id, wd, n] = v
            by_unit[u.id].append((wd, n, v))
            for g in u.group_ids:
                by_group_cell[g, wd, n].append(v)
            by_teacher_cell[u.teacher_id, wd, n].append(v)

    # Нужное число пар в неделю; недобор допускается только с большим штрафом и переносится дальше.
    for u in units:
        need = demand[u.id]
        if strict:
            m.add(sum(v for _, _, v in by_unit[u.id]) == need)
            continue
        short = m.new_int_var(0, need, f"short_{u.id}")
        m.add(sum(v for _, _, v in by_unit[u.id]) + short == need)
        shorts[u.id] = short
        terms.append(SHORTAGE_PENALTY * short)

    # Жёсткие: группа и преподаватель не в двух местах сразу.
    for vs in by_group_cell.values():
        if len(vs) > 1:
            m.add_at_most_one(vs)
    for vs in by_teacher_cell.values():
        if len(vs) > 1:
            m.add_at_most_one(vs)

    # Жёсткие: лимиты преподавателя в день и неделю.
    for t in p.teachers.values():
        week = []
        for d in study_wd:
            day = [v for n in p.slot_numbers for v in by_teacher_cell.get((t.id, d, n), [])]
            if len(day) > t.max_per_day:
                m.add(sum(day) <= t.max_per_day)
            week += day
        if len(week) > t.max_per_week:
            m.add(sum(week) <= t.max_per_week)

    # Жёсткие: аудитории (условие Холла по типу и порогам вместимости).
    rooms_by_type: dict[str, list[int]] = defaultdict(list)
    for r in p.rooms.values():
        if r.active:
            rooms_by_type[r.room_type].append(r.capacity)
    units_by_type: dict[str, list] = defaultdict(list)
    for u in units:
        units_by_type[p.subjects[u.subject_id].room_type].append(u)
    for rtype, us in units_by_type.items():
        caps = rooms_by_type.get(rtype, [])
        thresholds = sorted({u.size for u in us})
        for d in study_wd:
            for n in p.slot_numbers:
                for q in thresholds:
                    vs = [x[u.id, d, n] for u in us if u.size >= q and (u.id, d, n) in x]
                    if not vs:
                        continue
                    limit = sum(1 for cap in caps if cap >= q)
                    if limit < len(vs):
                        m.add(sum(vs) <= limit)

    # --- мягкие ограничения -------------------------------------------------
    half = (len(p.slots) + 1) // 2
    ndays = max(1, len(study_wd))
    for u in units:
        need = demand[u.id]
        subj = p.subjects[u.subject_id]
        cells = by_unit[u.id]
        if need >= 2 and w.get("even_days"):
            per_day_ok = math.ceil(need / ndays)  # при большой нагрузке несколько пар в день неизбежны
            for d in study_wd:
                day = [v for dd, _, v in cells if dd == d]
                if len(day) > per_day_ok:
                    dup = m.new_int_var(0, len(day), f"dup_{u.id}_{d}")
                    m.add(dup >= sum(day) - per_day_ok)
                    terms.append(w["even_days"] * dup)
        if 2 <= need <= ndays and w.get("same_slot"):
            for n in p.slot_numbers:
                col = [v for _, nn, v in cells if nn == n]
                if len(col) > 1:
                    rep = m.new_int_var(0, len(col), f"rep_{u.id}_{n}")
                    m.add(rep >= sum(col) - 1)
                    terms.append(w["same_slot"] * rep)
        if w.get("lecture_morning") and subj.lesson_type == "лекция":
            for d, n, v in cells:
                if n > half:
                    terms.append(w["lecture_morning"] * v)

    # Стабильность: пара на том же месте, что и неделей раньше.
    if prev and w.get("stability"):
        for key, v in x.items():
            if key in prev:
                terms.append(w["stability"] * (1 - v))
    for key, v in x.items():
        m.add_hint(v, 1 if key in prev else 0)

    # Пожелания преподавателя: штраф за каждое желательное время, которое можно было занять, но не заняли.
    if w.get("teacher_pref"):
        for t in p.teachers.values():
            if not p.teacher_has_preferences(t.id):
                continue
            pref_cells = {(d, n) for (tid, d, n) in by_teacher_cell if tid == t.id
                          and p.teacher_status(t.id, d, n) == "preferred"}
            if not pref_cells:
                continue
            pref = [v for (tid, d, n), vs in by_teacher_cell.items() if tid == t.id and (d, n) in pref_cells for v in vs]
            load = sum(demand[u.id] for u in units if u.teacher_id == t.id)
            want = min(load, len(pref_cells))
            if want:
                miss = m.new_int_var(0, want, f"pref_{t.id}")
                m.add(miss >= want - sum(pref))
                terms.append(w["teacher_pref"] * miss)

    # Окна у преподавателей.
    if w.get("teacher_gaps"):
        for tid in {u.teacher_id for u in units}:
            for d in study_wd:
                occ = _occupancy(m, by_teacher_cell, tid, p.slot_numbers, d, f"t{tid}")
                if len(occ) > 2 and sum(o is not None for o in occ) >= 2:
                    terms += [w["teacher_gaps"] * g for g in _gap_penalties(m, occ, f"t{tid}_{d}")]

    # Группы: окна, лимит пар в день, равномерность.
    for gid in {g for u in units for g in u.group_ids}:
        gslots = p.group_slots(gid)
        loads = []
        for d in study_wd:
            occ = _occupancy(m, by_group_cell, gid, gslots, d, f"g{gid}")
            real = [o for o in occ if o is not None]
            load = m.new_int_var(0, len(gslots), f"load_{gid}_{d}")
            m.add(load == (sum(real) if real else 0))
            loads.append(load)
            if not real:
                continue
            if w.get("group_day_limit") and len(real) > p.group_day_limit:
                ex = m.new_int_var(0, len(real), f"ex_{gid}_{d}")
                m.add(ex >= load - p.group_day_limit)
                terms.append(w["group_day_limit"] * ex)
            if w.get("gaps") and len(real) >= 2 and len(occ) > 2:
                terms += [w["gaps"] * gap for gap in _gap_penalties(m, occ, f"g{gid}_{d}")]
        if w.get("even_days") and len(loads) > 1:
            mx = m.new_int_var(0, len(gslots), f"mx_{gid}")
            mn = m.new_int_var(0, len(gslots), f"mn_{gid}")
            m.add_max_equality(mx, loads)
            m.add_min_equality(mn, loads)
            spread = m.new_int_var(0, len(gslots), f"spread_{gid}")
            m.add(spread >= mx - mn - 1)  # разница в одну пару между днями неизбежна
            terms.append(w["even_days"] * spread)

    if terms:
        m.minimize(sum(terms))
    return m, x, shorts


def solve_week(p: Problem, wk: date, demand: dict[int, int], prev: set | None = None,
               time_limit: float = 10, on_solution=None, stop_event: threading.Event | None = None,
               workers: int = 8) -> SolveResult:
    """Сначала строгая постановка (все пары обязательны): так решение находится быстро.
    Если неделю так не уложить — мягкая, где недобор допускается и переносится дальше."""
    t0 = time.time()
    if all(len(week_cells(p, p.unit_by_id[uid], wk)) >= n for uid, n in demand.items()):
        r = _solve(p, wk, demand, prev, time_limit * 0.75, on_solution, stop_event, workers, strict=True)
        if r.template or r.status == "stopped":
            r.wall_time = time.time() - t0
            return r
    r = _solve(p, wk, demand, prev, max(0.5, time_limit - (time.time() - t0)), on_solution, stop_event, workers,
               strict=False)
    r.wall_time = time.time() - t0
    return r


def _solve(p: Problem, wk: date, demand: dict[int, int], prev: set | None, time_limit: float, on_solution,
           stop_event: threading.Event | None, workers: int, strict: bool) -> SolveResult:
    t0 = time.time()
    model, x, shorts = build_model(p, wk, demand, prev, strict=strict)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = 1

    watcher, done = None, threading.Event()
    if stop_event is not None:
        def watch():
            while not done.is_set():
                if stop_event.wait(0.2):
                    solver.stop_search()
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()

    status = solver.solve(model, _Progress(on_solution))
    done.set()

    res = SolveResult(status="infeasible" if status == cp_model.INFEASIBLE else "timeout", wall_time=time.time() - t0)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res.status = "optimal" if status == cp_model.OPTIMAL else "feasible"
        if stop_event is not None and stop_event.is_set():
            res.status = "stopped"
        res.objective = int(solver.objective_value)
        res.template = [key for key, v in x.items() if solver.value(v)]
        res.shortages = {uid: int(solver.value(s)) for uid, s in shorts.items() if solver.value(s)}
    elif stop_event is not None and stop_event.is_set():
        res.status = "stopped"
    return res
