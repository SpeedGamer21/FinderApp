import os
import sys
import time
import queue
import atexit
import shutil
import ctypes
import tempfile
import hashlib
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageOps, ImageTk


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

BG = "#0f1216"
SURFACE = "#171b21"
SURFACE_ALT = "#1b2027"
RAISED = "#242b35"
BORDER = "#2c3440"
TEXT = "#e7eaf0"
MUTED = "#8a94a6"
ACCENT = "#4f8cff"
PURPLE = "#9b7bf7"
GREEN = "#34c77b"
AMBER = "#f2a93b"
RED = "#ef5350"
SELECT = "#2d4a7a"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_CAPTION = ("Segoe UI Semibold", 8)
FONT_HEADING = ("Segoe UI Semibold", 13)
FONT_TITLE = ("Segoe UI Semibold", 20)
FONT_STAT = ("Segoe UI Semibold", 18)
FONT_MONO = ("Consolas", 9)

IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def center_window(win, width, height):
    win.update_idletasks()
    x = int((win.winfo_screenwidth() / 2) - (width / 2))
    y = int((win.winfo_screenheight() / 2) - (height / 2))
    win.geometry(f"{width}x{height}+{x}+{max(y, 0)}")


def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def format_duration(seconds):
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{seconds:.1f}s"


def norm_path(path):
    """Cheap, syscall-free key for comparing paths that came from the same scan."""
    return os.path.normcase(os.path.normpath(path))


def real_path(path):
    """Resolves links / mapped drives so the same file is recognised however it is spelled."""
    return os.path.normcase(os.path.realpath(path))


def folders_overlap(a, b):
    a, b = real_path(a), real_path(b)
    try:
        common = os.path.commonpath([a, b])
    except ValueError:  # different drives
        return False
    return common in (a, b)


def shade(hex_color, factor):
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]
    rgb = [max(0, min(255, int(c * factor))) for c in rgb]
    return "#" + "".join(f"{c:02x}" for c in rgb)


def send_to_recycle_bin(path):
    """Moves a file to the Windows Recycle Bin. Network drives have no Recycle Bin,
    so Windows deletes files on them permanently."""
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]
        if ctypes.sizeof(ctypes.c_void_p) == 4:
            _pack_ = 1

    FO_DELETE = 0x3
    FOF_SILENT = 0x4
    FOF_NOCONFIRMATION = 0x10
    FOF_ALLOWUNDO = 0x40
    FOF_NOERRORUI = 0x400

    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"  # list must be double-null terminated
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Recycle Bin operation failed (code {result:#x})")


def open_file_location(path):
    try:
        if IS_WINDOWS:
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError as e:
        messagebox.showerror("Could not open folder", str(e))


def apply_dark_titlebar(win):
    if not IS_WINDOWS:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        value = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+), 19 on older builds
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
        # Windows 10 only repaints the title bar after the window is re-shown
        win.withdraw()
        win.deiconify()
    except Exception:
        pass


def load_avatar(size):
    try:
        img = Image.open(resource_path("Jared_niala.jpg")).convert("RGBA")
    except Exception:
        return None
    big = size * 4  # draw the mask large and shrink it for smooth edges
    img = ImageOps.fit(img, (big, big), Image.LANCZOS)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    img.putalpha(mask)
    return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))


def create_demo_folders():
    """Builds two throwaway folders full of fake duplicates for the --demo preview.
    They live in the temp folder and are removed when the app closes."""
    base = tempfile.mkdtemp(prefix="duplicate_finder_demo_")
    atexit.register(shutil.rmtree, base, ignore_errors=True)
    folder_a = os.path.join(base, "My Files")
    folder_b = os.path.join(base, "Backup Drive")

    def write(folder, relative, data):
        path = os.path.join(folder, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    # (name in A, name in B, size) — same content on both sides
    shared = [
        ("Photos/vacation_001.jpg", "old_backup/Photos/vacation_001.jpg", 2_400_000),
        ("Photos/vacation_002.jpg", "old_backup/Photos/vacation_002.jpg", 1_900_000),
        ("Photos/birthday.png", "Pictures/birthday (copy).png", 3_100_000),
        ("Videos/clip.mp4", "Videos/clip.mp4", 12_000_000),
        ("Documents/report.pdf", "Docs/report_final.pdf", 450_000),
        ("Documents/notes.txt", "Docs/notes.txt", 8_000),
        ("Music/song.mp3", "Music/song.mp3", 5_200_000),
    ]
    for name_a, name_b, size in shared:
        data = os.urandom(size)
        write(folder_a, name_a, data)
        write(folder_b, name_b, data)

    # One file in A that has two copies in B
    data = os.urandom(700_000)
    write(folder_a, "Photos/profile.jpg", data)
    write(folder_b, "Pictures/profile.jpg", data)
    write(folder_b, "old_backup/Photos/profile.jpg", data)

    # Same size and same first 64 KB, but different endings — must NOT be reported
    head = os.urandom(64 * 1024)
    write(folder_a, "Projects/build_v1.zip", head + os.urandom(500_000))
    write(folder_b, "Projects/build_v2.zip", head + os.urandom(500_000))

    # Files that only exist on one side, plus empty files (skipped by design)
    write(folder_a, "Documents/only_here.docx", os.urandom(90_000))
    write(folder_b, "Docs/only_on_backup.xlsx", os.urandom(120_000))
    write(folder_a, "empty.log", b"")
    write(folder_b, "empty.log", b"")

    return folder_a, folder_b


def setup_styles(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=RAISED, background=ACCENT, bordercolor=RAISED,
        lightcolor=ACCENT, darkcolor=ACCENT, thickness=10,
    )

    style.layout("Dark.Treeview", [("Dark.Treeview.treearea", {"sticky": "nswe"})])
    style.configure(
        "Dark.Treeview",
        background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
        rowheight=28, borderwidth=0, font=FONT,
    )
    style.map("Dark.Treeview", background=[("selected", SELECT)], foreground=[("selected", "white")])
    style.configure(
        "Dark.Treeview.Heading",
        background=RAISED, foreground=MUTED, relief="flat",
        font=FONT_CAPTION, padding=(8, 7), bordercolor=BORDER,
    )
    style.map("Dark.Treeview.Heading", background=[("active", BORDER)], foreground=[("active", TEXT)])

    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"Dark.{orient}.TScrollbar",
            background=RAISED, troughcolor=SURFACE, bordercolor=SURFACE,
            arrowcolor=MUTED, lightcolor=RAISED, darkcolor=RAISED, gripcount=0,
        )
        style.map(f"Dark.{orient}.TScrollbar", background=[("active", BORDER)])


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------

