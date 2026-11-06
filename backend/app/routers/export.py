"""Выгрузка расписания: Excel (лист на группу/преподавателя), PDF (печатная недельная сетка), iCal."""
import io
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import current_user
from ..config import PDF_FONT_BOLD_CANDIDATES, PDF_FONT_CANDIDATES
from ..db import get_db
from ..solver.problem import WEEKDAYS, WEEKDAYS_FULL, load_problem, week_start
from .schedule import plessons

router = APIRouter(prefix="/api/export", dependencies=[Depends(current_user)])


def _subjects(p, lessons, mode: str, entity_id: int | None):
    """Список (id, заголовок, короткое имя) для выгрузки и пары, сгруппированные по этим id."""
    if mode == "teacher":
        ids = sorted({p.cur_by_id[ls.cur_id].teacher_id for ls in lessons}, key=lambda i: p.teachers[i].name)
        items = [(i, f"Преподаватель {p.teachers[i].name}", p.teachers[i].name) for i in ids]
        key = lambda ls: p.cur_by_id[ls.cur_id].teacher_id  # noqa: E731
    else:
        ids = sorted({p.cur_by_id[ls.cur_id].group_id for ls in lessons}, key=lambda i: p.groups[i].name)
        items = [(i, f"Группа {p.groups[i].name}", p.groups[i].name) for i in ids]
        key = lambda ls: p.cur_by_id[ls.cur_id].group_id  # noqa: E731
    if entity_id is not None:
        items = [x for x in items if x[0] == entity_id]
        if not items:
            raise HTTPException(404, "В расписании нет пар для выбранного фильтра")
    grouped = defaultdict(list)
    seen = set()
    for ls in lessons:
        if mode == "teacher":  # общая пара потока у преподавателя — одна строка
            sk = (p.unit_of[ls.cur_id].id, ls.date, ls.slot_number)
            if sk in seen:
                continue
            seen.add(sk)
        grouped[key(ls)].append(ls)
    return items, grouped


def _groups_of(p, ls) -> str:
    u = p.unit_of[ls.cur_id]
    return ", ".join(p.groups[g].name for g in u.group_ids)


def _other(p, ls, mode: str) -> str:
    """Для группы — преподаватель (и пометка потока), для преподавателя — группы."""
    u = p.unit_of[ls.cur_id]
    if mode == "teacher":
        return _groups_of(p, ls)
    name = p.teachers[u.teacher_id].name
    return f"{name} (поток: {_groups_of(p, ls)})" if len(u.group_ids) > 1 else name


def _load(db: Session, version_id: int, mode: str, entity_id: int | None):
    v = db.get(m.ScheduleVersion, version_id)
    if v is None:
        raise HTTPException(404, "Версия расписания не найдена")
    p = load_problem(db, v.term_id)
    lessons = sorted(plessons(db, v.id, p), key=lambda x: (x.date, x.slot_number))
    items, grouped = _subjects(p, lessons, mode, entity_id)
    if not items:
        raise HTTPException(404, "В расписании нет пар")
    return v, p, items, grouped


def _meta_lines(p, v, title: str) -> list[str]:
    return [title, f"Период: {p.term_name}, {p.start_date:%d.%m.%Y} – {p.end_date:%d.%m.%Y}",
            f"Версия расписания: №{v.number} «{v.name}» от {v.created_at:%d.%m.%Y %H:%M}",
            f"Дата формирования: {datetime.now():%d.%m.%Y %H:%M}"]


def _filename(base: str, ext: str) -> dict:
    safe = re.sub(r"[^\w\-. ]", "_", base, flags=re.UNICODE).strip() or "schedule"
    return {"Content-Disposition": f"attachment; filename=schedule.{ext}; filename*=UTF-8''{quote(safe)}.{ext}"}


def _sheet_name(name: str, used: set) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "Лист"
    out, i = base, 2
    while out in used:
        suffix = f" ({i})"
        out = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(out)
    return out


