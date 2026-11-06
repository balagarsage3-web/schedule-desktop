import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'schedule.db'}")
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))

# Шрифт с кириллицей для PDF. Ищем по порядку: переменная окружения, DejaVu (Linux/Docker), Arial (Windows).
PDF_FONT_CANDIDATES = [
    os.getenv("PDF_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
PDF_FONT_BOLD_CANDIDATES = [
    os.getenv("PDF_FONT_BOLD", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