class FlatButton(tk.Button):
    def __init__(self, parent, text, command, color, fg="white", bold=True, **kwargs):
        self.color = color
        self.hover_color = shade(color, 1.15)
        super().__init__(
            parent, text=text, command=command,
            bg=color, fg=fg, activebackground=shade(color, 0.9), activeforeground=fg,
            disabledforeground=MUTED, relief="flat", bd=0, highlightthickness=0,
            padx=16, pady=7, cursor="hand2", font=FONT_BOLD if bold else FONT,
            **kwargs,
        )
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, inside):
        if str(self["state"]) != "disabled":
            self.config(bg=self.hover_color if inside else self.color)

    def set_enabled(self, enabled):
        self.config(
            state=tk.NORMAL if enabled else tk.DISABLED,
            bg=self.color if enabled else RAISED,
            cursor="hand2" if enabled else "arrow",
        )


def make_card(parent, title=None, padding=(16, 14)):
    outer = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
    inner = tk.Frame(outer, bg=SURFACE)
    inner.pack(fill="both", expand=True, padx=padding[0], pady=padding[1])
    if title:
        tk.Label(inner, text=title.upper(), bg=SURFACE, fg=MUTED, font=FONT_CAPTION).pack(anchor="w", pady=(0, 8))
    return outer, inner


def make_entry(parent, bg=RAISED, **kwargs):
    """An entry with inner padding and a border that lights up on focus."""
    wrap = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=BORDER)
    entry = tk.Entry(
        wrap, bg=bg, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0,
        font=FONT, disabledbackground=bg, **kwargs,
    )
    entry.pack(fill="x", padx=10, pady=7)
    entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=ACCENT))
    entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=BORDER))
    return wrap, entry


def confirm_danger(parent, title, message, confirm_text, on_confirm):
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=SURFACE)
    center_window(dlg, 500, 250)
    dlg.transient(parent)
    dlg.resizable(False, False)

    body = tk.Frame(dlg, bg=SURFACE)
    body.pack(fill="both", expand=True, padx=24, pady=20)

    tk.Label(body, text="⚠  " + title, bg=SURFACE, fg=RED, font=FONT_HEADING).pack(anchor="w")
    tk.Label(
        body, text=message, bg=SURFACE, fg=TEXT, font=FONT,
        justify="left", wraplength=450,
    ).pack(anchor="w", pady=(10, 0))

    buttons = tk.Frame(body, bg=SURFACE)
    buttons.pack(side="bottom", fill="x")

    def confirm():
        dlg.destroy()
        on_confirm()

    FlatButton(buttons, confirm_text, confirm, RED).pack(side="right")
    FlatButton(buttons, "Cancel", dlg.destroy, RAISED, fg=TEXT, bold=False).pack(side="right", padx=(0, 8))

    dlg.bind("<Escape>", lambda e: dlg.destroy())
    apply_dark_titlebar(dlg)
    dlg.grab_set()


# ---------------------------------------------------------------------------
# Scanner (no UI code in here — it only talks through callbacks)
# ---------------------------------------------------------------------------

