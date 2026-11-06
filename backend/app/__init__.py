import os

# Ускоряющие C-расширения SQLAlchemy могут блокироваться политикой Windows (Smart App Control).
# Чистый Python-режим работает везде, разница в скорости для этого сервиса несущественна.
os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")