@router.get("/{version_id}/xlsx")
def export_xlsx(version_id: int, mode: str = Query("group", pattern="^(group|teacher)$"),
                entity_id: int | None = None, db: Session = Depends(get_db)):
    v, p, items, grouped = _load(db, version_id, mode, entity_id)
    wb = Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="B7C3D0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDE7F5")
    used: set = set()
    other_col = "Группа" if mode == "teacher" else "Преподаватель"
    for eid, title, short in items:
        ws = wb.create_sheet(_sheet_name(short, used))
        for i, line in enumerate(_meta_lines(p, v, f"Расписание: {title}"), start=1):
            ws.cell(i, 1, line).font = Font(bold=(i == 1), size=13 if i == 1 else 10)
        hdr = ["Дата", "День", "Пара", "Время", "Дисциплина", "Тип", other_col, "Аудитория"]
        row0 = 6
        for j, h in enumerate(hdr, start=1):
            c = ws.cell(row0, j, h)
            c.font, c.fill, c.border = Font(bold=True), head_fill, border
        r = row0
        prev_week = None
        for ls in grouped.get(eid, []):
            cur = p.cur_by_id[ls.cur_id]
            subj, slot = p.subjects[cur.subject_id], p.slot_by_number[ls.slot_number]
            other = _other(p, ls, mode)
            room = p.rooms[ls.room_id].number if ls.room_id in p.rooms else "—"
            r += 1
            vals = [ls.date, WEEKDAYS[ls.date.weekday()], ls.slot_number, f"{slot.start:%H:%M}–{slot.end:%H:%M}",
                    subj.name, subj.lesson_type, other, room]
            wk = week_start(ls.date)
            for j, val in enumerate(vals, start=1):
                c = ws.cell(r, j, val)
                c.border = border
                if prev_week is not None and wk != prev_week:
                    c.border = Border(left=thin, right=thin, bottom=thin, top=Side(style="medium", color="44546A"))
            ws.cell(r, 1).number_format = "DD.MM.YYYY"
            prev_week = wk
        ws.cell(r + 2, 1, f"Всего пар: {len(grouped.get(eid, []))}").font = Font(italic=True)
        for col, width in zip("ABCDEFGH", (12, 6, 6, 13, 30, 11, 26, 12)):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = ws.cell(row0 + 1, 1)
        ws.auto_filter.ref = f"A{row0}:H{max(r, row0)}"
        ws.page_setup.orientation = "landscape"
        ws.print_title_rows = f"{row0}:{row0}"
        for row in ws.iter_rows(min_row=row0 + 1, max_row=r):
            for c in row:
                c.alignment = Alignment(vertical="center")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = f"Расписание {items[0][2]}" if entity_id is not None else f"Расписание {v.name}"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers=_filename(name, "xlsx"))


def _register_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    reg = next((f for f in PDF_FONT_CANDIDATES if f and os.path.exists(f)), None)
    bold = next((f for f in PDF_FONT_BOLD_CANDIDATES if f and os.path.exists(f)), None) or reg
    if reg is None:
        raise HTTPException(500, "Не найден шрифт с кириллицей для PDF. Укажите путь в переменной PDF_FONT.")
    if "Sched" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Sched", reg))
        pdfmetrics.registerFont(TTFont("Sched-Bold", bold))
        pdfmetrics.registerFontFamily("Sched", normal="Sched", bold="Sched-Bold", italic="Sched", boldItalic="Sched-Bold")
    return "Sched", "Sched-Bold"


