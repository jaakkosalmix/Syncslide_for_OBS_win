import json
import os
import threading
import time
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

def ensure_watchdog_installed():
    try:
        from watchdog.events import FileSystemEventHandler  # noqa: F401
        from watchdog.observers import Observer  # noqa: F401
        return
    except ImportError:
        pass

    import subprocess
    import sys
    import tkinter as _tk
    from tkinter import messagebox as _messagebox

    root = _tk.Tk()
    root.withdraw()

    ok = _messagebox.askyesno(
        "Missing dependency",
        "The watchdog package was not found.\n\nInstall it automatically now?\n\n"
        "The app will run:\n"
        f"{sys.executable} -m pip install watchdog"
    )
    if not ok:
        _messagebox.showerror("Installation cancelled", "watchdog is required for this app to work.")
        root.destroy()
        raise SystemExit(1)

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "watchdog"])
    except Exception as exc:
        _messagebox.showerror(
            "Installation failed",
            "Automatic installation of watchdog failed.\n\n"
            f"Error: {exc}\n\n"
            "You can install it manually with:\n"
            f"{sys.executable} -m pip install watchdog"
        )
        root.destroy()
        raise SystemExit(1)

    _messagebox.showinfo("Installation complete", "watchdog was installed successfully.")
    root.destroy()

ensure_watchdog_installed()

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

