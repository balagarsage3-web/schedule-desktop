"""Разбор календарного учебного графика (КУГ) из Excel.

Ожидаемая структура листа (лист на курс, как в шаблонах колледжа):
  * в заголовке — «… 2024-2025 учебный год»;
  * строка-шапка с ячейками «Индекс», «Компоненты программы», «Виды учебной нагрузки»;
  * строка «Номера календарных недель», под ней — номера недель ISO (36…52, 1…27);
  * колонки «Всего семестр (час.)» отделяют первое полугодие от второго;
  * строки дисциплин: индекс, название, вид нагрузки («аудит. нагр.» / «сам.раб») и часы по неделям;
    «К» в клетке — каникулы; строка «сам.раб» может идти без индекса и названия (объединённые ячейки);
  * строки практик (УП, ПП) и экзаменов (ЭМ/ЭК, ГИА) — без вида нагрузки.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta

from openpyxl import load_workbook

KIND_LABELS = {
    "class": "аудиторная нагрузка",
    "self": "самостоятельная работа",
    "up": "учебная практика",
    "pp": "производственная практика",
    "exam": "экзамен / аттестация",
}


class KugError(ValueError):
    pass


def _s(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _num(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ".").strip())
        except ValueError:
            return None
    return None


def _kind(code: str, kind: str) -> str | None:
    k = kind.lower()
    if k.startswith("аудит"):
        return "class"
    if k.startswith("сам"):
        return "self"
    c = code.upper().replace(" ", "")
    if c.startswith("УП"):
        return "up"
    if c.startswith("ПП"):
        return "pp"
    if "ЭМ" in c or "ЭК" in c or c.startswith("ГИА"):
        return "exam"
    return None


def parse_sheet(ws, index: int) -> dict:
    cells = {(c.row, c.column): c.value for row in ws.iter_rows(max_row=min(ws.max_row, 400)) for c in row
             if c.value not in (None, "")}

    def find(pred):
        return sorted(k for k, v in cells.items() if isinstance(v, str) and pred(_s(v).lower()))

    # Учебный год.
    year = None
    for (r, c), v in sorted(cells.items()):
        if r > 6 or not isinstance(v, str):
            continue
        mt = re.search(r"(20\d\d)\s*[-–]\s*(20\d\d)", v)
        if mt:
            year = int(mt.group(1))
            break
    if year is None:
        raise KugError(f"Лист «{ws.title.strip()}»: не найден учебный год вида «2024-2025» в заголовке")

    # Колонки шапки.
    head = find(lambda s: s == "индекс")
    if not head:
        raise KugError(f"Лист «{ws.title.strip()}»: не найдена шапка с ячейкой «Индекс»")
    head_row, code_col = head[0]
    name_col = next((c for (r, c) in find(lambda s: s.startswith("компоненты")) if r == head_row), code_col + 1)
    kind_col = next((c for (r, c) in find(lambda s: s.startswith("виды")) if r == head_row), name_col + 1)
    sem_cols = sorted(c for (r, c) in find(lambda s: s.startswith("всего семестр")) if r == head_row)

    # Номера календарных недель.
    label = find(lambda s: "номера календарных недель" in s)
    if not label:
        raise KugError(f"Лист «{ws.title.strip()}»: не найдена строка «Номера календарных недель»")
    week_row = label[0][0] + 1
    cols = []
    for (r, c), v in sorted(cells.items()):
        n = _num(v)
        if r == week_row and c > kind_col and n is not None and 1 <= n <= 53 and n == int(n):
            cols.append((c, int(n)))
    if len(cols) < 10:
        raise KugError(f"Лист «{ws.title.strip()}»: в строке номеров недель найдено только {len(cols)} недель")

    # Даты недель. Номера календарных недель в шаблонах часто скопированы с прошлого года и сдвинуты,
    # поэтому опорой служит число месяца первой недели (строка под шапкой), дальше недели идут подряд.
    day_row = head_row + 1
    first_day = _num(cells.get((day_row, cols[0][0])))
    if first_day and 1 <= first_day <= 31:
        d = int(first_day)
        first = date(year, 9, d) if d <= 20 else date(year, 8, d)
        base = first - timedelta(days=first.weekday())
    else:
        iso = cols[0][1]
        base = date.fromisocalendar(year if iso >= 30 else year + 1, iso, 1)
    weeks = []
    for i, (c, iso_week) in enumerate(cols):
        monday = base + timedelta(weeks=i)
        sem = 1 if not sem_cols or c < sem_cols[0] else 2
        weeks.append({"col": c, "iso_week": iso_week, "monday": monday, "sem": sem})
    # Сверка: число месяца в строке начала недели должно попадать в эту неделю.
    mismatches = 0
    for w in weeks:
        dd = _num(cells.get((day_row, w["col"])))
        if dd and int(dd) not in {(w["monday"] + timedelta(days=k)).day for k in range(7)}:
            mismatches += 1
    if mismatches > len(weeks) // 4:
        raise KugError(f"Лист «{ws.title.strip()}»: даты недель в шапке не идут подряд — проверьте строку чисел месяца")
    week_cols = {w["col"]: w["monday"] for w in weeks}

    # Строки дисциплин.
    rows, vacation = [], set()
    start = max(week_row + 1, head_row + 1)
    last_code = last_name = ""
    for r in range(start, ws.max_row + 1):
        code, name, kind = _s(cells.get((r, code_col))), _s(cells.get((r, name_col))), _s(cells.get((r, kind_col)))
        if name.lower().startswith("всего часов"):
            for c, monday in week_cols.items():
                if _s(cells.get((r, c))).upper() == "К":
                    vacation.add(monday)
            break
        if not code and not name and kind:  # продолжение предыдущей дисциплины (объединённые ячейки)
            code, name = last_code, last_name
        if not name:
            continue
        last_code, last_name = code, name
        k = _kind(code, kind)
        if k is None:
            continue  # заголовок цикла/модуля
        hours = {}
        for c, monday in week_cols.items():
            v = cells.get((r, c))
            h = _num(v)
            if h:
                hours[monday] = hours.get(monday, 0) + h
            elif _s(v).upper() == "К":
                vacation.add(monday)
        if hours:
            rows.append({"code": code, "name": name, "kind": k, "hours": hours, "total": sum(hours.values())})

    title = ws.title.strip()
    return {
        "index": index, "title": title, "year": f"{year}-{year + 1}",
        "weeks": [{"monday": w["monday"], "iso_week": w["iso_week"], "sem": w["sem"]} for w in weeks],
        "vacation": sorted(vacation), "rows": rows,
    }


def parse_kug(content: bytes) -> dict:
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception as e:  # noqa: BLE001
        raise KugError("Файл не похож на Excel (.xlsx)") from e
    title = ""
    sheets, errors = [], []
    for i, ws in enumerate(wb.worksheets):
        if not title:
            for row in ws.iter_rows(max_row=3):
                for c in row:
                    if isinstance(c.value, str) and "график" in c.value.lower():
                        title = _s(c.value)
                        break
                if title:
                    break
        try:
            sheets.append(parse_sheet(ws, i))
        except KugError as e:
            errors.append(str(e))
    if not sheets:
        raise KugError("Не удалось разобрать ни один лист. " + " ".join(errors))
    profession = re.sub(r"^календарный учебный график\s*(по\s+(профессии|специальности))?\s*", "", title,
                        flags=re.I).strip()
    return {"title": title, "profession": profession, "sheets": sheets, "errors": errors}


COMPUTER_HINTS = ("adobe", "autodesk", "3ds", "maya", "zbrush", "substance", "marvelous", "html", "css", "javascript",
                  "jquery", "информатик", "информационн", "программир", "компьютер", "баз данных", "веб", "web",
                  "ui/ux", "c++", "c#", ".net", "unity", "android", "php", "java", "sql", "операционные системы",
                  "photoshop", "illustrator", "indesign", "premiere", "aftereffects", "цифров", "моделирование",
                  "допечатн", "типографик", "айдентик", "численные методы")


def guess_room_type(name: str) -> str:
    n = name.lower()
    return "компьютерный класс" if any(h in n for h in COMPUTER_HINTS) else "обычная"