@router.get("/{version_id}/pdf")
def export_pdf(version_id: int, mode: str = Query("group", pattern="^(group|teacher)$"),
               entity_id: int | None = None, week: date | None = None, db: Session = Depends(get_db)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    v, p, items, grouped = _load(db, version_id, mode, entity_id)
    font, font_b = _register_fonts()
    wk = week_start(week or p.start_date)
    days = [wk + timedelta(days=i) for i in range(p.days_per_week)]

    st_title = ParagraphStyle("t", fontName=font_b, fontSize=14, leading=18)
    st_meta = ParagraphStyle("m", fontName=font, fontSize=8.5, leading=11, textColor=colors.HexColor("#44546A"))
    st_cell = ParagraphStyle("c", fontName=font, fontSize=8, leading=10)
    st_cell_b = ParagraphStyle("cb", fontName=font_b, fontSize=8.5, leading=10.5)
    st_head = ParagraphStyle("h", fontName=font_b, fontSize=9, leading=11, alignment=1)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title="Расписание", author="Сервис расписания")
    story = []
    page_w = landscape(A4)[0] - 20 * mm
    for idx, (eid, title, _) in enumerate(items):
        if idx:
            story.append(PageBreak())
        meta = _meta_lines(p, v, title)
        story.append(Paragraph(f"Расписание: {title}", st_title))
        story.append(Paragraph(f"Неделя {days[0]:%d.%m.%Y} – {days[-1]:%d.%m.%Y}", st_cell_b))
        for line in meta[1:]:
            story.append(Paragraph(line, st_meta))
        story.append(Spacer(1, 4 * mm))
        cell = {(ls.date, ls.slot_number): ls for ls in grouped.get(eid, []) if wk <= ls.date < wk + timedelta(days=7)}
        data = [[Paragraph("Пара", st_head)] +
                [Paragraph(f"{WEEKDAYS_FULL[d.weekday()].capitalize()}<br/>{d:%d.%m}"
                           + ("<br/><font size=7>нерабочий</font>" if d in p.non_working else ""), st_head)
                 for d in days]]
        for s in p.slots:
            row = [Paragraph(f"<b>{s.number}</b><br/>{s.start:%H:%M}<br/>{s.end:%H:%M}", st_cell)]
            for d in days:
                ls = cell.get((d, s.number))
                if ls is None:
                    row.append("")
                    continue
                cur = p.cur_by_id[ls.cur_id]
                subj = p.subjects[cur.subject_id]
                other = _other(p, ls, mode)
                room = p.rooms[ls.room_id].number if ls.room_id in p.rooms else "—"
                row.append(Paragraph(f"<b>{subj.name}</b><br/>{subj.lesson_type}<br/>{other}<br/>ауд. {room}", st_cell))
            data.append(row)
        first = 18 * mm
        col = (page_w - first) / len(days)
        t = Table(data, colWidths=[first] + [col] * len(days), repeatRows=1)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9AA9BA")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE7F5")),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F2F5F9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for j, d in enumerate(days, start=1):
            if d in p.non_working:
                style.append(("BACKGROUND", (j, 1), (j, -1), colors.HexColor("#F3F3F3")))
        t.setStyle(TableStyle(style))
        story.append(t)
        total = len(cell)
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"Пар на неделе: {total}", st_meta))
    doc.build(story)
    buf.seek(0)
    name = f"Расписание {items[0][2]} {wk:%d.%m}" if entity_id is not None else f"Расписание {wk:%d.%m}"
    return StreamingResponse(buf, media_type="application/pdf", headers=_filename(name, "pdf"))


@router.get("/{version_id}/ics")
def export_ics(version_id: int, mode: str = Query("group", pattern="^(group|teacher)$"),
               entity_id: int = Query(...), db: Session = Depends(get_db)):
    """Календарь .ics (RFC 5545) — для Google Calendar, Яндекс.Календаря, Outlook."""
    v, p, items, grouped = _load(db, version_id, mode, entity_id)
    eid, title, short = items[0]

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//schedule-service//RU", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{esc('Расписание ' + short)}", "X-WR-TIMEZONE:Europe/Moscow"]
    for ls in grouped.get(eid, []):
        cur = p.cur_by_id[ls.cur_id]
        subj, slot = p.subjects[cur.subject_id], p.slot_by_number[ls.slot_number]
        room = p.rooms[ls.room_id].number if ls.room_id in p.rooms else ""
        other = _other(p, ls, mode)
        start = datetime.combine(ls.date, slot.start)
        end = datetime.combine(ls.date, slot.end)
        lines += ["BEGIN:VEVENT", f"UID:lesson-{ls.id}-v{v.id}@schedule", f"DTSTAMP:{stamp}",
                  f"DTSTART;TZID=Europe/Moscow:{start:%Y%m%dT%H%M%S}", f"DTEND;TZID=Europe/Moscow:{end:%Y%m%dT%H%M%S}",
                  f"SUMMARY:{esc(f'{subj.name} ({subj.lesson_type})')}", f"LOCATION:{esc('ауд. ' + room)}",
                  f"DESCRIPTION:{esc(other)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    body = "\r\n".join(lines).encode()
    return StreamingResponse(io.BytesIO(body), media_type="text/calendar", headers=_filename(f"Расписание {short}", "ics"))
