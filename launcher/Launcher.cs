using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

internal static class Launcher
{
    private const string Url = "http://127.0.0.1:8000";

    private static bool Ready()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(Url + "/api/health");
            request.Timeout = 700;
            request.Proxy = null;
            using (var response = request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream()))
                return reader.ReadToEnd().Replace(" ", "").Contains("\"ok\":true");
        }
        catch { return false; }
    }

    private static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.Title = "Расписание — сервер приложения";
        bool smoke = Array.IndexOf(args, "--smoke-test") >= 0;
        bool check = Array.IndexOf(args, "--check") >= 0;
        Process server = null;
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string backend = Path.Combine(root, "backend");
            string python = Path.Combine(backend, ".venv", "Scripts", "python.exe");
            if (!File.Exists(Path.Combine(backend, "app", "main.py")))
                throw new Exception("Поместите exe рядом с папками backend и frontend.");
            if (!File.Exists(python))
                throw new Exception("Не найдено Python-окружение. Сначала запустите run.ps1 для установки зависимостей.");
            if (!File.Exists(Path.Combine(root, "frontend", "dist", "index.html")))
                throw new Exception("Не найден собранный интерфейс. Сначала запустите run.ps1.");
            if (check)
            {
                Console.WriteLine("Файлы проекта и Python-окружение найдены.");
                return 0;
            }
            if (!Ready())
            {
                var probe = new TcpListener(IPAddress.Loopback, 8000);
                try { probe.Start(); }
                catch (SocketException) { throw new Exception("Порт 8000 занят другой программой. Освободите порт и повторите запуск."); }
                finally { probe.Stop(); }
                Console.WriteLine("Запуск приложения. Для остановки нажмите Ctrl+C или закройте это окно.");
                server = Process.Start(new ProcessStartInfo(python,
                    "-m uvicorn app.main:app --host 127.0.0.1 --port 8000")
                {
                    WorkingDirectory = backend,
                    UseShellExecute = false
                });
                var timer = Stopwatch.StartNew();
                while (!Ready())
                {
                    if (server.HasExited)
                        throw new Exception("Сервер завершился с кодом " + server.ExitCode + ". Подробности указаны выше.");
                    if (timer.Elapsed.TotalSeconds > 60)
                        throw new Exception("Сервер не запустился за 60 секунд.");
                    Thread.Sleep(250);
                }
            }
            Console.WriteLine("Приложение доступно: " + Url);
            if (smoke) return 0;
            Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
            if (server != null) { server.WaitForExit(); return server.ExitCode; }
            return 0;
        }
        catch (Exception error)
        {
            Console.WriteLine("Ошибка: " + error.Message);
            if (!smoke && !check) { Console.WriteLine("Нажмите Enter для закрытия."); Console.ReadLine(); }
            return 1;
        }
        finally
        {
            if (server != null)
            {
                if (!server.HasExited) server.Kill();
                server.Dispose();
            }
        }
    }
}
