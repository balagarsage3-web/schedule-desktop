"""Импорт справочников и учебного плана из Excel/CSV по шаблону.

Файл проверяется целиком: если есть хоть одна ошибка, ничего не сохраняется,
а в ответе — номер строки и причина для каждой ошибки. Существующие записи
с тем же ключом (название, ФИО, номер) обновляются.
"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import current_user
from ..db import get_db

router = APIRouter(prefix="/api/import", dependencies=[Depends(current_user)])

WD = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
STATUS = {"доступен": "available", "недоступен": "unavailable", "желательно": "preferred"}

TEMPLATES = {
    "groups": {"title": "Группы", "columns": ["Название", "Курс/направление", "Численность", "Смена"],
               "example": [["ИС-21", "2 курс, Информационные системы", 25, "утро"]]},
    "subjects": {"title": "Дисциплины", "columns": ["Название", "Тип занятий", "Тип аудитории"],
                 "example": [["Информатика", "лекция", "обычная"], ["Информатика", "практика", "компьютерный класс"]]},
    "teachers": {"title": "Преподаватели", "columns": ["ФИО", "Дисциплины", "Макс. пар в день", "Макс. пар в неделю"],
                 "example": [["Иванов И.И.", "Информатика; Программирование", 4, 18]]},
    "rooms": {"title": "Аудитории", "columns": ["Номер", "Вместимость", "Тип", "Доступна"],
              "example": [["101", 30, "обычная", "да"], ["204", 25, "компьютерный класс", "да"]]},
    "curriculum": {"title": "Учебный план",
                   "columns": ["Группа", "Дисциплина", "Тип занятий", "Преподаватель", "Пар всего", "Пар в неделю",
                               "Поток (для общих пар)", "Начало (необязательно)", "Окончание (необязательно)"],
                   "example": [["ИС-21", "Информатика", "практика", "Иванов И.И.", 36, 2, "", "", ""],
                               ["ИС-21", "История", "лекция", "Петров П.П.", 18, 1, "История-2 курс", "", ""],
                               ["ИС-22", "История", "лекция", "Петров П.П.", 18, 1, "История-2 курс", "", ""],
                               ["ИС-21", "Химия", "практика", "", 16, 2, "", "01.09.2026", "25.10.2026"],
                               ["ИС-21", "Биология", "практика", "", 16, 2, "", "26.10.2026", "31.12.2026"]]},
    "availability": {"title": "Доступность", "columns": ["Преподаватель", "День", "Пары", "Статус"],
                     "example": [["Иванов И.И.", "вт", "1-6", "недоступен"], ["Иванов И.И.", "пн", "1-2", "желательно"]]},
}


@router.get("/template/{entity}")
def template(entity: str):
    t = TEMPLATES.get(entity)
    if t is None:
        raise HTTPException(404, "Нет такого шаблона")
    wb = Workbook()
    ws = wb.active
    ws.title = t["title"]
    ws.append(t["columns"])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDE7F5")
    for row in t["example"]:
        ws.append(row)
    for i, col in enumerate(t["columns"], start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(16, len(col) + 4)
    if entity == "availability":
        ws.append([])
        ws.append(["Подсказка: День — пн, вт, ср, чт, пт, сб; Пары — «1-4» или «1,3,5»; "
                   "Статус — доступен / недоступен / желательно."])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename=template_{entity}.xlsx"})


def read_rows(filename: str, content: bytes) -> list[tuple[int, list]]:
    """Строки файла без заголовка: (номер строки в файле, значения)."""
    name = (filename or "").lower()
    rows: list[list] = []
    if name.endswith(".csv") or name.endswith(".txt"):
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(422, "Не удалось прочитать кодировку CSV (ожидается UTF-8 или Windows-1251)")
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=";,\t")
        except csv.Error:
            class dialect(csv.excel):
                delimiter = ";"
        rows = [r for r in csv.reader(io.StringIO(text), dialect)]
    elif name.endswith(".xlsx") or name.endswith(".xlsm"):
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "Файл не похож на Excel (.xlsx)")
        rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
    else:
        raise HTTPException(422, "Поддерживаются файлы .xlsx и .csv")
    out = []
    for i, r in enumerate(rows[1:], start=2):
        vals = ["" if v is None else str(v).strip() for v in r]
        if any(vals):
            out.append((i, vals))
    return out


def _int(v: str, what: str, lo: int = 1, hi: int = 10000) -> int:
    try:
        n = int(float(v.replace(",", ".")))
    except ValueError:
        raise ValueError(f"{what}: «{v}» — не число")
    if not lo <= n <= hi:
        raise ValueError(f"{what}: значение {n} вне диапазона {lo}–{hi}")
    return n


def _date(v: str, what: str):
    """Дата из ячейки: 2026-09-01, 01.09.2026 или значение даты Excel; пусто — None."""
    v = (v or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{what}: «{v}» — не дата (ожидается ДД.ММ.ГГГГ)")


def _choice(v: str, options: list[str], what: str) -> str:
    v = v.strip().lower()
    if v not in options:
        raise ValueError(f"{what}: «{v}» — допустимо {', '.join(options)}")
    return v


def _slots(v: str) -> list[int]:
    out = []
    for part in v.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(_int(a, "Пары", 1, 12), _int(b, "Пары", 1, 12) + 1))
        else:
            out.append(_int(part, "Пары", 1, 12))
    if not out:
        raise ValueError("Пары: не указаны номера пар")
    return out


def _cell(vals: list, i: int) -> str:
    return vals[i] if i < len(vals) else ""


@router.post("/{entity}")
async def import_file(entity: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if entity not in TEMPLATES:
        raise HTTPException(404, "Нет такого типа импорта")
    rows = read_rows(file.filename, await file.read())
    if not rows:
        raise HTTPException(422, "В файле нет строк с данными (первая строка — заголовок)")
    errors: list[dict] = []
    actions = []
    seen: dict[str, int] = {}

    def dup(key: str, line: int) -> bool:
        if key in seen:
            errors.append({"row": line, "message": f"Повтор записи из строки {seen[key]}"})
            return True
        seen[key] = line
        return False

    subjects = db.query(m.Subject).all()
    for line, v in rows:
        try:
            if entity == "groups":
                name = _cell(v, 0)
                if not name:
                    raise ValueError("Не указано название группы")
                if dup(name.lower(), line):
                    continue
                actions.append(("groups", name, {"name": name, "course": _cell(v, 1),
                                                 "size": _int(_cell(v, 2), "Численность", 1, 1000),
                                                 "shift": _choice(_cell(v, 3) or "утро", m.SHIFTS, "Смена")}))
            elif entity == "subjects":
                name = _cell(v, 0)
                if not name:
                    raise ValueError("Не указано название дисциплины")
                lt = _choice(_cell(v, 1) or "практика", m.LESSON_TYPES, "Тип занятий")
                if dup(f"{name.lower()}|{lt}", line):
                    continue
                actions.append(("subjects", (name, lt), {"name": name, "lesson_type": lt,
                                                         "room_type": _choice(_cell(v, 2) or "обычная", m.ROOM_TYPES,
                                                                              "Тип аудитории")}))
            elif entity == "teachers":
                name = _cell(v, 0)
                if not name:
                    raise ValueError("Не указано ФИО")
                if dup(name.lower(), line):
                    continue
                subj_ids = []
                for sname in [x.strip() for x in _cell(v, 1).replace(",", ";").split(";") if x.strip()]:
                    found = [s for s in subjects if s.name.lower() == sname.lower()
                             or f"{s.name} ({s.lesson_type})".lower() == sname.lower()]
                    if not found:
                        raise ValueError(f"Дисциплина «{sname}» не найдена в справочнике — сначала импортируйте дисциплины")
                    subj_ids += [s.id for s in found]
                actions.append(("teachers", name, {"full_name": name, "subject_ids": subj_ids,
                                                   "max_per_day": _int(_cell(v, 2) or "4", "Макс. пар в день", 1, 12),
                                                   "max_per_week": _int(_cell(v, 3) or "18", "Макс. пар в неделю", 1, 60)}))
            elif entity == "rooms":
                num = _cell(v, 0)
                if not num:
                    raise ValueError("Не указан номер аудитории")
                if dup(num.lower(), line):
                    continue
                active = (_cell(v, 3) or "да").lower() not in ("нет", "0", "false", "no")
                actions.append(("rooms", num, {"number": num, "capacity": _int(_cell(v, 1), "Вместимость", 1, 2000),
                                               "room_type": _choice(_cell(v, 2) or "обычная", m.ROOM_TYPES, "Тип"),
                                               "active": active}))
            elif entity == "curriculum":
                gname, sname, lt, tname = _cell(v, 0), _cell(v, 1), _cell(v, 2), _cell(v, 3)
                g = db.query(m.Group).filter(m.Group.name == gname).first()
                if g is None:
                    raise ValueError(f"Группа «{gname}» не найдена")
                cand = [s for s in subjects if s.name.lower() == sname.lower()]
                if lt:
                    lt = _choice(lt, m.LESSON_TYPES, "Тип занятий")
                    cand = [s for s in cand if s.lesson_type == lt]
                if not cand:
                    raise ValueError(f"Дисциплина «{sname}» {f'({lt}) ' if lt else ''}не найдена")
                if len(cand) > 1:
                    raise ValueError(f"Дисциплина «{sname}» есть с разными типами занятий — укажите тип")
                t = None
                if tname:
                    t = db.query(m.Teacher).filter(m.Teacher.full_name == tname).first()
                    if t is None:
                        raise ValueError(f"Преподаватель «{tname}» не найден")
                total = _int(_cell(v, 4), "Пар всего", 1, 1000)
                per_week = _int(_cell(v, 5), "Пар в неделю", 1, 40)
                if per_week > total:
                    raise ValueError("Пар в неделю больше, чем всего")
                start, end = _date(_cell(v, 7), "Начало"), _date(_cell(v, 8), "Окончание")
                if start and end and end < start:
                    raise ValueError("Окончание раньше начала")
                if dup(f"{g.id}|{cand[0].id}", line):
                    continue
                actions.append(("curriculum", (g.id, cand[0].id), {"group_id": g.id, "subject_id": cand[0].id,
                                                                   "teacher_id": t.id if t else None, "total": total,
                                                                   "per_week": per_week,
                                                                   "stream": _cell(v, 6)[:64],
                                                                   "start_date": start, "end_date": end}))
            elif entity == "availability":
                tname = _cell(v, 0)
                t = db.query(m.Teacher).filter(m.Teacher.full_name == tname).first()
                if t is None:
                    raise ValueError(f"Преподаватель «{tname}» не найден")
                day = _cell(v, 1).lower()[:2]
                if day not in WD:
                    raise ValueError(f"День: «{_cell(v, 1)}» — укажите пн, вт, ср, чт, пт или сб")
                st = STATUS.get(_cell(v, 3).lower())
                if st is None:
                    raise ValueError("Статус: доступен / недоступен / желательно")
                for n in _slots(_cell(v, 2)):
                    actions.append(("availability", (t.id, WD[day], n), {"status": st}))
        except ValueError as e:
            errors.append({"row": line, "message": str(e)})

    if errors:
        return {"ok": False, "created": 0, "updated": 0, "errors": errors}

    created = updated = 0
    for kind, key, data in actions:
        if kind == "groups":
            obj = db.query(m.Group).filter(m.Group.name == key).first()
        elif kind == "subjects":
            obj = db.query(m.Subject).filter_by(name=key[0], lesson_type=key[1]).first()
        elif kind == "teachers":
            obj = db.query(m.Teacher).filter(m.Teacher.full_name == key).first()
            ids = data.pop("subject_ids")
            data["subjects"] = db.query(m.Subject).filter(m.Subject.id.in_(ids)).all() if ids else \
                (obj.subjects if obj else [])
        elif kind == "rooms":
            obj = db.query(m.Room).filter(m.Room.number == key).first()
        elif kind == "curriculum":
            obj = db.query(m.Curriculum).filter_by(group_id=key[0], subject_id=key[1]).first()
        else:
            obj = db.query(m.TeacherAvailability).filter_by(teacher_id=key[0], weekday=key[1], slot_number=key[2]).first()
            data = {"teacher_id": key[0], "weekday": key[1], "slot_number": key[2], **data}
        model = {"groups": m.Group, "subjects": m.Subject, "teachers": m.Teacher, "rooms": m.Room,
                 "curriculum": m.Curriculum, "availability": m.TeacherAvailability}[kind]
        if obj is None:
            db.add(model(**data))
            created += 1
        else:
            for k, val in data.items():
                setattr(obj, k, val)
            updated += 1
        db.flush()
    db.commit()
    return {"ok": True, "created": created, "updated": updated, "errors": []}
