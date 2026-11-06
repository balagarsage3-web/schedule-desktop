# Desktop-сборка

Готовый установщик: [скачать Schedule-Setup-1.0.0.exe](https://github.com/balagarsage3-web/schedule-desktop/releases/download/v1.0.0/Schedule-Setup-1.0.0.exe).
Все опубликованные версии находятся в [GitHub Releases](https://github.com/balagarsage3-web/schedule-desktop/releases).
После локальной сборки файл для отправки появляется в `release/Schedule-Setup-1.0.0.exe`.
Поддерживаются Windows 10 (1809+) и Windows 11, x64.

Мастер установки на русском языке устанавливает приложение текущему пользователю,
создаёт ярлыки и предлагает запуск. Python, сервер, решатель и интерфейс уже внутри.
Если WebView2 отсутствует, установщик Microsoft скачивает и устанавливает его;
для этого нужен интернет. При обычной работе интернет не требуется.

Программа открывается в собственном окне, сервер работает только на loopback-интерфейсе
со свободным портом и завершается вместе с приложением. Публичные ссылки в этой
локальной сборке доступны только на этом компьютере, пока приложение открыто.

Данные: `%LOCALAPPDATA%\ScheduleDesktop\schedule.db`.
Журнал запуска: `%LOCALAPPDATA%\ScheduleDesktop\desktop.log`.
Обновление и удаление программы не удаляют пользовательскую базу.
В установщик не включаются база разработчика, резервные копии и исходные Excel-файлы.
Первый вход: `admin` / `admin`.

Для пересборки нужны зависимости backend, `desktop/requirements-build.txt`,
собранный `frontend/dist`, Inno Setup в `installer/tools/Inno` и официальный
WebView2 bootstrapper в `installer/tools/MicrosoftEdgeWebview2Setup.exe`.
Команда: `powershell -ExecutionPolicy Bypass -File desktop/build.ps1`.

`Schedule.exe --smoke-test` проверяет запуск сервера, интерфейс и вход на временной
базе, затем завершает процесс. При успехе рядом с exe появляется `smoke-test-ok.txt`.
