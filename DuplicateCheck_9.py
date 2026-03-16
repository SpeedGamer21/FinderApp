import os
import sys
import time
import hashlib
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageTk


def center_window(win, width, height):
    win.update_idletasks()
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = int((screen_width / 2) - (width / 2))
    y = int((screen_height / 2) - (height / 2))
    win.geometry(f"{width}x{height}+{x}+{y}")


def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


class DuplicateScanner:
    def __init__(self, ui_callback=None, speed_callback=None, progress_callback=None):
        self.stop_event = threading.Event()
        self.ui_callback = ui_callback or (lambda msg: None)
        self.speed_callback = speed_callback or (lambda drive, speed: None)
        self.progress_callback = progress_callback or (lambda scanned, total, duplicates: None)

        self.total_files = 0
        self.scanned_files = 0
        self.duplicates = []
        self._lock = threading.Lock()

    def stop(self):
        self.stop_event.set()

    def count_files(self, folder):
        count = 0
        for _, _, files in os.walk(folder):
            if self.stop_event.is_set():
                break
            count += len(files)
        return count

    def hash_file(self, file_path, chunk_size=1024 * 1024):
        hasher = hashlib.md5()
        bytes_read = 0

        try:
            with open(file_path, "rb") as f:
                while True:
                    if self.stop_event.is_set():
                        return None, 0

                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    hasher.update(chunk)
                    bytes_read += len(chunk)

            return hasher.hexdigest(), bytes_read
        except (OSError, PermissionError):
            return None, 0

    def collect_files_by_size(self, folder, drive_name):
        grouped = defaultdict(list)
        total_bytes = 0
        start = time.perf_counter()
        last_ui_update = start

        for root_dir, _, files in os.walk(folder):
            if self.stop_event.is_set():
                break

            for name in files:
                if self.stop_event.is_set():
                    break

                path = os.path.join(root_dir, name)

                try:
                    size = os.path.getsize(path)
                    grouped[size].append(path)
                    total_bytes += size
                except (OSError, PermissionError):
                    pass

                with self._lock:
                    self.scanned_files += 1
                    scanned = self.scanned_files
                    total = self.total_files

                now = time.perf_counter()
                if now - last_ui_update >= 0.2:
                    elapsed = now - start
                    speed_mb = (total_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    self.speed_callback(drive_name, speed_mb)
                    self.progress_callback(scanned, total, len(self.duplicates))
                    last_ui_update = now

        self.speed_callback(drive_name, 0.0)
        return grouped

    def hash_candidates(self, paths, drive_name):
        grouped = defaultdict(list)
        total_bytes = 0
        start = time.perf_counter()
        last_ui_update = start

        for path in paths:
            if self.stop_event.is_set():
                break

            file_hash, bytes_processed = self.hash_file(path)
            total_bytes += bytes_processed

            if file_hash:
                grouped[file_hash].append(path)

            now = time.perf_counter()
            if now - last_ui_update >= 0.2:
                elapsed = now - start
                speed_mb = (total_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                self.speed_callback(drive_name, speed_mb)
                last_ui_update = now

        self.speed_callback(drive_name, 0.0)
        return grouped

    def find_cross_drive_duplicates(self, drive1, drive2):
        self.stop_event.clear()
        self.scanned_files = 0
        self.duplicates = []

        self.ui_callback("Counting files...")
        total_1 = self.count_files(drive1)
        if self.stop_event.is_set():
            return []

        total_2 = self.count_files(drive2)
        if self.stop_event.is_set():
            return []

        self.total_files = total_1 + total_2
        self.progress_callback(0, self.total_files, 0)

        self.ui_callback("Scanning folders and grouping by file size...")

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(self.collect_files_by_size, drive1, "Drive 1")
            future2 = executor.submit(self.collect_files_by_size, drive2, "Drive 2")
            sizes1 = future1.result()
            sizes2 = future2.result()

        if self.stop_event.is_set():
            return []

        common_sizes = set(sizes1.keys()) & set(sizes2.keys())

        if not common_sizes:
            self.progress_callback(self.scanned_files, self.total_files, 0)
            self.ui_callback("No duplicates found.")
            return []

        self.ui_callback("Hashing candidate files only...")

        drive1_candidates = []
        drive2_candidates = []

        for size in common_sizes:
            drive1_candidates.extend(sizes1[size])
            drive2_candidates.extend(sizes2[size])

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(self.hash_candidates, drive1_candidates, "Drive 1")
            future2 = executor.submit(self.hash_candidates, drive2_candidates, "Drive 2")
            hashes1 = future1.result()
            hashes2 = future2.result()

        if self.stop_event.is_set():
            return []

        self.ui_callback("Comparing duplicate hashes...")

        common_hashes = set(hashes1.keys()) & set(hashes2.keys())
        duplicates = []

        for h in common_hashes:
            for p1 in hashes1[h]:
                for p2 in hashes2[h]:
                    duplicates.append((p1, p2))

        self.duplicates = duplicates
        self.progress_callback(self.scanned_files, self.total_files, len(self.duplicates))
        self.ui_callback(f"Done. Found {len(self.duplicates)} duplicate pair(s).")
        return duplicates


loading_window = None
scanner = None
duplicates_list = []


def show_loading(message="Please wait..."):
    global loading_window

    try:
        if loading_window is not None and loading_window.winfo_exists():
            for widget in loading_window.winfo_children():
                if isinstance(widget, tk.Label):
                    widget.config(text=message)
            loading_window.update_idletasks()
            return
    except tk.TclError:
        pass

    loading_window = tk.Toplevel(root)
    loading_window.title("Processing")
    center_window(loading_window, 340, 120)
    loading_window.transient(root)
    loading_window.grab_set()
    loading_window.resizable(False, False)
    loading_window.protocol("WM_DELETE_WINDOW", lambda: None)

    tk.Label(
        loading_window,
        text=message,
        font=("Arial", 11, "bold")
    ).pack(expand=True, pady=25)

    loading_window.update_idletasks()


def hide_loading():
    global loading_window
    try:
        if loading_window is not None and loading_window.winfo_exists():
            loading_window.grab_release()
            loading_window.destroy()
    except tk.TclError:
        pass
    loading_window = None


def confirm_delete_both(parent, continue_callback):
    warn = tk.Toplevel(parent)
    warn.title("Danger Warning")
    center_window(warn, 520, 230)
    warn.transient(parent)
    warn.grab_set()
    warn.resizable(False, False)

    tk.Label(
        warn,
        text="WARNING",
        font=("Arial Black", 18, "bold"),
        fg="red"
    ).pack(pady=(15, 5))

    tk.Label(
        warn,
        text="Choosing this option will result in deletion of all selected files\nfrom both drives/folders. Are you sure?",
        font=("Arial", 12, "bold"),
        fg="red",
        justify="center"
    ).pack(pady=10)

    btn_frame = tk.Frame(warn)
    btn_frame.pack(pady=10)

    def yes():
        warn.destroy()
        continue_callback()

    def no():
        warn.destroy()

    tk.Button(
        btn_frame,
        text="YES - Continue",
        width=16,
        bg="#e74c3c",
        fg="white",
        font=("Arial", 10, "bold"),
        command=yes
    ).grid(row=0, column=0, padx=10)

    tk.Button(
        btn_frame,
        text="NO - Cancel",
        width=16,
        command=no
    ).grid(row=0, column=1, padx=10)


def update_status(text, bg_color):
    status_label.config(text=text)
    status_frame.config(bg=bg_color)
    status_label.config(bg=bg_color)
    speed_label1.config(bg=bg_color)
    speed_label2.config(bg=bg_color)
    scanned_items_label.config(bg=bg_color)
    duplicates_count_label.config(bg=bg_color)


def append_log(message):
    root.after(0, lambda: (
        log.insert(tk.END, message + "\n"),
        log.see(tk.END)
    ))


def update_speed(drive_name, speed):
    label = speed_label1 if drive_name == "Drive 1" else speed_label2
    root.after(0, lambda: label.config(text=f"{drive_name}: {speed:.2f} MB/s"))


def update_progress(scanned, total, duplicates):
    percent = (scanned / total * 100) if total else 0

    def _update():
        progress.configure(value=percent)
        progress_label.config(text=f"{percent:.2f}%")
        scanned_items_label.config(
            text=f"Scanned Items: {scanned} / {total if total else 'Calculating...'}"
        )
        duplicates_count_label.config(text=f"Scanned Duplicates: {duplicates}")

    root.after(0, _update)


def start_scan():
    global scanner, duplicates_list

    d1 = entry1.get().strip()
    d2 = entry2.get().strip()

    if not d1 or not d2:
        messagebox.showwarning("Missing folders", "Please select both folders first.")
        return

    if not os.path.isdir(d1) or not os.path.isdir(d2):
        messagebox.showwarning("Invalid folder", "One or both selected paths are invalid.")
        return

    update_status("SCANNING", "#3498db")
    duplicates_list = []

    log.delete("1.0", tk.END)
    progress.stop()
    progress.configure(mode="determinate", value=0)
    progress_label.config(text="0.00%")
    scanned_items_label.config(text="Scanned Items: 0 / Calculating...")
    duplicates_count_label.config(text="Scanned Duplicates: 0")
    speed_label1.config(text="Drive 1: 0.00 MB/s")
    speed_label2.config(text="Drive 2: 0.00 MB/s")

    btn_start.config(state=tk.DISABLED)
    btn_stop.config(state=tk.NORMAL)

    scanner = DuplicateScanner(
        ui_callback=append_log,
        speed_callback=update_speed,
        progress_callback=update_progress
    )

    def worker():
        global duplicates_list
        duplicates = scanner.find_cross_drive_duplicates(d1, d2)

        def finish():
            btn_start.config(state=tk.NORMAL)
            btn_stop.config(state=tk.DISABLED)

            if scanner.stop_event.is_set():
                update_status("STOPPED", "#e74c3c")
                append_log("Scan stopped.")
                return

            duplicates_list = duplicates
            update_status("DONE", "#2ecc71")
            append_log(f"Scan Completed. Total Duplicates Found: {len(duplicates_list)}")

            if duplicates_list:
                show_duplicates()
            else:
                messagebox.showinfo("Done", "No duplicates found.")

        root.after(0, finish)

    threading.Thread(target=worker, daemon=True).start()


def stop_scan_func():
    global scanner
    if scanner is not None:
        scanner.stop()

    update_status("STOPPED", "#e74c3c")
    speed_label1.config(text="Drive 1: 0.00 MB/s")
    speed_label2.config(text="Drive 2: 0.00 MB/s")
    log.insert(tk.END, "\nScan stopping...\n")
    log.see(tk.END)


def delete_selected_duplicates(tree, dup_window):
    global duplicates_list

    selected_items = tree.selection()

    if not selected_items:
        messagebox.showwarning("No Selection", "Please select at least one duplicate row to delete.")
        return

    choice_window = tk.Toplevel(dup_window)
    choice_window.title("Delete Option")
    center_window(choice_window, 360, 200)
    choice_window.transient(dup_window)
    choice_window.grab_set()
    choice_window.resizable(False, False)

    tk.Label(
        choice_window,
        text="Which drive/folder should be used for deletion?",
        font=("Arial", 11, "bold")
    ).pack(pady=15)

    def perform_delete(mode):
        global duplicates_list

        mode_text = {
            "drive1": "Drive / Folder 1",
            "drive2": "Drive / Folder 2",
            "both": "Both Drives / Folders"
        }[mode]

        if mode != "both":
            confirm = messagebox.askyesno(
                "Confirm Delete",
                f"Delete selected duplicate file(s) from {mode_text}?",
                parent=choice_window
            )
            if not confirm:
                return

        show_loading(f"Deleting selected duplicates from {mode_text}...")
        choice_window.update_idletasks()

        deleted_count = 0
        failed_count = 0
        rows_to_remove = []

        for item in selected_items:
            values = tree.item(item, "values")
            if not values:
                continue

            p1 = values[3]
            p2 = values[4]

            if mode == "drive1":
                targets = [p1]
            elif mode == "drive2":
                targets = [p2]
            else:
                targets = [p1, p2]

            success_for_row = True

            for target in targets:
                try:
                    if os.path.exists(target):
                        os.remove(target)
                        deleted_count += 1
                        log.insert(tk.END, f"Deleted: {target}\n")
                    else:
                        failed_count += 1
                        success_for_row = False
                        log.insert(tk.END, f"File not found: {target}\n")
                except OSError as e:
                    failed_count += 1
                    success_for_row = False
                    log.insert(tk.END, f"Failed to delete {target}: {e}\n")

            if success_for_row:
                rows_to_remove.append((item, p1, p2))

        for item, p1, p2 in rows_to_remove:
            try:
                tree.delete(item)
            except tk.TclError:
                pass
            try:
                duplicates_list.remove((p1, p2))
            except ValueError:
                pass

        hide_loading()

        scanned_items_label.config(
            text=scanned_items_label.cget("text")
        )
        duplicates_count_label.config(text=f"Scanned Duplicates: {len(duplicates_list)}")

        log.insert(
            tk.END,
            f"\nDelete operation finished. Deleted: {deleted_count}, Failed: {failed_count}\n"
        )
        log.see(tk.END)

        choice_window.destroy()

        if not tree.get_children():
            messagebox.showinfo("Done", "No more duplicates!", parent=dup_window)

    btn_frame = tk.Frame(choice_window)
    btn_frame.pack(pady=10)

    tk.Button(
        btn_frame,
        text="Delete from Drive 1",
        width=18,
        bg="#f39c12",
        fg="white",
        command=lambda: perform_delete("drive1")
    ).grid(row=0, column=0, padx=5, pady=5)

    tk.Button(
        btn_frame,
        text="Delete from Drive 2",
        width=18,
        bg="#3498db",
        fg="white",
        command=lambda: perform_delete("drive2")
    ).grid(row=0, column=1, padx=5, pady=5)

    tk.Button(
        btn_frame,
        text="Delete from Both",
        width=18,
        bg="#e74c3c",
        fg="white",
        command=lambda: confirm_delete_both(choice_window, lambda: perform_delete("both"))
    ).grid(row=1, column=0, columnspan=2, pady=10)

    tk.Button(
        choice_window,
        text="Cancel",
        width=12,
        command=choice_window.destroy
    ).pack(pady=5)


def delete_all_duplicates(tree, dup_window):
    global duplicates_list

    all_items = tree.get_children()

    if not all_items:
        messagebox.showwarning("No Duplicates", "There are no duplicates to delete.")
        return

    choice_window = tk.Toplevel(dup_window)
    choice_window.title("Delete All Duplicates")
    center_window(choice_window, 380, 210)
    choice_window.transient(dup_window)
    choice_window.grab_set()
    choice_window.resizable(False, False)

    tk.Label(
        choice_window,
        text="Delete ALL duplicates from which location?",
        font=("Arial", 11, "bold")
    ).pack(pady=15)

    def perform_delete_all(mode):
        global duplicates_list

        mode_text = {
            "drive1": "Drive / Folder 1",
            "drive2": "Drive / Folder 2",
            "both": "Both Drives / Folders"
        }[mode]

        if mode != "both":
            confirm = messagebox.askyesno(
                "Confirm Delete All",
                f"Delete ALL duplicate file(s) from {mode_text}?\n\nThis will affect every row in the results table.",
                parent=choice_window
            )
            if not confirm:
                return

        show_loading(f"Deleting all duplicates from {mode_text}...")
        choice_window.update_idletasks()

        deleted_count = 0
        failed_count = 0
        rows_to_remove = []

        for item in all_items:
            values = tree.item(item, "values")
            if not values:
                continue

            p1 = values[3]
            p2 = values[4]

            if mode == "drive1":
                targets = [p1]
            elif mode == "drive2":
                targets = [p2]
            else:
                targets = [p1, p2]

            success_for_row = True

            for target in targets:
                try:
                    if os.path.exists(target):
                        os.remove(target)
                        deleted_count += 1
                        log.insert(tk.END, f"Deleted: {target}\n")
                    else:
                        failed_count += 1
                        success_for_row = False
                        log.insert(tk.END, f"File not found: {target}\n")
                except OSError as e:
                    failed_count += 1
                    success_for_row = False
                    log.insert(tk.END, f"Failed to delete {target}: {e}\n")

            if success_for_row:
                rows_to_remove.append((item, p1, p2))

        for item, p1, p2 in rows_to_remove:
            try:
                tree.delete(item)
            except tk.TclError:
                pass
            try:
                duplicates_list.remove((p1, p2))
            except ValueError:
                pass

        hide_loading()

        duplicates_count_label.config(text=f"Scanned Duplicates: {len(duplicates_list)}")

        log.insert(
            tk.END,
            f"\nDelete ALL operation finished. Deleted: {deleted_count}, Failed: {failed_count}\n"
        )
        log.see(tk.END)

        choice_window.destroy()

        if not tree.get_children():
            messagebox.showinfo(
                "Done",
                "All duplicate files have been removed.",
                parent=dup_window
            )

    btn_frame = tk.Frame(choice_window)
    btn_frame.pack(pady=10)

    tk.Button(
        btn_frame,
        text="Delete All from Drive/Folder 1",
        width=20,
        bg="#f39c12",
        fg="white",
        command=lambda: perform_delete_all("drive1")
    ).grid(row=0, column=0, padx=5, pady=5)

    tk.Button(
        btn_frame,
        text="Delete All from Drive/Folder 2",
        width=20,
        bg="#3498db",
        fg="white",
        command=lambda: perform_delete_all("drive2")
    ).grid(row=0, column=1, padx=5, pady=5)

    tk.Button(
        btn_frame,
        text="Delete All from Both",
        width=20,
        bg="#e74c3c",
        fg="white",
        command=lambda: confirm_delete_both(choice_window, lambda: perform_delete_all("both"))
    ).grid(row=1, column=0, columnspan=2, pady=10)

    tk.Button(
        choice_window,
        text="Cancel",
        width=12,
        command=choice_window.destroy
    ).pack(pady=5)


def show_duplicates():
    dup_window = tk.Toplevel(root)
    dup_window.title("Duplicate Files Found")
    center_window(dup_window, 1100, 650)

    tk.Label(
        dup_window,
        text=f"Duplicates found ({len(duplicates_list)} found)",
        font=("Arial", 14, "bold")
    ).pack(pady=10)

    frame = tk.Frame(dup_window)
    frame.pack(fill="both", expand=True, padx=20, pady=10)

    cols = ("File Name", "Drive 1", "Drive 2", "Path 1", "Path 2")
    tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")

    for col in cols:
        tree.heading(col, text=col)

    tree.column("File Name", width=200, anchor="w")
    tree.column("Drive 1", width=100, anchor="center")
    tree.column("Drive 2", width=100, anchor="center")
    tree.column("Path 1", width=350, anchor="w")
    tree.column("Path 2", width=350, anchor="w")

    tree.tag_configure("evenrow", background="#f0f8ff")
    tree.tag_configure("oddrow", background="white")

    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(0, weight=1)

    for i, (p1, p2) in enumerate(duplicates_list):
        fname = os.path.basename(p1)
        d1_label = os.path.splitdrive(p1)[0] or "Dir 1"
        d2_label = os.path.splitdrive(p2)[0] or "Dir 2"
        tag = "evenrow" if i % 2 == 0 else "oddrow"

        tree.insert("", tk.END, values=(fname, d1_label, d2_label, p1, p2), tags=(tag,))

    btn_frame = tk.Frame(dup_window)
    btn_frame.pack(pady=10)

    tk.Button(
        btn_frame,
        text="Delete Selected",
        width=18,
        bg="#c0392b",
        fg="white",
        font=("Arial", 10, "bold"),
        command=lambda: delete_selected_duplicates(tree, dup_window)
    ).pack(side=tk.LEFT, padx=10)

    tk.Button(
        btn_frame,
        text="Delete All Duplicates",
        width=20,
        bg="#8e44ad",
        fg="white",
        font=("Arial", 10, "bold"),
        command=lambda: delete_all_duplicates(tree, dup_window)
    ).pack(side=tk.LEFT, padx=10)

    tk.Button(
        btn_frame,
        text="Dismiss",
        width=18,
        command=dup_window.destroy
    ).pack(side=tk.LEFT, padx=10)


def browse1():
    folder = filedialog.askdirectory()
    if folder:
        entry1.delete(0, tk.END)
        entry1.insert(0, folder)


def browse2():
    folder = filedialog.askdirectory()
    if folder:
        entry2.delete(0, tk.END)
        entry2.insert(0, folder)


root = tk.Tk()
root.title("Duplicate File Checker (Optimized) By: SpeedGamer21")
center_window(root, 1100, 750)

main_frame = tk.Frame(root)
main_frame.pack(padx=20, pady=20, fill="x")
main_frame.columnconfigure(4, weight=1)

try:
    image_path = resource_path("Jared_niala.jpg")
    original = Image.open(image_path).convert("RGBA")
    resized_square = original.resize((150, 150), Image.LANCZOS)
    photo = ImageTk.PhotoImage(resized_square)

    img_label = tk.Label(main_frame, image=photo, borderwidth=2, relief="solid")
    img_label.grid(row=0, column=0, rowspan=2, padx=(0, 20), pady=10, sticky="nw")
    img_label.image = photo
except Exception:
    tk.Label(
        main_frame,
        text="[No Image]",
        width=20,
        height=10,
        relief="sunken"
    ).grid(row=0, column=0, rowspan=2, padx=(0, 20), pady=10, sticky="nw")

tk.Label(main_frame, text="Drive / Folder 1").grid(row=0, column=1, sticky="w", pady=5)
entry1 = tk.Entry(main_frame, width=45)
entry1.grid(row=0, column=2, padx=10, pady=5)
tk.Button(main_frame, text="Browse", width=10, command=browse1).grid(row=0, column=3, padx=5)

tk.Label(main_frame, text="Drive / Folder 2").grid(row=1, column=1, sticky="w", pady=5)
entry2 = tk.Entry(main_frame, width=45)
entry2.grid(row=1, column=2, padx=10, pady=5)
tk.Button(main_frame, text="Browse", width=10, command=browse2).grid(row=1, column=3, padx=5)

status_frame = tk.Frame(main_frame, bg="#ecf0f1", relief="ridge", borderwidth=3)
status_frame.grid(row=0, column=4, rowspan=2, sticky="nsew", padx=(20, 0), pady=5)

status_label = tk.Label(status_frame, text="IDLE", font=("Arial Black", 24), fg="black", bg="#ecf0f1")
status_label.pack(expand=True, pady=(10, 0))

speed_label1 = tk.Label(status_frame, text="Drive 1: 0.00 MB/s", font=("Courier New", 11, "bold"), fg="black", bg="#ecf0f1")
speed_label1.pack()

speed_label2 = tk.Label(status_frame, text="Drive 2: 0.00 MB/s", font=("Courier New", 11, "bold"), fg="black", bg="#ecf0f1")
speed_label2.pack()

scanned_items_label = tk.Label(
    status_frame,
    text="Scanned Items: 0 / 0",
    font=("Arial", 10, "bold"),
    fg="black",
    bg="#ecf0f1"
)
scanned_items_label.pack()

duplicates_count_label = tk.Label(
    status_frame,
    text="Scanned Duplicates: 0",
    font=("Arial", 10, "bold"),
    fg="black",
    bg="#ecf0f1"
)
duplicates_count_label.pack(pady=(0, 10))

btn_container = tk.Frame(root)
btn_container.pack(pady=15)

btn_start = tk.Button(
    btn_container,
    text="Start Scan",
    width=15,
    bg="#4CAF50",
    fg="white",
    font=("Arial", 10, "bold"),
    command=start_scan
)
btn_start.pack(side=tk.LEFT, padx=10)

btn_stop = tk.Button(
    btn_container,
    text="Stop Scan",
    width=15,
    bg="#f44336",
    fg="white",
    font=("Arial", 10, "bold"),
    command=stop_scan_func,
    state=tk.DISABLED
)
btn_stop.pack(side=tk.LEFT, padx=10)

progress_frame = tk.Frame(root)
progress_frame.pack(fill="x", padx=30, pady=10)

progress = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
progress.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 10))

progress_label = tk.Label(progress_frame, text="0.00%", font=("Arial", 10, "bold"))
progress_label.pack(side=tk.RIGHT)

log_label = tk.Label(root, text="Activity Log:", font=("Arial", 9, "italic"))
log_label.pack(anchor="w", padx=30)

log = tk.Text(root, height=18)
log.pack(padx=30, pady=(0, 20), fill="both", expand=True)

root.mainloop()