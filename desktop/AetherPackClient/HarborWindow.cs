using System.Diagnostics;
using System.Net.Http;
using Microsoft.Web.WebView2.WinForms;

namespace AetherPackClient;

internal sealed class HarborWindow : Form
{
    private const int WebPort = 7619;
    private const string WebUrl = "http://127.0.0.1:7619/";

    private readonly Panel _chrome;
    private readonly Label _title;
    private readonly Label _status;
    private readonly Label _boot;
    private readonly WebView2 _web;
    private Process? _kernel;
    private bool _pageReady;

    public HarborWindow()
    {
        Text = "AetherPackBot";
        Width = 1320;
        Height = 860;
        MinimumSize = new Size(980, 640);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(11, 16, 24);
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10f);

        _chrome = new Panel
        {
            Dock = DockStyle.Top,
            Height = 56,
            BackColor = Color.FromArgb(16, 24, 36),
            Padding = new Padding(18, 0, 18, 0),
        };

        _title = new Label
        {
            AutoSize = false,
            Dock = DockStyle.Left,
            Width = 420,
            TextAlign = ContentAlignment.MiddleLeft,
            Text = "AetherPackBot   Harbor + Brain",
            Font = new Font("Segoe UI Semibold", 12.5f),
            ForeColor = Color.FromArgb(232, 240, 250),
        };

        _status = new Label
        {
            AutoSize = false,
            Dock = DockStyle.Right,
            Width = 280,
            TextAlign = ContentAlignment.MiddleRight,
            Text = "booting  :7619",
            Font = new Font("Consolas", 10f),
            ForeColor = Color.FromArgb(120, 190, 170),
        };

        _chrome.Controls.Add(_title);
        _chrome.Controls.Add(_status);

        _boot = new Label
        {
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            Text = "Starting Harbor...\nOpening client on http://127.0.0.1:7619",
            Font = new Font("Segoe UI", 14f),
            ForeColor = Color.FromArgb(180, 210, 230),
            BackColor = Color.FromArgb(11, 16, 24),
        };

        _web = new WebView2
        {
            Dock = DockStyle.Fill,
            Visible = false,
            DefaultBackgroundColor = Color.FromArgb(11, 16, 24),
        };

        Controls.Add(_web);
        Controls.Add(_boot);
        Controls.Add(_chrome);

        Shown += async (_, _) => await BootAsync();
        FormClosing += HarborWindow_FormClosing;
    }

    private async Task BootAsync()
    {
        try
        {
            SetStatus("starting kernel");
            EnsureDashboard();
            await StartKernelAsync();
            SetStatus("waiting :7619");
            await WaitForWebAsync();
            await _web.EnsureCoreWebView2Async();
            _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
            _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            _web.CoreWebView2.Navigate(WebUrl);
            _boot.Visible = false;
            _boot.Enabled = false;
            Controls.Remove(_boot);
            _web.Visible = true;
            _web.BringToFront();
            _pageReady = true;
            SetStatus("live  http://127.0.0.1:7619");
        }
        catch (Exception ex)
        {
            _boot.Text = "Harbor client failed to open.\n" + ex.Message;
            SetStatus("failed");
        }
    }

    private void SetStatus(string text)
    {
        _status.Text = text;
    }

    private static DirectoryInfo FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (var i = 0; i < 8 && dir is not null; i++)
        {
            if (File.Exists(Path.Combine(dir.FullName, "main.py")) &&
                Directory.Exists(Path.Combine(dir.FullName, "aetherpackbot")))
            {
                return dir;
            }
            dir = dir.Parent;
        }

        var fallback = new DirectoryInfo(@"D:\AetherPackBot");
        if (File.Exists(Path.Combine(fallback.FullName, "main.py")))
        {
            return fallback;
        }

        throw new DirectoryNotFoundException("Cannot find AetherPackBot root (main.py).");
    }

    private static void EnsureDashboard()
    {
        var root = FindRoot();
        var dataDist = Path.Combine(root.FullName, "data", "dist", "index.html");
        var dashDist = Path.Combine(root.FullName, "dashboard", "dist", "index.html");
        if (File.Exists(dataDist) || File.Exists(dashDist))
        {
            return;
        }

        var dataDir = Path.Combine(root.FullName, "data", "dist");
        Directory.CreateDirectory(dataDir);
        File.WriteAllText(Path.Combine(dataDir, "index.html"), """
            <!doctype html>
            <html lang="zh-CN">
            <head>
              <meta charset="utf-8"/>
              <title>AetherPackBot</title>
              <style>
                body { margin:0; background:#0b1018; color:#dbe8f4; font:16px/1.5 Segoe UI, sans-serif; display:grid; place-items:center; height:100vh; }
                main { width:min(640px, 90vw); }
                h1 { font-weight:600; letter-spacing:.04em; }
                p { color:#8fb0c6; }
                code { color:#7dceb8; }
              </style>
            </head>
            <body>
              <main>
                <h1>AetherPackBot Harbor</h1>
                <p>Kernel is up. Dashboard files were not built, so this client page is the fallback.</p>
                <p>API lives at <code>/api</code> · port <code>7619</code></p>
              </main>
            </body>
            </html>
            """);
    }

    private static string FindPython(DirectoryInfo root)
    {
        var env = Environment.GetEnvironmentVariable("AETHERPACK_PYTHON");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env))
        {
            return env;
        }

        string[] candidates =
        [
            Path.Combine(root.FullName, ".venv", "Scripts", "python.exe"),
            Path.Combine(root.FullName, "venv", "Scripts", "python.exe"),
            @"D:\1\AstrBot\backend\python\python.exe",
        ];
        foreach (var path in candidates)
        {
            if (File.Exists(path))
            {
                return path;
            }
        }

        return "python";
    }

    private async Task StartKernelAsync()
    {
        if (await PortAliveAsync())
        {
            return;
        }

        var root = FindRoot();
        var python = FindPython(root);
        var psi = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "main.py",
            WorkingDirectory = root.FullName,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        psi.Environment["PYTHONUNBUFFERED"] = "1";

        _kernel = Process.Start(psi) ?? throw new InvalidOperationException("Failed to start AetherPackBot kernel.");
        _ = DrainAsync(_kernel);
    }

    private static async Task DrainAsync(Process process)
    {
        try
        {
            _ = process.StandardOutput.ReadToEndAsync();
            _ = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
        }
        catch
        {
            // ignore drain errors; window owns shutdown
        }
    }

    private static async Task<bool> PortAliveAsync()
    {
        try
        {
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(1.2) };
            using var resp = await http.GetAsync(WebUrl);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static async Task WaitForWebAsync()
    {
        var until = DateTime.UtcNow.AddSeconds(40);
        while (DateTime.UtcNow < until)
        {
            if (await PortAliveAsync())
            {
                return;
            }
            await Task.Delay(400);
        }
        throw new TimeoutException("Web dashboard on :7619 did not come up.");
    }

    private void HarborWindow_FormClosing(object? sender, FormClosingEventArgs e)
    {
        if (_kernel is { HasExited: false })
        {
            try
            {
                _kernel.Kill(entireProcessTree: true);
            }
            catch
            {
                try { _kernel.Kill(); } catch { /* ignore */ }
            }
        }
        _ = _pageReady;
    }
}
