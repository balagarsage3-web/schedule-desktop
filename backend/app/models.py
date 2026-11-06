from datetime import date, datetime, time

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Table, Time, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

LESSON_TYPES = ["лекция", "практика", "лаба"]
ROOM_TYPES = ["обычная", "компьютерный класс", "лаборатория"]
SHIFTS = ["утро", "день", "вечер"]
AVAIL_STATUSES = ["available", "unavailable", "preferred"]

DEFAULT_WEIGHTS = {
    "gaps": 20,              # без «окон» у группы
    "teacher_gaps": 5,       # без «окон» у преподавателя
    "group_day_limit": 10,   # не более N пар в день у группы
    "even_days": 5,          # равномерно по дням недели
    "same_slot": 5,          # дисциплина не в один и тот же слот каждый день
    "teacher_pref": 5,       # пожелания преподавателя
    "room_changes": 1,       # минимум смен аудитории
    "lecture_morning": 1,    # лекции в первой половине дня
    "stability": 3,          # пары стоят на тех же местах, что и на прошлой неделе
}

HOURS_PER_PAIR = 2  # в КУГ нагрузка в академических часах, пара = 2 часа

DEFAULT_SHIFT_SLOTS = {"утро": [1, 2, 3, 4], "день": [3, 4, 5, 6], "вечер": [5, 6, 7, 8]}

teacher_subjects = Table(
    "teacher_subjects",
    Base.metadata,
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), default="methodist")


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    course: Mapped[str] = mapped_column(String(128), default="")
    size: Mapped[int] = mapped_column(Integer, default=25)
    shift: Mapped[str] = mapped_column(String(16), default="утро")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("name", "lesson_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    lesson_type: Mapped[str] = mapped_column(String(16), default="практика")
    room_type: Mapped[str] = mapped_column(String(32), default="обычная")


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128), unique=True)
    max_per_day: Mapped[int] = mapped_column(Integer, default=4)
    max_per_week: Mapped[int] = mapped_column(Integer, default=18)
    subjects: Mapped[list[Subject]] = relationship(secondary=teacher_subjects, lazy="selectin")


class TeacherAvailability(Base):
    __tablename__ = "teacher_availability"
    __table_args__ = (UniqueConstraint("teacher_id", "weekday", "slot_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = понедельник
    slot_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="available")


class TeacherDayOff(Base):
    __tablename__ = "teacher_days_off"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(256), default="")


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    capacity: Mapped[int] = mapped_column(Integer, default=30)
    room_type: Mapped[str] = mapped_column(String(32), default="обычная")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Curriculum(Base):
    __tablename__ = "curriculum"
    __table_args__ = (UniqueConstraint("group_id", "subject_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    # Преподаватель может быть ещё не назначен (например, сразу после импорта КУГ).
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    total: Mapped[int] = mapped_column(Integer)
    per_week: Mapped[int] = mapped_column(Integer)
    # Метка потока: строки с одинаковой меткой — одна общая пара для нескольких групп.
    stream: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # Сроки изучения (для строк без КУГ): дисциплина идёт только в эти даты.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Нагрузка по КУГ: {"2024-09-02": 4, ...} — часы на неделю, ключ — понедельник недели.
    weekly: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    kug_ref: Mapped[str] = mapped_column(String(256), default="", server_default="")
    group: Mapped[Group] = relationship(lazy="joined")
    subject: Mapped[Subject] = relationship(lazy="joined")
    teacher: Mapped[Teacher | None] = relationship(lazy="joined")


class TimeSlot(Base):
    __tablename__ = "time_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    start: Mapped[time] = mapped_column(Time)
    end: Mapped[time] = mapped_column(Time)


class Term(Base):
    __tablename__ = "terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days_per_week: Mapped[int] = mapped_column(Integer, default=5)  # 5 = пн–пт, 6 = с субботой
    time_limit: Mapped[int] = mapped_column(Integer, default=60)
    group_day_limit: Mapped[int] = mapped_column(Integer, default=4)
    weights: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_WEIGHTS))
    shift_slots: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_SHIFT_SLOTS))


class NonWorkingDay(Base):
    __tablename__ = "non_working_days"
    __table_args__ = (UniqueConstraint("term_id", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(256), default="")


class ScheduleVersion(Base):
    __tablename__ = "schedule_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    score: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    public_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    term: Mapped[Term] = relationship(lazy="joined")


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("schedule_versions.id", ondelete="CASCADE"), index=True)
    curriculum_id: Mapped[int] = mapped_column(ForeignKey("curriculum.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, index=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("time_slots.id", ondelete="CASCADE"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
