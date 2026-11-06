from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import AVAIL_STATUSES, LESSON_TYPES, ROOM_TYPES, SHIFTS


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _choice(value: str, options: list[str], what: str) -> str:
    value = (value or "").strip().lower()
    if value not in options:
        raise ValueError(f"{what}: допустимо {', '.join(options)}")
    return value


class LoginIn(BaseModel):
    login: str
    password: str


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    course: str = ""
    size: int = Field(ge=1, le=1000)
    shift: str = "утро"

    @field_validator("shift")
    @classmethod
    def _shift(cls, v):
        return _choice(v, SHIFTS, "Смена")


class GroupOut(GroupIn, ORM):
    id: int


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    lesson_type: str = "практика"
    room_type: str = "обычная"

    @field_validator("lesson_type")
    @classmethod
    def _lt(cls, v):
        return _choice(v, LESSON_TYPES, "Тип занятий")

    @field_validator("room_type")
    @classmethod
    def _rt(cls, v):
        return _choice(v, ROOM_TYPES, "Тип аудитории")


class SubjectOut(SubjectIn, ORM):
    id: int


class TeacherIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=128)
    max_per_day: int = Field(4, ge=1, le=12)
    max_per_week: int = Field(18, ge=1, le=60)
    subject_ids: list[int] = []


class TeacherOut(ORM):
    id: int
    full_name: str
    max_per_day: int
    max_per_week: int
    subject_ids: list[int] = []


class RoomIn(BaseModel):
    number: str = Field(min_length=1, max_length=32)
    capacity: int = Field(ge=1, le=2000)
    room_type: str = "обычная"
    active: bool = True

    @field_validator("room_type")
    @classmethod
    def _rt(cls, v):
        return _choice(v, ROOM_TYPES, "Тип аудитории")


class RoomOut(RoomIn, ORM):
    id: int


class CurriculumIn(BaseModel):
    group_id: int
    subject_id: int
    teacher_id: int | None = None
    total: int = Field(ge=0, le=1000)
    per_week: int = Field(ge=0, le=40)
    stream: str = Field("", max_length=64)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("stream")
    @classmethod
    def _stream(cls, v):
        return (v or "").strip()

    @field_validator("teacher_id", mode="before")
    @classmethod
    def _teacher(cls, v):
        return None if v in ("", 0, "0") else v

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _dates(cls, v):
        return None if v == "" else v


class CurriculumOut(CurriculumIn, ORM):
    id: int
    group_name: str = ""
    subject_name: str = ""
    lesson_type: str = ""
    teacher_name: str = ""
    has_kug: bool = False
    kug_ref: str = ""
    kug_hours: int = 0


class AssignTeacherIn(BaseModel):
    ids: list[int]
    teacher_id: int | None = None


class WeeklyIn(BaseModel):
    weekly: dict[str, float]


class TimeSlotIn(BaseModel):
    number: int = Field(ge=1, le=12)
    start: time
    end: time


class TimeSlotOut(TimeSlotIn, ORM):
    id: int


class TermIn(BaseModel):
    name: str = Field(min_length=1)
    start_date: date
    end_date: date
    days_per_week: int = Field(5, ge=1, le=7)
    time_limit: int = Field(60, ge=5, le=1800)
    group_day_limit: int = Field(4, ge=1, le=12)
    weights: dict[str, int] = {}
    shift_slots: dict[str, list[int]] = {}


class TermOut(TermIn, ORM):
    id: int


class NonWorkingIn(BaseModel):
    date: date
    reason: str = ""


class NonWorkingOut(NonWorkingIn, ORM):
    id: int
    term_id: int


class DayOffIn(BaseModel):
    date: date
    reason: str = ""


class DayOffOut(DayOffIn, ORM):
    id: int
    teacher_id: int


class AvailabilityCell(BaseModel):
    weekday: int = Field(ge=0, le=6)
    slot_number: int
    status: str

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v not in AVAIL_STATUSES:
            raise ValueError("Статус: available / unavailable / preferred")
        return v


class GenerateIn(BaseModel):
    term_id: int
    time_limit: int | None = Field(None, ge=5, le=1800)


class MoveIn(BaseModel):
    date: date
    slot_number: int
    room_id: int | None = None
    series: bool = False   # перенести эту пару и все такие же в последующие недели
    force: bool = False    # сохранить, даже если есть конфликты
    dry_run: bool = False
