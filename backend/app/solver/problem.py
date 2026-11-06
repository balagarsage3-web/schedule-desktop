"""Входные данные генерации в виде, не зависящем от базы данных.

Решатель, проверка данных и валидатор работают только с этими структурами,
поэтому их можно тестировать без БД.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_IN = ["в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"]


@dataclass
class SlotInfo:
    id: int
    number: int
    start: time
    end: time


@dataclass
class GroupInfo:
    id: int
    name: str
    size: int
    shift: str


@dataclass
class SubjectInfo:
    id: int
    name: str
    lesson_type: str
    room_type: str


@dataclass
class TeacherInfo:
    id: int
    name: str
    max_per_day: int
    max_per_week: int
    subject_ids: set[int] = field(default_factory=set)


@dataclass
class RoomInfo:
    id: int
    number: str
    capacity: int
    room_type: str
    active: bool = True


@dataclass
class CurItem:
    id: int
    group_id: int
    subject_id: int
    teacher_id: int             # 0 — преподаватель не назначен
    total: int
    per_week: int
    stream: str = ""
    start: date | None = None   # сроки изучения (для строк без КУГ)
    end: date | None = None
    weekly: dict[date, float] | None = None  # часы по неделям из КУГ (ключ — понедельник)


@dataclass
class Unit:
    """Одно расставляемое занятие: строка плана или поток из нескольких строк (общая пара)."""
    id: int                     # id первой строки плана
    cur_ids: list[int]
    group_ids: list[int]
    teacher_id: int
    subject_id: int
    total: int
    per_week: int
    size: int                   # суммарная численность групп
    stream: str = ""


NO_TEACHER = 0


def weekly_pairs(weekly: dict) -> dict[date, int]:
    """Часы КУГ по неделям -> пары по неделям (пара = 2 часа).
    Нечётные часы накапливаются: 3 + 3 часа дают 1 и 2 пары, итог за период не теряется."""
    from ..models import HOURS_PER_PAIR

    out: dict[date, int] = {}
    cum, done = 0.0, 0
    for k in sorted(weekly, key=lambda x: x if isinstance(x, date) else date.fromisoformat(x)):
        d = k if isinstance(k, date) else date.fromisoformat(k)
        cum += float(weekly[k] or 0)
        pairs = int(cum / HOURS_PER_PAIR + 1e-9) - done
        if pairs > 0:
            out[d] = pairs
            done += pairs
    return out


@dataclass
class Problem:
    term_name: str
    start_date: date
    end_date: date
    days_per_week: int
    slots: list[SlotInfo]
    groups: dict[int, GroupInfo]
    subjects: dict[int, SubjectInfo]
    teachers: dict[int, TeacherInfo]
    rooms: dict[int, RoomInfo]
    curriculum: list[CurItem]
    availability: dict[int, dict[tuple[int, int], str]] = field(default_factory=dict)
    days_off: dict[int, set[date]] = field(default_factory=dict)
    non_working: set[date] = field(default_factory=set)
    weights: dict[str, int] = field(default_factory=dict)
    shift_slots: dict[str, list[int]] = field(default_factory=dict)
    group_day_limit: int = 4
    time_limit: int = 60

    def __post_init__(self):
        self.slots = sorted(self.slots, key=lambda s: s.number)
        self.slot_by_number = {s.number: s for s in self.slots}
        self.slot_by_id = {s.id: s for s in self.slots}
        self.cur_by_id = {c.id: c for c in self.curriculum}
        self.teachers.setdefault(NO_TEACHER, TeacherInfo(NO_TEACHER, "(не назначен)", 99, 999))
        self._build_units()
        self._build_demand()

    def _build_units(self):
        by_stream: dict[str, list[CurItem]] = {}
        singles: list[list[CurItem]] = []
        for c in sorted(self.curriculum, key=lambda c: c.id):
            if c.stream:
                by_stream.setdefault(c.stream, []).append(c)
            else:
                singles.append([c])
        self.units: list[Unit] = []
        self.unit_of: dict[int, Unit] = {}
        for members in singles + list(by_stream.values()):
            first = members[0]
            u = Unit(id=first.id, cur_ids=[c.id for c in members], group_ids=[c.group_id for c in members],
                     teacher_id=first.teacher_id, subject_id=first.subject_id, total=first.total,
                     per_week=first.per_week, size=sum(self.groups[c.group_id].size for c in members),
                     stream=first.stream)
            self.units.append(u)
            for c in members:
                self.unit_of[c.id] = u
        self.unit_by_id = {u.id: u for u in self.units}

    def _build_demand(self):
        """Сколько пар каждого занятия нужно поставить в каждую неделю периода.

        Строки КУГ берут нагрузку из графика как есть. Строки без КУГ («пар в неделю» и «всего»)
        раскладываются по неделям с учётом реальной ёмкости: неполные недели, праздники, отгулы,
        доступность и лимиты преподавателя, слоты группы. Если неделя меньше нормы, пары
        догоняются в следующих неделях; что не поместилось за период — в shortfall."""
        self.weeks: list[date] = sorted({week_start(d) for d in self.term_dates() if self.is_study_day(d)})
        first = week_start(self.start_date)
        self.demand: dict[int, dict[date, int]] = {}
        self.shortfall: dict[int, int] = {}
        flexible = []
        for u in self.units:
            c = self.cur_by_id[u.id]
            if c.weekly:
                self.demand[u.id] = {wk: n for wk, n in weekly_pairs(c.weekly).items() if first <= wk <= self.end_date}
            else:
                self.demand[u.id] = {}
                if u.teacher_id != NO_TEACHER:
                    flexible.append(u)
        if not flexible:
            return
        # Занятое строками КУГ — их нагрузка фиксирована.
        t_used: dict[tuple[int, date], int] = {}
        g_used: dict[tuple[int, date], int] = {}
        for u in self.units:
            for wk, n in self.demand[u.id].items():
                t_used[u.teacher_id, wk] = t_used.get((u.teacher_id, wk), 0) + n
                for g in u.group_ids:
                    g_used[g, wk] = g_used.get((g, wk), 0) + n
        left = {u.id: self.cur_by_id[u.id].total for u in flexible}
        for i, wk in enumerate(self.weeks):
            dates = self.week_dates(wk)
            # Самые «срочные» (больше всего пар на оставшиеся недели) — первыми.
            def urgency(u):
                rest = sum(1 for w in self.weeks[i:] if self.unit_dates(u, w))
                return -left[u.id] / max(1, rest)
            for u in sorted(flexible, key=urgency):
                c = self.cur_by_id[u.id]
                if left[u.id] <= 0 or not self.unit_dates(u, wk):
                    continue
                elapsed = sum(1 for w in self.weeks[:i + 1] if self.unit_dates(u, w))
                behind = min(c.total, c.per_week * elapsed) - (c.total - left[u.id])
                t = self.teachers[u.teacher_id]
                t_cap = self._teacher_week_cap(u.teacher_id, wk, dates) - t_used.get((u.teacher_id, wk), 0)
                g_cap = min(len(self.group_slots(g)) * len(dates) - g_used.get((g, wk), 0) for g in u.group_ids)
                n = min(left[u.id], max(c.per_week, behind), self._unit_week_cap(u, wk), t_cap, g_cap,
                        2 * c.per_week)  # догоняем не быстрее удвоенной нормы
                if n <= 0:
                    continue
                self.demand[u.id][wk] = n
                left[u.id] -= n
                t_used[t.id, wk] = t_used.get((t.id, wk), 0) + n
                for g in u.group_ids:
                    g_used[g, wk] = g_used.get((g, wk), 0) + n
        self.shortfall = {uid: n for uid, n in left.items() if n > 0}

    def _unit_week_cap(self, u: Unit, wk: date) -> int:
        off = self.days_off.get(u.teacher_id, set())
        slots = self.unit_slots(u)
        t = self.teachers[u.teacher_id]
        total = 0
        for d in self.unit_dates(u, wk):
            if d in off:
                continue
            free = sum(1 for n in slots if self.teacher_status(u.teacher_id, d.weekday(), n) != "unavailable")
            total += min(free, t.max_per_day)
        return total

    def _teacher_week_cap(self, tid: int, wk: date, dates: list[date]) -> int:
        t = self.teachers[tid]
        off = self.days_off.get(tid, set())
        total = 0
        for d in dates:
            if d in off:
                continue
            free = sum(1 for n in self.slot_numbers if self.teacher_status(tid, d.weekday(), n) != "unavailable")
            total += min(free, t.max_per_day)
        return min(total, t.max_per_week)

    def week_dates(self, wk: date) -> list[date]:
        """Учебные дни недели, начинающейся с понедельника wk."""
        return [wk + timedelta(days=i) for i in range(self.days_per_week) if self.is_study_day(wk + timedelta(days=i))]

    def unit_dates(self, u: Unit, wk: date) -> list[date]:
        """Учебные дни недели wk, когда занятие может идти (с учётом сроков дисциплины)."""
        c = self.cur_by_id[u.id]
        out = []
        for i in range(self.days_per_week):
            d = wk + timedelta(days=i)
            if not self.is_study_day(d):
                continue
            if not c.weekly and (c.start and d < c.start or c.end and d > c.end):
                continue
            out.append(d)
        return out

    def expected_total(self, cur_id: int) -> int:
        """Сколько пар строки плана должно быть в этом периоде: по КУГ — сумма недель периода,
        иначе — «пар всего»."""
        c = self.cur_by_id[cur_id]
        if c.weekly is None:
            return c.total
        u = self.unit_of.get(cur_id)
        return sum(self.demand.get(u.id, {}).values()) if u else 0

    def max_week_demand(self, u: Unit) -> int:
        return max(self.demand.get(u.id, {}).values(), default=0)

    # --- справочные функции -------------------------------------------------
    @property
    def days(self) -> list[int]:
        return list(range(self.days_per_week))

    @property
    def slot_numbers(self) -> list[int]:
        return [s.number for s in self.slots]

    def group_slots(self, group_id: int) -> list[int]:
        """Номера пар, разрешённые смене группы."""
        allowed = self.shift_slots.get(self.groups[group_id].shift)
        nums = self.slot_numbers
        if not allowed:
            return nums
        return [n for n in nums if n in set(allowed)]

    def teacher_status(self, teacher_id: int, weekday: int, slot_number: int) -> str:
        return self.availability.get(teacher_id, {}).get((weekday, slot_number), "available")

    def teacher_has_preferences(self, teacher_id: int) -> bool:
        return any(v == "preferred" for v in self.availability.get(teacher_id, {}).values())

    def unit_slots(self, u: Unit) -> list[int]:
        """Пары, подходящие сменам всех групп потока."""
        common = set(self.slot_numbers)
        for g in u.group_ids:
            common &= set(self.group_slots(g))
        return [n for n in self.slot_numbers if n in common]

    def suitable_rooms(self, cur: "CurItem | Unit") -> list[RoomInfo]:
        u = cur if isinstance(cur, Unit) else self.unit_of[cur.id]
        need = self.subjects[u.subject_id].room_type
        rooms = [r for r in self.rooms.values() if r.active and r.room_type == need and r.capacity >= u.size]
        return sorted(rooms, key=lambda r: (r.capacity, r.number))

    def unit_label(self, u: Unit) -> str:
        s = self.subjects[u.subject_id]
        names = ", ".join(self.groups[g].name for g in u.group_ids)
        if len(u.group_ids) > 1:
            return f"«{s.name}» ({s.lesson_type}) у потока {names}"
        return f"«{s.name}» ({s.lesson_type}) у группы {names}"

    def is_study_day(self, d: date) -> bool:
        return (self.start_date <= d <= self.end_date and d.weekday() < self.days_per_week
                and d not in self.non_working)

    def term_dates(self) -> list[date]:
        out, d = [], self.start_date
        while d <= self.end_date:
            out.append(d)
            d += timedelta(days=1)
        return out

    def cur_label(self, c: CurItem) -> str:
        return self.unit_label(self.unit_of[c.id])


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def load_problem(db, term_id: int) -> Problem:
    from .. import models as m

    term = db.get(m.Term, term_id)
    if term is None:
        raise ValueError("Учебный период не найден")
    slots = [SlotInfo(s.id, s.number, s.start, s.end) for s in db.query(m.TimeSlot).all()]
    groups = {g.id: GroupInfo(g.id, g.name, g.size, g.shift) for g in db.query(m.Group).all()}
    subjects = {s.id: SubjectInfo(s.id, s.name, s.lesson_type, s.room_type) for s in db.query(m.Subject).all()}
    teachers = {
        t.id: TeacherInfo(t.id, t.full_name, t.max_per_day, t.max_per_week, {s.id for s in t.subjects})
        for t in db.query(m.Teacher).all()
    }
    rooms = {r.id: RoomInfo(r.id, r.number, r.capacity, r.room_type, r.active) for r in db.query(m.Room).all()}
    curriculum = [
        CurItem(c.id, c.group_id, c.subject_id, c.teacher_id or NO_TEACHER, c.total, c.per_week,
                (c.stream or "").strip(), c.start_date, c.end_date,
                {date.fromisoformat(k): v for k, v in c.weekly.items()} if c.weekly else None)
        for c in db.query(m.Curriculum).all()
    ]
    availability: dict[int, dict[tuple[int, int], str]] = {}
    for a in db.query(m.TeacherAvailability).all():
        availability.setdefault(a.teacher_id, {})[(a.weekday, a.slot_number)] = a.status
    days_off: dict[int, set[date]] = {}
    for d in db.query(m.TeacherDayOff).all():
        days_off.setdefault(d.teacher_id, set()).add(d.date)
    non_working = {n.date for n in db.query(m.NonWorkingDay).filter_by(term_id=term_id).all()}
    weights = dict(m.DEFAULT_WEIGHTS)
    weights.update(term.weights or {})
    return Problem(
        term_name=term.name,
        start_date=term.start_date,
        end_date=term.end_date,
        days_per_week=term.days_per_week,
        slots=slots,
        groups=groups,
        subjects=subjects,
        teachers=teachers,
        rooms=rooms,
        curriculum=curriculum,
        availability=availability,
        days_off=days_off,
        non_working=non_working,
        weights=weights,
        shift_slots=term.shift_slots or dict(m.DEFAULT_SHIFT_SLOTS),
        group_day_limit=term.group_day_limit,
        time_limit=term.time_limit,
    )