APP_NAME = "SyncSlide for OBS"
HOST = "127.0.0.1"
PORT = 3210
DEFAULT_SLIDE_DURATION_MS = 5000
DEFAULT_FADE_DURATION_MS = 1000
DEFAULT_WEB_ROOT = str(Path.home() / "syncslide_obs_web")
SETTINGS_PATH = Path.home() / ".syncslide_obs_settings.json"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SyncSlide for OBS</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body { margin:0; padding:0; width:100%; height:100%; background:#000; overflow:hidden; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    #stage { position:relative; width:100vw; height:100vh; background:#000; }
    .slide { position:absolute; inset:0; width:100%; height:100%; object-fit:__OBJECT_FIT__; opacity:0; transition:opacity __FADE_DURATION_MS__ms ease-in-out; background:#000; }
    .slide.visible { opacity:1; }
    #empty { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:rgba(255,255,255,0.78); font-size:22px; text-align:center; padding:40px; }
  </style>
</head>
<body>
  <div id="stage"><div id="empty">No images found in the selected folders.</div></div>
  <script>
    let slideDurationMs = __SLIDE_DURATION_MS__;
    let fadeDurationMs = __FADE_DURATION_MS__;
    let randomOrder = __RANDOM_ORDER__;
    const MANIFEST_REFRESH_MS = 3000;
    const CONFIG_REFRESH_MS = 1500;

    let manifestImages = [];
    let playQueue = [];
    let queueIndex = 0;
    let slideA = null;
    let slideB = null;
    let showingA = true;
    let slideshowTimer = null;

    function ensureSlides() {
      if (slideA && slideB) return;
      slideA = document.createElement("img");
      slideB = document.createElement("img");
      slideA.className = "slide visible";
      slideB.className = "slide";
      document.getElementById("stage").appendChild(slideA);
      document.getElementById("stage").appendChild(slideB);
    }

    function applyFadeDuration() {
      ensureSlides();
      slideA.style.transition = `opacity ${fadeDurationMs}ms ease-in-out`;
      slideB.style.transition = `opacity ${fadeDurationMs}ms ease-in-out`;
    }

    function updateEmptyState() {
      const el = document.getElementById("empty");
      el.style.display = manifestImages.length ? "none" : "flex";
    }

    function shuffleArray(array) {
      const copy = [...array];
      for (let i = copy.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      return copy;
    }

    function rebuildQueue(preserveCurrent = false) {
      if (!manifestImages.length) {
        playQueue = [];
        queueIndex = 0;
        return;
      }
      const currentUrl =
        preserveCurrent && playQueue.length && queueIndex > 0
          ? playQueue[Math.min(queueIndex - 1, playQueue.length - 1)].url
          : null;

      playQueue = randomOrder ? shuffleArray(manifestImages) : [...manifestImages];

      if (currentUrl) {
        const idx = playQueue.findIndex(img => img.url === currentUrl);
        queueIndex = idx >= 0 ? (idx + 1) % playQueue.length : 0;
      } else {
        queueIndex = 0;
      }
    }

    async function fetchManifest() {
      const res = await fetch(`/manifest?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error("Manifest fetch failed");
      return await res.json();
    }

    async function fetchConfig() {
      const res = await fetch(`/config?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error("Config fetch failed");
      return await res.json();
    }

    function sameImageList(a, b) {
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) {
        if (a[i].url !== b[i].url) return false;
      }
      return true;
    }

    async function updateManifest() {
      try {
        const data = await fetchManifest();
        const newImages = data.images || [];
        if (!sameImageList(manifestImages, newImages)) {
          manifestImages = newImages;
          updateEmptyState();
          rebuildQueue(true);
        }
      } catch (err) {
        console.error(err);
      }
    }

    async function updateConfig() {
      try {
        const data = await fetchConfig();
        const newSlide = Math.max(1000, parseInt(data.slide_duration_ms || 5000, 10));
        const newFade = Math.max(0, parseInt(data.fade_duration_ms || 1000, 10));
        const newRandom = !!data.random_order;
        if (newSlide !== slideDurationMs) {
          slideDurationMs = newSlide;
          restartSlideshowTimer();
        }
        if (newFade !== fadeDurationMs) {
          fadeDurationMs = newFade;
          applyFadeDuration();
        }
        if (newRandom !== randomOrder) {
          randomOrder = newRandom;
          rebuildQueue(true);
        }
      } catch (err) {
        console.error(err);
      }
    }

    function showImage(url) {
      ensureSlides();
      const visible = showingA ? slideA : slideB;
      const hidden = showingA ? slideB : slideA;
      hidden.onload = () => {
        hidden.classList.add("visible");
        visible.classList.remove("visible");
        showingA = !showingA;
      };
      hidden.src = url + `&cb=${Date.now()}`;
    }

    async function showNextSlide() {
      await updateManifest();
      if (!playQueue.length) {
        restartSlideshowTimer();
        return;
      }
      if (queueIndex >= playQueue.length) rebuildQueue(false);
      const image = playQueue[queueIndex];
      showImage(image.url);
      queueIndex += 1;
      if (queueIndex >= playQueue.length) rebuildQueue(false);
      restartSlideshowTimer();
    }

    function restartSlideshowTimer() {
      if (slideshowTimer) clearTimeout(slideshowTimer);
      slideshowTimer = setTimeout(showNextSlide, slideDurationMs);
    }

    async function init() {
      ensureSlides();
      applyFadeDuration();
      await updateManifest();
      await updateConfig();
      updateEmptyState();
      rebuildQueue(false);
      if (playQueue.length) {
        showImage(playQueue[0].url);
        queueIndex = 1;
        if (queueIndex >= playQueue.length) rebuildQueue(false);
      }
      restartSlideshowTimer();
      setInterval(updateManifest, MANIFEST_REFRESH_MS);
      setInterval(updateConfig, CONFIG_REFRESH_MS);
    }

    init();
  </script>
</body>
</html>
"""

def render_index_html(slide_duration_ms: int, fade_duration_ms: int, object_fit: str, random_order: bool) -> str:
    html = HTML_TEMPLATE.replace("__SLIDE_DURATION_MS__", str(max(1000, int(slide_duration_ms))))
    html = html.replace("__FADE_DURATION_MS__", str(max(0, int(fade_duration_ms))))
    html = html.replace("__OBJECT_FIT__", "cover" if object_fit == "cover" else "contain")
    html = html.replace("__RANDOM_ORDER__", "true" if random_order else "false")
    return html

class ConfigState:
    def __init__(self):
        self.lock = threading.Lock()
        self.slide_duration_ms = DEFAULT_SLIDE_DURATION_MS
        self.fade_duration_ms = DEFAULT_FADE_DURATION_MS
        self.random_order = False

    def set_values(self, slide_duration_ms: int, fade_duration_ms: int, random_order: bool):
        with self.lock:
            self.slide_duration_ms = max(1000, int(slide_duration_ms))
            self.fade_duration_ms = max(0, int(fade_duration_ms))
            self.random_order = bool(random_order)

    def get_json(self):
        with self.lock:
            return json.dumps({
                "slide_duration_ms": int(self.slide_duration_ms),
                "fade_duration_ms": int(self.fade_duration_ms),
                "random_order": bool(self.random_order),
            }).encode("utf-8")

class ManifestState:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {"images": [], "updated": int(time.time())}
        self.image_dirs = []

    def set_dirs(self, image_dirs):
        self.image_dirs = list(image_dirs)
        self.rebuild()

    def rebuild(self):
        images = []
        now_ts = int(time.time())
        seen = set()
        for image_dir in self.image_dirs:
            if not image_dir or not os.path.isdir(image_dir):
                continue
            files = []
            for name in os.listdir(image_dir):
                full_path = os.path.join(image_dir, name)
                ext = os.path.splitext(name)[1].lower()
                if os.path.isfile(full_path) and ext in ALLOWED_EXTENSIONS:
                    files.append(name)
            files.sort(key=lambda s: s.lower())
            for name in files:
                full_path = os.path.join(image_dir, name)
                dedupe_key = os.path.abspath(full_path)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                try:
                    mtime = int(os.path.getmtime(full_path))
                except OSError:
                    mtime = now_ts
                encoded_path = urllib.parse.quote(full_path)
                images.append({"name": name, "url": f"/images/{encoded_path}?v={mtime}"})
        with self.lock:
            self.data = {"images": images, "updated": now_ts}

    def get_json(self):
        with self.lock:
            return json.dumps(self.data).encode("utf-8")

class SlideshowHandler(BaseHTTPRequestHandler):
    manifest_state = None
    config_state = None
    index_html_path = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._serve_index_html(); return
        if path == "/manifest":
            self._send_bytes(self.manifest_state.get_json(), "application/json; charset=utf-8"); return
        if path == "/config":
            self._send_bytes(self.config_state.get_json(), "application/json; charset=utf-8"); return
        if path.startswith("/images/"):
            encoded_path = path[len("/images/"):]
            file_path = urllib.parse.unquote(encoded_path)
            self._serve_image(file_path); return
        self.send_error(404, "Not found")

    def _serve_index_html(self):
        index_path = self.index_html_path
        if index_path and os.path.isfile(index_path):
            try:
                with open(index_path, "rb") as f:
                    data = f.read()
                self._send_bytes(data, "text/html; charset=utf-8")
                return
            except OSError as exc:
                self.send_error(500, f"Failed to read index.html: {exc}")
                return
        self._send_bytes(render_index_html(DEFAULT_SLIDE_DURATION_MS, DEFAULT_FADE_DURATION_MS, "contain", False).encode("utf-8"), "text/html; charset=utf-8")

    def _serve_image(self, file_path: str):
        if not os.path.isfile(file_path):
            self.send_error(404, "Image not found")
            return
        ext = os.path.splitext(file_path)[1].lower()
        content_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".webp": "image/webp",
        }.get(ext, "application/octet-stream")
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self._send_bytes(data, content_type)
        except OSError as exc:
            self.send_error(500, f"Failed to read image: {exc}")

    def _send_bytes(self, data: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return

class FolderWatcher(FileSystemEventHandler):
    def __init__(self, manifest_state: ManifestState, on_change_callback):
        self.manifest_state = manifest_state
        self.on_change_callback = on_change_callback
        self.last_run = 0.0

    def on_any_event(self, event):
        now = time.time()
        if now - self.last_run < 1.0:
            return
        self.last_run = now
        self.manifest_state.rebuild()
        if self.on_change_callback:
            self.on_change_callback()

class ServerController:
    def __init__(self, manifest_state: ManifestState, config_state: ConfigState, on_change_callback=None):
        self.manifest_state = manifest_state
        self.config_state = config_state
        self.on_change_callback = on_change_callback
        self.httpd = None
        self.server_thread = None
        self.observers = []
        self.running = False

    def start(self, image_dirs, web_root_dir=None):
        if self.running:
            self.stop()
        self.manifest_state.set_dirs(image_dirs)
        handler_class = type("AppSlideshowHandler", (SlideshowHandler,), {})
        handler_class.manifest_state = self.manifest_state
        handler_class.config_state = self.config_state
        handler_class.index_html_path = os.path.join(web_root_dir, "index.html") if web_root_dir else None
        self.httpd = HTTPServer((HOST, PORT), handler_class)
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        for image_dir in image_dirs:
            if image_dir and os.path.isdir(image_dir):
                watcher = FolderWatcher(self.manifest_state, self.on_change_callback)
                observer = Observer()
                observer.schedule(watcher, image_dir, recursive=False)
                observer.start()
                self.observers.append(observer)
        self.running = True

    def update_config(self, slide_duration_ms: int, fade_duration_ms: int, random_order: bool):
        self.config_state.set_values(slide_duration_ms, fade_duration_ms, random_order)

    def stop(self):
        for observer in self.observers:
            observer.stop()
            observer.join(timeout=2)
        self.observers = []
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.server_thread is not None:
            self.server_thread.join(timeout=2)
            self.server_thread = None
        self.running = False

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1080x650")
        self.resizable(False, False)
        self.manifest_state = ManifestState()
        self.config_state = ConfigState()
        self.server = ServerController(self.manifest_state, self.config_state, self.on_folder_change)
        self.status_var = tk.StringVar(value="Select one or more image folders and a web folder.")
        self.url_var = tk.StringVar(value=f"http://{HOST}:{PORT}")
        self.web_root_var = tk.StringVar(value=DEFAULT_WEB_ROOT)
        self.slide_seconds_var = tk.StringVar(value=str(DEFAULT_SLIDE_DURATION_MS // 1000))
        self.fade_ms_var = tk.StringVar(value=str(DEFAULT_FADE_DURATION_MS))
        self.fit_mode_var = tk.StringVar(value="contain")
        self.random_order_var = tk.BooleanVar(value=False)
        self.autostart_var = tk.BooleanVar(value=False)
        self.load_settings()
        self.create_widgets()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_widgets(self):
        pad = {"padx": 14, "pady": 8}
        ttk.Label(self, text=APP_NAME, font=("Arial", 18, "bold")).pack(anchor="w", **pad)
        ttk.Label(self, text="Multi-folder browser slideshow for OBS. Add one or more image folders, then use the Browser Source URL below in OBS.", wraplength=1000, justify="left").pack(anchor="w", fill="x", **pad)

        folders_outer = ttk.LabelFrame(self, text="Image folders / playlist")
        folders_outer.pack(fill="both", padx=14, pady=8)
        folders_frame = ttk.Frame(folders_outer)
        folders_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.folder_list = tk.Listbox(folders_frame, height=7, width=100)
        self.folder_list.grid(row=0, column=0, rowspan=6, sticky="nsew")
        folders_frame.columnconfigure(0, weight=1)
        scrollbar = ttk.Scrollbar(folders_frame, orient="vertical", command=self.folder_list.yview)
        scrollbar.grid(row=0, column=1, rowspan=6, sticky="ns")
        self.folder_list.configure(yscrollcommand=scrollbar.set)
        ttk.Button(folders_frame, text="Add folder…", command=self.add_folder).grid(row=0, column=2, padx=(10, 0), sticky="ew")
        ttk.Button(folders_frame, text="Remove", command=self.remove_folder).grid(row=1, column=2, padx=(10, 0), sticky="ew")
        ttk.Button(folders_frame, text="Move up", command=self.move_folder_up).grid(row=2, column=2, padx=(10, 0), sticky="ew")
        ttk.Button(folders_frame, text="Move down", command=self.move_folder_down).grid(row=3, column=2, padx=(10, 0), sticky="ew")
        ttk.Button(folders_frame, text="Clear all", command=self.clear_folders).grid(row=4, column=2, padx=(10, 0), sticky="ew")

        config_frame = ttk.LabelFrame(self, text="Playback and output")
        config_frame.pack(fill="x", padx=14, pady=8)
        grid = ttk.Frame(config_frame)
        grid.pack(fill="x", padx=10, pady=10)
        for c in (1, 3, 5):
            grid.columnconfigure(c, weight=1)

        ttk.Label(grid, text="Web folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.web_root_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(grid, text="Browse…", command=self.choose_web_root).grid(row=0, column=2, sticky="w")
        ttk.Label(grid, text="OBS Browser URL:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(grid, textvariable=self.url_var, state="readonly").grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        ttk.Button(grid, text="Copy URL", command=self.copy_url).grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(grid, text="Slide duration (sec):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(grid, from_=1, to=3600, textvariable=self.slide_seconds_var, width=10, command=self.save_settings).grid(row=2, column=1, sticky="w", padx=(8, 8), pady=(8, 0))
        ttk.Label(grid, text="Fade duration (ms):").grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Spinbox(grid, from_=0, to=10000, textvariable=self.fade_ms_var, width=10, command=self.save_settings).grid(row=2, column=3, sticky="w", padx=(8, 8), pady=(8, 0))
        ttk.Label(grid, text="Image fit:").grid(row=2, column=4, sticky="w", pady=(8, 0))
        ttk.Combobox(grid, textvariable=self.fit_mode_var, values=["contain", "cover"], width=12, state="readonly").grid(row=2, column=5, sticky="w", padx=(8, 8), pady=(8, 0))
        ttk.Checkbutton(grid, text="Random order (shuffle full list)", variable=self.random_order_var, command=self.save_settings).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
        buttons = ttk.Frame(grid)
        buttons.grid(row=4, column=0, columnspan=6, sticky="w", pady=(12, 0))
        ttk.Button(buttons, text="Apply playback now", command=self.apply_timing_now).pack(side="left")
        ttk.Button(buttons, text="Open preview", command=self.open_preview).pack(side="left", padx=(8, 0))

        runtime = ttk.Frame(self)
        runtime.pack(fill="x", padx=14, pady=8)
        self.start_button = ttk.Button(runtime, text="Start", command=self.start_server)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(runtime, text="Stop", command=self.stop_server, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Checkbutton(runtime, text="Start server automatically on launch", variable=self.autostart_var, command=self.save_settings).pack(side="left", padx=(14, 0))

        status_frame = ttk.LabelFrame(self, text="Status")
        status_frame.pack(fill="both", expand=True, padx=14, pady=8)
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=1000, justify="left").pack(anchor="w", padx=10, pady=10)

        if self.autostart_var.get() and self.get_folders():
            self.after(300, self.start_server)

    def get_folders(self): return list(self.folder_list.get(0, tk.END))
    def set_folders(self, folders):
        self.folder_list.delete(0, tk.END)
        for folder in folders: self.folder_list.insert(tk.END, folder)

    def add_folder(self):
        folder = filedialog.askdirectory(initialdir=str(Path.home()), title="Select image folder")
        if folder and folder not in self.get_folders():
            self.folder_list.insert(tk.END, folder); self.save_settings(); self.status_var.set(f"Added folder: {folder}")

    def remove_folder(self):
        sel = self.folder_list.curselection()
        if not sel: return
        for idx in reversed(sel): self.folder_list.delete(idx)
        self.save_settings(); self.status_var.set("Selected folder removed.")

    def move_folder_up(self):
        sel = self.folder_list.curselection()
        if not sel or sel[0] == 0: return
        idx = sel[0]; value = self.folder_list.get(idx)
        self.folder_list.delete(idx); self.folder_list.insert(idx - 1, value); self.folder_list.selection_set(idx - 1); self.save_settings()

    def move_folder_down(self):
        sel = self.folder_list.curselection()
        if not sel or sel[0] >= self.folder_list.size() - 1: return
        idx = sel[0]; value = self.folder_list.get(idx)
        self.folder_list.delete(idx); self.folder_list.insert(idx + 1, value); self.folder_list.selection_set(idx + 1); self.save_settings()

    def clear_folders(self):
        self.folder_list.delete(0, tk.END); self.save_settings(); self.status_var.set("Playlist cleared.")

    def choose_web_root(self):
        initial = self.web_root_var.get() or str(Path.home())
        folder = filedialog.askdirectory(initialdir=initial, title="Select web folder")
        if folder:
            self.web_root_var.set(folder); self.save_settings(); self.status_var.set(f"Web folder selected: {folder}")

    def get_slide_duration_ms(self):
        try: seconds = int(float(self.slide_seconds_var.get().strip().replace(",", ".")))
        except Exception: seconds = DEFAULT_SLIDE_DURATION_MS // 1000
        seconds = max(1, seconds); self.slide_seconds_var.set(str(seconds)); return seconds * 1000

    def get_fade_duration_ms(self):
        try: ms = int(float(self.fade_ms_var.get().strip().replace(",", ".")))
        except Exception: ms = DEFAULT_FADE_DURATION_MS
        ms = max(0, ms); self.fade_ms_var.set(str(ms)); return ms

    def ensure_index_html(self, web_root: str):
        os.makedirs(web_root, exist_ok=True)
        index_path = os.path.join(web_root, "index.html")
        html = render_index_html(self.get_slide_duration_ms(), self.get_fade_duration_ms(), self.fit_mode_var.get().strip() or "contain", self.random_order_var.get())
        created = not os.path.exists(index_path)
        with open(index_path, "w", encoding="utf-8") as f: f.write(html)
        return index_path, created

    def apply_timing_now(self):
        slide_ms = self.get_slide_duration_ms(); fade_ms = self.get_fade_duration_ms(); random_order = self.random_order_var.get()
        self.save_settings(); web_root = self.web_root_var.get().strip() or DEFAULT_WEB_ROOT
        try:
            index_path, _ = self.ensure_index_html(web_root)
            if self.server.running:
                self.server.update_config(slide_ms, fade_ms, random_order)
                self.status_var.set(f"Playback updated immediately. Slide: {slide_ms // 1000}s | Fade: {fade_ms}ms | Random: {'On' if random_order else 'Off'} | index.html updated: {index_path}")
            else:
                self.status_var.set(f"Playback saved. Slide: {slide_ms // 1000}s | Fade: {fade_ms}ms | Random: {'On' if random_order else 'Off'} | index.html updated: {index_path}")
        except OSError as exc:
            messagebox.showerror("Update failed", f"Failed to update index.html.\n\n{exc}")

    def start_server(self):
        folders = self.get_folders(); web_root = self.web_root_var.get().strip() or DEFAULT_WEB_ROOT
        if not folders:
            messagebox.showwarning("Image folders missing", "Add at least one image folder first."); return
        for folder in folders:
            if not os.path.isdir(folder):
                messagebox.showerror("Error", f"Folder does not exist:\n{folder}"); return
        try:
            slide_ms = self.get_slide_duration_ms(); fade_ms = self.get_fade_duration_ms(); random_order = self.random_order_var.get()
            index_path, created = self.ensure_index_html(web_root)
            self.config_state.set_values(slide_ms, fade_ms, random_order)
            self.server.start(folders, web_root)
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            msg = "Server running. index.html created:" if created else "Server running. index.html updated:"
            self.status_var.set(f"{msg} {index_path} | Folders: {len(folders)} | Slide: {slide_ms // 1000}s | Fade: {fade_ms}ms | Random: {'On' if random_order else 'Off'}")
            self.save_settings()
        except OSError as exc:
            message = f"Could not start server.\n\n{exc}\n\nCheck that port {PORT} is not already in use."
            messagebox.showerror("Startup failed", message)

    def stop_server(self):
        self.server.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("Server stopped.")

    def open_preview(self): webbrowser.open(self.url_var.get())

    def copy_url(self):
        self.clipboard_clear(); self.clipboard_append(self.url_var.get()); self.status_var.set("URL copied to clipboard.")

    def on_folder_change(self):
        self.after(0, lambda: self.status_var.set("Folders updated. New images are now visible in preview and OBS."))

    def load_settings(self):
        folders = []
        if SETTINGS_PATH.exists():
            try:
                data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                folders = data.get("folders", [])
                self.web_root_var.set(data.get("web_root", DEFAULT_WEB_ROOT))
                self.slide_seconds_var.set(str(data.get("slide_seconds", DEFAULT_SLIDE_DURATION_MS // 1000)))
                self.fade_ms_var.set(str(data.get("fade_ms", DEFAULT_FADE_DURATION_MS)))
                self.fit_mode_var.set(data.get("fit_mode", "contain"))
                self.random_order_var.set(bool(data.get("random_order", False)))
                self.autostart_var.set(bool(data.get("autostart", False)))
            except Exception:
                self.web_root_var.set(DEFAULT_WEB_ROOT)
                self.slide_seconds_var.set(str(DEFAULT_SLIDE_DURATION_MS // 1000))
                self.fade_ms_var.set(str(DEFAULT_FADE_DURATION_MS))
                self.fit_mode_var.set("contain")
                self.random_order_var.set(False)
        else:
            self.web_root_var.set(DEFAULT_WEB_ROOT)
            self.slide_seconds_var.set(str(DEFAULT_SLIDE_DURATION_MS // 1000))
            self.fade_ms_var.set(str(DEFAULT_FADE_DURATION_MS))
            self.fit_mode_var.set("contain")
            self.random_order_var.set(False)
        self.after(0, lambda: self.set_folders(folders))

    def save_settings(self):
        try: slide_seconds = max(1, int(float(self.slide_seconds_var.get().strip().replace(",", "."))))
        except Exception:
            slide_seconds = DEFAULT_SLIDE_DURATION_MS // 1000; self.slide_seconds_var.set(str(slide_seconds))
        try: fade_ms = max(0, int(float(self.fade_ms_var.get().strip().replace(",", "."))))
        except Exception:
            fade_ms = DEFAULT_FADE_DURATION_MS; self.fade_ms_var.set(str(fade_ms))
        data = {
            "folders": self.get_folders(),
            "web_root": self.web_root_var.get().strip() or DEFAULT_WEB_ROOT,
            "slide_seconds": slide_seconds,
            "fade_ms": fade_ms,
            "fit_mode": self.fit_mode_var.get().strip() or "contain",
            "random_order": bool(self.random_order_var.get()),
            "autostart": bool(self.autostart_var.get()),
        }
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def on_close(self):
        try: self.server.stop()
        finally: self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