class DuplicateScanner:
    QUICK_READ_SIZE = 64 * 1024
    FULL_HASH_CHUNK_SIZE = 1024 * 1024
    UI_UPDATE_INTERVAL = 0.2
    TOTAL_STEPS = 3

    def __init__(self, log_callback=None, speed_callback=None, progress_callback=None,
                 stat_callback=None, min_size=1):
        self.stop_event = threading.Event()
        self.log = log_callback or (lambda msg, level="info": None)
        self.speed_callback = speed_callback or (lambda drive, text: None)
        self.progress_callback = progress_callback or (lambda step, label, done, total: None)
        self.stat_callback = stat_callback or (lambda name, value: None)
        # Empty files are all "identical" to each other, so they are skipped by default.
        self.min_size = min_size

        self._lock = threading.Lock()
        self._done = 0

    def stop(self):
        self.stop_event.set()

    def _advance(self, amount):
        with self._lock:
            self._done += amount
            return self._done

    def iter_files(self, folder):
        stack = [folder]
        while stack and not self.stop_event.is_set():
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if self.stop_event.is_set():
                            return
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                # Junctions can loop back on themselves (e.g. old "Application Data")
                                if not getattr(entry, "is_junction", lambda: False)():
                                    stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                yield entry.path, entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue

    def quick_fingerprint(self, file_path, file_size):
        try:
            hasher = hashlib.blake2b(digest_size=16)
            hasher.update(str(file_size).encode("utf-8"))
            with open(file_path, "rb") as f:
                hasher.update(f.read(self.QUICK_READ_SIZE))
            return hasher.hexdigest()
        except OSError:
            return None

    def full_hash(self, file_path, on_chunk):
        try:
            hasher = hashlib.blake2b(digest_size=16)
            with open(file_path, "rb") as f:
                while not self.stop_event.is_set():
                    chunk = f.read(self.FULL_HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    on_chunk(len(chunk))
            if self.stop_event.is_set():
                return None
            return hasher.hexdigest()
        except OSError:
            return None

    def collect_files(self, folder, drive_name):
        files_by_size = defaultdict(list)
        file_count = 0
        start = last_ui_update = time.perf_counter()

        for path, size in self.iter_files(folder):
            file_count += 1
            if size >= self.min_size:
                files_by_size[size].append(path)

            now = time.perf_counter()
            if now - last_ui_update >= self.UI_UPDATE_INTERVAL:
                self.speed_callback(drive_name, f"{file_count / (now - start):,.0f} files/s")
                self.stat_callback(f"listed_{drive_name}", file_count)
                last_ui_update = now

        self.speed_callback(drive_name, "idle")
        self.stat_callback(f"listed_{drive_name}", file_count)
        return files_by_size, file_count

    def quick_group_candidates(self, candidates, drive_name, total):
        grouped = defaultdict(list)
        processed = 0
        start = last_ui_update = time.perf_counter()

        for path, size in candidates:
            if self.stop_event.is_set():
                break

            fp = self.quick_fingerprint(path, size)
            if fp:
                grouped[fp].append((path, size))
            processed += 1
            done = self._advance(1)

            now = time.perf_counter()
            if now - last_ui_update >= self.UI_UPDATE_INTERVAL:
                self.speed_callback(drive_name, f"{processed / (now - start):,.0f} files/s")
                self.progress_callback(2, "Comparing quick fingerprints", done, total)
                last_ui_update = now

        self.speed_callback(drive_name, "idle")
        return grouped

    def full_hash_group(self, candidates, drive_name, total_bytes):
        grouped = defaultdict(list)
        hashed_bytes = 0
        start = last_ui_update = time.perf_counter()

        def on_chunk(size):
            nonlocal hashed_bytes, last_ui_update
            hashed_bytes += size
            done = self._advance(size)
            now = time.perf_counter()
            if now - last_ui_update >= self.UI_UPDATE_INTERVAL:
                speed = hashed_bytes / (now - start)
                self.speed_callback(drive_name, f"{format_size(speed)}/s")
                self.progress_callback(3, "Verifying matches with a full hash", done, total_bytes)
                last_ui_update = now

        for path, size in candidates:
            if self.stop_event.is_set():
                break
            h = self.full_hash(path, on_chunk)
            if h:
                grouped[h].append((path, size))

        self.speed_callback(drive_name, "idle")
        return grouped

    def find_cross_drive_duplicates(self, folder_a, folder_b):
        """Returns a list of (path_in_a, path_in_b, size) for files that exist in both folders."""
        self.stop_event.clear()

        # Step 1: list everything and group by size (cheap — no file contents read)
        self.progress_callback(1, "Listing files", 0, None)
        self.log("Listing files in both folders...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(self.collect_files, folder_a, "A")
            future_b = executor.submit(self.collect_files, folder_b, "B")
            sizes_a, count_a = future_a.result()
            sizes_b, count_b = future_b.result()

        if self.stop_event.is_set():
            return []
        self.log(f"Folder A has {count_a:,} files, Folder B has {count_b:,} files.")

        common_sizes = sizes_a.keys() & sizes_b.keys()
        candidates_a = [(p, s) for s in common_sizes for p in sizes_a[s]]
        candidates_b = [(p, s) for s in common_sizes for p in sizes_b[s]]
        total = len(candidates_a) + len(candidates_b)
        self.stat_callback("candidates", total)

        if not total:
            self.log("No file in A has the same size as a file in B, so there are no duplicates.", "ok")
            return []

        # Step 2: hash the first 64 KB of same-size files to weed out most non-matches
        self.log(f"{total:,} files share a size with a file in the other folder. Comparing fingerprints...")
        self._done = 0
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(self.quick_group_candidates, candidates_a, "A", total)
            future_b = executor.submit(self.quick_group_candidates, candidates_b, "B", total)
            quick_a = future_a.result()
            quick_b = future_b.result()

        if self.stop_event.is_set():
            return []

        common_quick = quick_a.keys() & quick_b.keys()
        final_a = [item for key in common_quick for item in quick_a[key]]
        final_b = [item for key in common_quick for item in quick_b[key]]
        if not final_a:
            self.log("No fingerprints matched, so there are no duplicates.", "ok")
            return []

        # Step 3: hash whole files to be certain
        total_bytes = sum(s for _, s in final_a) + sum(s for _, s in final_b)
        self.log(
            f"{len(final_a) + len(final_b):,} files look identical. "
            f"Verifying {format_size(total_bytes)} with a full hash..."
        )
        self._done = 0
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(self.full_hash_group, final_a, "A", total_bytes)
            future_b = executor.submit(self.full_hash_group, final_b, "B", total_bytes)
            hashes_a = future_a.result()
            hashes_b = future_b.result()

        if self.stop_event.is_set():
            return []

        duplicates = []
        for h in hashes_a.keys() & hashes_b.keys():
            for p1, size in hashes_a[h]:
                for p2, _ in hashes_b[h]:
                    # Never report a file as a duplicate of itself
                    if real_path(p1) != real_path(p2):
                        duplicates.append((p1, p2, size))

        self.progress_callback(3, "Finished", 1, 1)
        return duplicates


# ---------------------------------------------------------------------------
# Results window
# ---------------------------------------------------------------------------

class ResultsWindow:
    COLUMNS = {
        "name": ("File name", 220, "w"),
        "size": ("Size", 90, "e"),
        "path_a": ("In A", 380, "w"),
        "path_b": ("In B", 380, "w"),
    }
    SORT_KEYS = {
        "name": lambda d: os.path.basename(d[0]).lower(),
        "size": lambda d: d[2],
        "path_a": lambda d: d[0].lower(),
        "path_b": lambda d: d[1].lower(),
    }

    def __init__(self, app):
        self.app = app
        self.busy = False
        self.sort_column = "size"
        self.sort_reverse = True

        self.win = tk.Toplevel(app.root)
        self.win.title("Duplicate files")
        self.win.configure(bg=BG)
        self.win.minsize(820, 480)
        center_window(self.win, 1180, 700)

        self._build_header()
        self._build_table()
        self._build_footer()
        self._build_context_menu()

        self.populate()
        apply_dark_titlebar(self.win)

    # -- layout --------------------------------------------------------------

    def _build_header(self):
        header = tk.Frame(self.win, bg=BG)
        header.pack(fill="x", padx=20, pady=(18, 10))

        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        self.summary_label = tk.Label(titles, bg=BG, fg=TEXT, font=FONT_HEADING)
        self.summary_label.pack(anchor="w")
        tk.Label(
            titles, bg=BG, fg=MUTED, font=FONT_SMALL,
            text="Select rows, then choose which side to delete from. Double-click opens the file's folder.",
        ).pack(anchor="w")

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.populate())
        wrap, entry = make_entry(header, bg=SURFACE, textvariable=self.filter_var, width=32)
        wrap.pack(side="right")
        tk.Label(header, text="Filter", bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="right", padx=(0, 8))

    def _build_table(self):
        outer = tk.Frame(self.win, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(fill="both", expand=True, padx=20)

        self.tree = ttk.Treeview(
            outer, columns=tuple(self.COLUMNS), show="headings",
            selectmode="extended", style="Dark.Treeview",
        )
        for col, (_, width, anchor) in self.COLUMNS.items():
            self.tree.column(col, width=width, anchor=anchor, stretch=col.startswith("path"))
        self.tree.tag_configure("odd", background=SURFACE_ALT)
        self.tree.tag_configure("even", background=SURFACE)

        vsb = ttk.Scrollbar(outer, orient="vertical", command=self.tree.yview, style="Dark.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=self.tree.xview, style="Dark.Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_selection_label())
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Control-a>", lambda e: (self.select_all(), "break")[1])

    def _build_footer(self):
        footer = tk.Frame(self.win, bg=BG)
        footer.pack(fill="x", padx=20, pady=14)

        self.select_all_btn = FlatButton(footer, "Select all", self.select_all, RAISED, fg=TEXT, bold=False)
        self.select_all_btn.pack(side="left")
        self.selection_label = tk.Label(footer, bg=BG, fg=MUTED, font=FONT_SMALL)
        self.selection_label.pack(side="left", padx=12)

        FlatButton(footer, "Close", self.win.destroy, RAISED, fg=TEXT, bold=False).pack(side="right")
        self.delete_buttons = [
            FlatButton(footer, "Delete from BOTH", lambda: self.delete("both"), RED),
            FlatButton(footer, "Delete from B", lambda: self.delete("B"), PURPLE),
            FlatButton(footer, "Delete from A", lambda: self.delete("A"), ACCENT),
        ]
        for btn in self.delete_buttons:
            btn.pack(side="right", padx=(0, 8))
        self.delete_buttons[0].pack_configure(padx=(0, 24))  # keep the dangerous one apart

    def _build_context_menu(self):
        self.menu = tk.Menu(
            self.win, tearoff=0, bg=RAISED, fg=TEXT, activebackground=ACCENT,
            activeforeground="white", bd=0, font=FONT,
        )
        self.menu.add_command(label="Show Folder A copy in Explorer", command=lambda: self._open_selected(0))
        self.menu.add_command(label="Show Folder B copy in Explorer", command=lambda: self._open_selected(1))
        self.menu.add_separator()
        self.menu.add_command(label="Copy Folder A path", command=lambda: self._copy_selected(0))
        self.menu.add_command(label="Copy Folder B path", command=lambda: self._copy_selected(1))
        self.tree.bind("<Button-3>", self._on_right_click)

    # -- data ----------------------------------------------------------------

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        query = self.filter_var.get().strip().lower()

        rows = [
            (i, d) for i, d in enumerate(self.app.duplicates)
            if not query or query in d[0].lower() or query in d[1].lower()
        ]
        sort_key = self.SORT_KEYS[self.sort_column]
        rows.sort(key=lambda r: sort_key(r[1]), reverse=self.sort_reverse)

        for n, (i, (p1, p2, size)) in enumerate(rows):
            self.tree.insert(
                "", tk.END, iid=str(i),
                values=(
                    os.path.basename(p1), format_size(size),
                    self._relative(p1, self.app.folder_a), self._relative(p2, self.app.folder_b),
                ),
                tags=("odd" if n % 2 else "even",),
            )

        for col, (title, _, _) in self.COLUMNS.items():
            if col in ("path_a", "path_b"):
                folder = self.app.folder_a if col == "path_a" else self.app.folder_b
                title = f"{title} · {os.path.basename(folder) or folder}"
            arrow = (" ▼" if self.sort_reverse else " ▲") if col == self.sort_column else ""
            self.tree.heading(col, text=title + arrow, anchor="w", command=lambda c=col: self.sort_by(c))

        total = len(self.app.duplicates)
        shown = f" (showing {len(rows):,})" if query else ""
        self.summary_label.config(
            text=f"{total:,} duplicate pair(s) · {format_size(self.app.duplicate_bytes())}{shown}"
        )
        self.update_selection_label()

    @staticmethod
    def _relative(path, folder):
        # Show the part of the path inside the chosen folder; the full path is in the header
        try:
            return os.path.relpath(path, folder)
        except ValueError:
            return path

    def sort_by(self, column):
        if column == self.sort_column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column, self.sort_reverse = column, column == "size"
        self.populate()

    def selected_pairs(self):
        return [self.app.duplicates[int(iid)] for iid in self.tree.selection()]

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def update_selection_label(self):
        pairs = self.selected_pairs()
        if pairs:
            size = sum(p[2] for p in pairs)
            self.selection_label.config(text=f"{len(pairs):,} selected · {format_size(size)}")
        else:
            self.selection_label.config(text="Nothing selected")

    # -- interactions --------------------------------------------------------

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            column = self.tree.identify_column(event.x)
            side = 1 if column == "#4" else 0
            open_file_location(self.app.duplicates[int(iid)][side])

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _focused_pair(self):
        iid = self.tree.focus() or next(iter(self.tree.selection()), None)
        return self.app.duplicates[int(iid)] if iid else None

    def _open_selected(self, side):
        pair = self._focused_pair()
        if pair:
            open_file_location(pair[side])

    def _copy_selected(self, side):
        pair = self._focused_pair()
        if pair:
            self.win.clipboard_clear()
            self.win.clipboard_append(pair[side])

    # -- deleting ------------------------------------------------------------

    def delete(self, mode):
        if self.busy:
            return
        pairs = self.selected_pairs()
        if not pairs:
            messagebox.showwarning("Nothing selected", "Select at least one row first.", parent=self.win)
            return

        recycle = self.app.recycle_var.get() and IS_WINDOWS
        how = "moved to the Recycle Bin" if recycle else "permanently deleted"

        if mode == "both":
            files = len({norm_path(p) for pair in pairs for p in pair[:2]})
            confirm_danger(
                self.win,
                "Delete both copies?",
                f"This removes {files:,} file(s) from BOTH folders, so no copy will be left "
                f"in either place.\n\nFiles will be {how}.",
                "Delete both copies",
                lambda: self._start_delete(pairs, mode, recycle),
            )
            return

        side, other = ("A", "B") if mode == "A" else ("B", "A")
        index = 0 if mode == "A" else 1
        files = len({norm_path(p[index]) for p in pairs})
        if messagebox.askyesno(
            "Confirm delete",
            f"Delete {files:,} file(s) from Folder {side}?\n\n"
            f"The matching copies in Folder {other} are kept.\nFiles will be {how}.",
            icon="warning", parent=self.win,
        ):
            self._start_delete(pairs, mode, recycle)

    def _set_busy(self, busy):
        self.busy = busy
        for btn in self.delete_buttons + [self.select_all_btn]:
            btn.set_enabled(not busy)

    def _start_delete(self, pairs, mode, recycle):
        self._set_busy(True)
        self.summary_label.config(text="Deleting...")
        self.app.set_status("DELETING", AMBER)
        duplicates = list(self.app.duplicates)
        threading.Thread(
            target=self._delete_worker, args=(pairs, mode, recycle, duplicates), daemon=True
        ).start()

    def _delete_worker(self, pairs, mode, recycle, duplicates):
        post, log = self.app.post, self.app.log
        deleted = skipped = failed = 0
        gone = set()      # files that no longer exist after this run
        attempted = set()

        for p1, p2, _ in pairs:
            if mode == "A":
                targets, keepers = [p1], [p2]
            elif mode == "B":
                targets, keepers = [p2], [p1]
            else:
                targets, keepers = [p1, p2], []

            # Safety net: only delete one side if the other copy is really still there
            missing = [k for k in keepers if not os.path.exists(k)]
            if missing:
                skipped += 1
                gone.update(norm_path(k) for k in missing)
                post(log, f"Skipped {targets[0]} because its other copy is gone.", "warn")
                continue

            for target in targets:
                key = norm_path(target)
                if key in attempted:
                    continue
                attempted.add(key)

                if not os.path.exists(target):
                    gone.add(key)
                    skipped += 1
                    continue
                try:
                    if recycle:
                        send_to_recycle_bin(target)
                    else:
                        os.remove(target)
                    deleted += 1
                    gone.add(key)
                    post(log, f"{'Recycled' if recycle else 'Deleted'}: {target}", "muted")
                except OSError as e:
                    failed += 1
                    post(log, f"Failed to delete {target}: {e}", "error")

        # A pair stops being a duplicate as soon as either side is gone
        remaining = [d for d in duplicates if norm_path(d[0]) not in gone and norm_path(d[1]) not in gone]
        post(self._delete_finished, remaining, deleted, skipped, failed)

    def _delete_finished(self, remaining, deleted, skipped, failed):
        self.app.duplicates = remaining
        self.app.refresh_totals()
        self.app.set_status("DONE", GREEN)
        self.app.log(
            f"Delete finished: {deleted:,} removed, {skipped:,} skipped, {failed:,} failed.",
            "error" if failed else "ok",
        )

        if not self.win.winfo_exists():
            return
        self._set_busy(False)
        self.populate()
        if failed:
            messagebox.showwarning(
                "Some files were not deleted",
                f"{failed:,} file(s) could not be deleted. See the activity log for details.",
                parent=self.win,
            )
        elif not remaining:
            messagebox.showinfo("All clean", "No duplicates left.", parent=self.win)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root, demo=False):
        self.root = root
        self.events = queue.Queue()
        self.scanner = None
        self.scan_started = 0.0
        self.duplicates = []
        self.folder_a = self.folder_b = ""
        self.listed = {"A": 0, "B": 0}
        self.results = None
        self.recycle_var = tk.BooleanVar(value=IS_WINDOWS)

        root.title("Duplicate Finder · by SpeedGamer21")
        root.configure(bg=BG)
        root.minsize(900, 680)
        center_window(root, 1040, 780)
        setup_styles(root)

        if demo:
            root.title(root.title() + "  [DEBUG PREVIEW]")
            tk.Label(
                root, bg=AMBER, fg="#1a1a1a", font=FONT_BOLD, pady=5,
                text="DEBUG PREVIEW · using sample files in a temporary folder — nothing real can be deleted",
            ).pack(fill="x")

        self._build_header()
        self._build_folders()
        self._build_stats()
        self._build_progress()
        self._build_log()

        apply_dark_titlebar(root)
        if demo:
            self._load_demo()
        else:
            self.log("Pick two folders and press Start scan.", "muted")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_events()

    def _load_demo(self):
        folder_a, folder_b = create_demo_folders()
        self.entry_a.insert(0, folder_a)
        self.entry_b.insert(0, folder_b)
        # Demo files are throwaway, so don't fill the real Recycle Bin with them
        self.recycle_var.set(False)
        self.log("Debug preview: created sample folders with fake duplicates.", "warn")
        self.log("Expect 9 pairs. The look-alike zip and the empty files must NOT show up.", "muted")
        self.log("Press Start scan. The sample folders are deleted when you close the app.", "muted")

    # -- thread-safe UI updates ---------------------------------------------
    # Tkinter must only be touched from the main thread, so worker threads
    # post (function, args) here and the main loop runs them.

    def post(self, fn, *args):
        self.events.put((fn, args))

    def _poll_events(self):
        try:
            while True:
                fn, args = self.events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self._poll_id = self.root.after(50, self._poll_events)

    def _on_close(self):
        if self.scanner is not None:
            self.scanner.stop()
        self.root.after_cancel(self._poll_id)
        self.root.destroy()

    # -- layout --------------------------------------------------------------

    def _build_header(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 14))

        self.avatar = load_avatar(60)
        if self.avatar:
            tk.Label(header, image=self.avatar, bg=BG).pack(side="left", padx=(0, 14))

        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="Duplicate Finder", bg=BG, fg=TEXT, font=FONT_TITLE).pack(anchor="w")
        tk.Label(
            titles, text="Find files that exist in both folders and clean up the extra copies",
            bg=BG, fg=MUTED, font=FONT,
        ).pack(anchor="w")

        self.status_pill = tk.Label(header, font=FONT_BOLD, padx=14, pady=5)
        self.status_pill.pack(side="right")
        self.set_status("IDLE", RAISED, MUTED)

    def _build_folders(self):
        outer, inner = make_card(self.root, "Folders to compare")
        outer.pack(fill="x", padx=24)

        self.entry_a = self._folder_row(inner, "A", ACCENT)
        self.entry_b = self._folder_row(inner, "B", PURPLE)

        bottom = tk.Frame(inner, bg=SURFACE)
        bottom.pack(fill="x", pady=(10, 0))

        tk.Checkbutton(
            bottom, text="Move deleted files to the Recycle Bin (recommended)",
            variable=self.recycle_var, bg=SURFACE, fg=TEXT, selectcolor=RAISED,
            activebackground=SURFACE, activeforeground=TEXT, font=FONT,
            bd=0, highlightthickness=0, state=tk.NORMAL if IS_WINDOWS else tk.DISABLED,
        ).pack(side="left")

        self.btn_stop = FlatButton(bottom, "Stop", self.stop_scan, RED)
        self.btn_stop.pack(side="right")
        self.btn_stop.set_enabled(False)
        self.btn_start = FlatButton(bottom, "▶  Start scan", self.start_scan, GREEN)
        self.btn_start.pack(side="right", padx=(0, 8))
        self.btn_results = FlatButton(bottom, "View results", self.show_results, RAISED, fg=TEXT, bold=False)
        self.btn_results.pack(side="right", padx=(0, 8))
        self.btn_results.set_enabled(False)

    def _folder_row(self, parent, letter, color):
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", pady=4)

        tk.Label(row, text=letter, bg=color, fg="white", font=FONT_BOLD, width=3, pady=6).pack(side="left")
        tk.Label(row, text=f"Folder {letter}", bg=SURFACE, fg=MUTED, font=FONT, width=9, anchor="w").pack(
            side="left", padx=(10, 0)
        )

        def browse():
            folder = filedialog.askdirectory(parent=self.root, title=f"Choose Folder {letter}")
            if folder:
                entry.delete(0, tk.END)
                entry.insert(0, os.path.normpath(folder))

        FlatButton(row, "Browse…", browse, RAISED, fg=TEXT, bold=False).pack(side="right")
        wrap, entry = make_entry(row)
        wrap.pack(side="left", fill="x", expand=True, padx=(0, 8))
        return entry

    def _build_stats(self):
        stats = tk.Frame(self.root, bg=BG)
        stats.pack(fill="x", padx=24, pady=14)

        tiles = [
            ("listed", "Files listed", TEXT),
            ("candidates", "Same-size candidates", TEXT),
            ("duplicates", "Duplicate pairs", AMBER),
            ("bytes", "Duplicate data", GREEN),
        ]
        self.stat_labels = {}
        for i, (key, title, color) in enumerate(tiles):
            stats.columnconfigure(i, weight=1, uniform="stat")
            tile = tk.Frame(stats, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == len(tiles) - 1 else 6))
            tk.Label(tile, text=title, bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=14, pady=(10, 0))
            value = tk.Label(tile, text="—", bg=SURFACE, fg=color, font=FONT_STAT)
            value.pack(anchor="w", padx=14, pady=(0, 10))
            self.stat_labels[key] = value

    def _build_progress(self):
        outer, inner = make_card(self.root)
        outer.pack(fill="x", padx=24)

        top = tk.Frame(inner, bg=SURFACE)
        top.pack(fill="x")
        self.phase_label = tk.Label(top, text="Ready", bg=SURFACE, fg=TEXT, font=FONT_BOLD)
        self.phase_label.pack(side="left")
        self.percent_label = tk.Label(top, text="", bg=SURFACE, fg=MUTED, font=FONT_BOLD)
        self.percent_label.pack(side="right")

        self.progress = ttk.Progressbar(
            inner, orient="horizontal", mode="determinate", maximum=100,
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(8, 8))

        speeds = tk.Frame(inner, bg=SURFACE)
        speeds.pack(fill="x")
        self.speed_labels = {}
        for letter, color in (("A", ACCENT), ("B", PURPLE)):
            tk.Label(speeds, text="●", bg=SURFACE, fg=color, font=FONT_SMALL).pack(side="left")
            label = tk.Label(speeds, text=f"Folder {letter}: idle", bg=SURFACE, fg=MUTED, font=FONT_SMALL)
            label.pack(side="left", padx=(4, 20))
            self.speed_labels[letter] = label

    def _build_log(self):
        outer, inner = make_card(self.root, "Activity", padding=(16, 12))
        outer.pack(fill="both", expand=True, padx=24, pady=(14, 20))

        frame = tk.Frame(inner, bg=SURFACE)
        frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            frame, bg=SURFACE, fg=TEXT, font=FONT_MONO, relief="flat", bd=0,
            highlightthickness=0, wrap="none", height=8, state=tk.DISABLED,
            selectbackground=SELECT, insertbackground=TEXT,
        )
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview, style="Dark.Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.log_text.tag_configure("time", foreground=shade(MUTED, 0.75))
        self.log_text.tag_configure("info", foreground=TEXT)
        self.log_text.tag_configure("muted", foreground=MUTED)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("warn", foreground=AMBER)
        self.log_text.tag_configure("error", foreground=RED)

    # -- small UI updaters ---------------------------------------------------

    def log(self, message, level="info"):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, time.strftime("%H:%M:%S  "), "time")
        self.log_text.insert(tk.END, message + "\n", level)
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.see(tk.END)

    def set_status(self, text, bg, fg="white"):
        self.status_pill.config(text=f"●  {text}", bg=bg, fg=fg)

    def set_speed(self, drive, text):
        self.speed_labels[drive].config(text=f"Folder {drive}: {text}")

    def set_stat(self, name, value):
        if name.startswith("listed_"):
            self.listed[name[-1]] = value
            self.stat_labels["listed"].config(text=f"{sum(self.listed.values()):,}")
        else:
            self.stat_labels[name].config(text=f"{value:,}")

    def set_progress(self, step, label, done, total):
        self.phase_label.config(text=f"Step {step} of {DuplicateScanner.TOTAL_STEPS} · {label}")
        if total is None:
            if str(self.progress["mode"]) != "indeterminate":
                self.progress.config(mode="indeterminate")
                self.progress.start(12)
            self.percent_label.config(text="")
            return
        if str(self.progress["mode"]) == "indeterminate":
            self.progress.stop()
            self.progress.config(mode="determinate")
        percent = min(100.0, done / total * 100) if total else 100.0
        self.progress["value"] = percent
        self.percent_label.config(text=f"{percent:.0f}%")

    def _reset_progress(self, text, value=0):
        self.progress.stop()
        self.progress.config(mode="determinate")
        self.progress["value"] = value
        self.phase_label.config(text=text)
        self.percent_label.config(text=f"{value:.0f}%" if value else "")

    def duplicate_bytes(self):
        # Size of one copy of each duplicated file, i.e. what deleting one side frees up
        return sum({norm_path(p1): size for p1, _, size in self.duplicates}.values())

    def refresh_totals(self):
        self.stat_labels["duplicates"].config(text=f"{len(self.duplicates):,}")
        self.stat_labels["bytes"].config(text=format_size(self.duplicate_bytes()))
        self.btn_results.set_enabled(bool(self.duplicates))

    # -- scanning ------------------------------------------------------------

    def start_scan(self):
        folder_a = self.entry_a.get().strip()
        folder_b = self.entry_b.get().strip()

        if not folder_a or not folder_b:
            messagebox.showwarning("Missing folders", "Please choose both folders first.")
            return
        if not os.path.isdir(folder_a) or not os.path.isdir(folder_b):
            messagebox.showwarning("Invalid folder", "One or both folders don't exist.")
            return
        if folders_overlap(folder_a, folder_b):
            messagebox.showwarning(
                "Folders overlap",
                "Folder A and Folder B are the same folder, or one is inside the other.\n\n"
                "Files would be matched against themselves, so please choose two separate folders.",
            )
            return

        if self.results and self.results.win.winfo_exists():
            self.results.win.destroy()
        self.folder_a, self.folder_b = os.path.normpath(folder_a), os.path.normpath(folder_b)
        self.duplicates = []
        self.listed = {"A": 0, "B": 0}
        for label in self.stat_labels.values():
            label.config(text="0")
        self.stat_labels["bytes"].config(text="—")
        for drive in self.speed_labels:
            self.set_speed(drive, "idle")

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.log(f"Folder A: {folder_a}", "muted")
        self.log(f"Folder B: {folder_b}", "muted")

        self.set_status("SCANNING", ACCENT)
        self.btn_start.set_enabled(False)
        self.btn_results.set_enabled(False)
        self.btn_stop.set_enabled(True)

        self.scanner = DuplicateScanner(
            log_callback=lambda msg, level="info": self.post(self.log, msg, level),
            speed_callback=lambda drive, text: self.post(self.set_speed, drive, text),
            progress_callback=lambda *args: self.post(self.set_progress, *args),
            stat_callback=lambda name, value: self.post(self.set_stat, name, value),
        )
        self.scan_started = time.perf_counter()
        threading.Thread(target=self._scan_worker, args=(self.scanner, folder_a, folder_b), daemon=True).start()

    def _scan_worker(self, scanner, folder_a, folder_b):
        try:
            duplicates = scanner.find_cross_drive_duplicates(folder_a, folder_b)
        except Exception as e:  # keep the UI usable if something unexpected happens
            self.post(self._scan_failed, e)
            return
        self.post(self._scan_finished, scanner, duplicates)

    def stop_scan(self):
        if self.scanner is not None:
            self.scanner.stop()
        self.btn_stop.set_enabled(False)
        self.set_status("STOPPING", AMBER)
        self.log("Stopping scan...", "warn")

    def _scan_failed(self, error):
        self.btn_start.set_enabled(True)
        self.btn_stop.set_enabled(False)
        self._reset_progress("Scan failed")
        self.set_status("ERROR", RED)
        self.log(f"Scan failed: {error}", "error")

    def _scan_finished(self, scanner, duplicates):
        self.btn_start.set_enabled(True)
        self.btn_stop.set_enabled(False)
        elapsed = format_duration(time.perf_counter() - self.scan_started)

        if scanner.stop_event.is_set():
            self._reset_progress("Stopped")
            self.set_status("STOPPED", AMBER)
            self.log(f"Scan stopped after {elapsed}.", "warn")
            return

        self.duplicates = sorted(duplicates, key=lambda d: d[2], reverse=True)
        self.refresh_totals()
        self._reset_progress("Finished", 100)
        self.set_status("DONE", GREEN)
        self.log(
            f"Scan complete in {elapsed}: {len(self.duplicates):,} duplicate pair(s), "
            f"{format_size(self.duplicate_bytes())} of duplicate data.",
            "ok",
        )

        if self.duplicates:
            self.show_results()
        else:
            messagebox.showinfo("No duplicates", "No files exist in both folders.")

    def show_results(self):
        if self.results and self.results.win.winfo_exists():
            self.results.populate()
            self.results.win.lift()
            self.results.win.focus_force()
            return
        self.results = ResultsWindow(self)


if __name__ == "__main__":
    root = tk.Tk()
    App(root, demo="--demo" in sys.argv)
    root.mainloop()
