import os
import hashlib
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageTk

def center_window(win, width, height):
    win.update_idletasks()
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = int((screen_width / 2) - (width / 2))
    y = int((screen_height / 2) - (height / 2))
    win.geometry(f"{width}x{height}+{x}+{y}")


loading_window = None

def show_loading(message="Please wait..."):
    global loading_window

    try:
        if loading_window is not None and loading_window.winfo_exists():
            for widget in loading_window.winfo_children():
                if isinstance(widget, tk.Label):
                    widget.config(text=message)
            loading_window.update_idletasks()
            return
    except:
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
    except:
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
        text="Choosing this option will result to deletion of all the files\nfrom both drives! are your sure?",
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


# --- Global Variables ---
stop_scan = False
total_files = 0
scanned_files = 0
duplicates_list = []

# --- Logic Functions ---
def get_file_hash(file_path, chunk_size=1024 * 1024):
    hasher = hashlib.md5()
    bytes_read = 0
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                if stop_scan:
                    return None, 0
                hasher.update(chunk)
                bytes_read += len(chunk)
        return hasher.hexdigest(), bytes_read
    except:
        return None, 0


def count_files(path):
    count = 0
    for root_dir, dirs, files in os.walk(path):
        if stop_scan:
            return count
        count += len(files)
    return count


def update_status(text, bg_color):
    status_label.config(text=text)
    status_frame.config(bg=bg_color)
    status_label.config(bg=bg_color)
    speed_label1.config(bg=bg_color)
    speed_label2.config(bg=bg_color)
    scanned_items_label.config(bg=bg_color)
    duplicates_count_label.config(bg=bg_color)


def update_counters():
    total_text = total_files if total_files > 0 else "Calculating..."
    scanned_items_label.config(text=f"Scanned Items: {scanned_files} / {total_text}")
    duplicates_count_label.config(text=f"Scanned Duplicates: {len(duplicates_list)}")


def scan_drive(path, file_hashes, log_widget, drive_name, speed_label):
    global stop_scan, scanned_files

    start_time = time.time()
    total_bytes_processed = 0

    for root_dir, dirs, files in os.walk(path):
        if stop_scan:
            break

        for file in files:
            if stop_scan:
                break

            filepath = os.path.join(root_dir, file)

            root.after(
                0,
                lambda p=filepath: (
                    log_widget.insert(tk.END, f"[{drive_name}] Checking: {p}\n"),
                    log_widget.see(tk.END)
                )
            )

            file_hash, bytes_processed = get_file_hash(filepath)
            total_bytes_processed += bytes_processed

            elapsed = time.time() - start_time
            if elapsed > 0.5:
                mb_per_sec = (total_bytes_processed / (1024 * 1024)) / elapsed
                root.after(
                    0,
                    lambda s=mb_per_sec: speed_label.config(text=f"{drive_name}: {s:.2f} MB/s")
                )

            if file_hash:
                file_hashes[file_hash] = filepath

            scanned_files += 1
            progress_value = (scanned_files / total_files * 100) if total_files > 0 else 0

            root.after(
                0,
                lambda v=progress_value: (
                    progress.configure(value=v),
                    progress_label.config(text=f"{v:.2f}%"),
                    update_counters()
                )
            )

    root.after(0, lambda: speed_label.config(text=f"{drive_name}: 0.00 MB/s"))


def start_scan():
    global stop_scan, total_files, scanned_files, duplicates_list

    d1, d2 = entry1.get(), entry2.get()
    if not d1 or not d2:
        log.insert(tk.END, "Error: Please select both folders first.\n")
        return

    update_status("SCANNING", "#3498db")
    stop_scan = False
    scanned_files = 0
    total_files = 0
    duplicates_list = []

    log.delete(1.0, tk.END)
    progress["value"] = 0
    progress_label.config(text="Preparing scan...")
    scanned_items_label.config(text="Scanned Items: 0 / Calculating...")
    duplicates_count_label.config(text="Scanned Duplicates: 0")

    btn_start.config(state=tk.DISABLED)
    btn_stop.config(state=tk.NORMAL)

    progress.configure(mode="indeterminate")
    progress.start(10)

    log.insert(tk.END, "Preparing scan...\n")
    log.see(tk.END)

    thread = threading.Thread(target=run_scan, args=(d1, d2), daemon=True)
    thread.start()


def stop_scan_func():
    global stop_scan
    stop_scan = True

    try:
        progress.stop()
        progress.configure(mode="determinate")
    except:
        pass

    hide_loading()
    update_status("STOPPED", "#e74c3c")
    speed_label1.config(text="Drive 1: 0.00 MB/s")
    speed_label2.config(text="Drive 2: 0.00 MB/s")
    log.insert(tk.END, "\nScan stopping...\n")
    log.see(tk.END)


def run_scan(drive1, drive2):
    global stop_scan, duplicates_list, total_files

    root.after(0, lambda: log.insert(tk.END, "Counting files in selected drives...\n"))

    total_1 = count_files(drive1)
    if stop_scan:
        root.after(0, lambda: (
            progress.stop(),
            progress.configure(mode="determinate"),
            progress.configure(value=0),
            progress_label.config(text="Stopped"),
            scanned_items_label.config(text="Scanned Items: 0 / 0"),
            btn_start.config(state=tk.NORMAL),
            btn_stop.config(state=tk.DISABLED),
            update_status("STOPPED", "#e74c3c")
        ))
        return

    total_2 = count_files(drive2)
    if stop_scan:
        root.after(0, lambda: (
            progress.stop(),
            progress.configure(mode="determinate"),
            progress.configure(value=0),
            progress_label.config(text="Stopped"),
            btn_start.config(state=tk.NORMAL),
            btn_stop.config(state=tk.DISABLED),
            update_status("STOPPED", "#e74c3c")
        ))
        return

    total_files = total_1 + total_2

    root.after(0, lambda: (
        progress.stop(),
        progress.configure(mode="determinate"),
        progress.configure(value=0),
        progress_label.config(text="0.00%"),
        update_counters(),
        log.insert(tk.END, f"Total files found: {total_files}\n"),
        log.insert(tk.END, "Starting parallel scan...\n")
    ))

    hashes1, hashes2 = {}, {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(scan_drive, drive1, hashes1, log, "Drive 1", speed_label1)
        future2 = executor.submit(scan_drive, drive2, hashes2, log, "Drive 2", speed_label2)
        future1.result()
        future2.result()

    if stop_scan:
        root.after(0, lambda: (
            btn_start.config(state=tk.NORMAL),
            btn_stop.config(state=tk.DISABLED),
            update_counters()
        ))
        return

    root.after(0, lambda: (
        show_loading("Comparing duplicates, please wait..."),
        log.insert(tk.END, "\nComparing files for duplicates...\n")
    ))

    for h in hashes1:
        if h in hashes2:
            duplicates_list.append((hashes1[h], hashes2[h]))
            root.after(0, update_counters)

    root.after(0, lambda: (
        hide_loading(),
        btn_start.config(state=tk.NORMAL),
        btn_stop.config(state=tk.DISABLED),
        update_counters(),
        update_status("DONE", "#2ecc71"),
        log.insert(tk.END, f"\nScan Completed\nTotal Duplicates Found: {len(duplicates_list)}\n")
    ))

    if duplicates_list:
        root.after(0, show_duplicates)


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
        text="Which drive should be used for deletion?",
        font=("Arial", 11, "bold")
    ).pack(pady=15)

    def perform_delete(mode):
        global duplicates_list

        mode_text = {
            "drive1": "Drive 1",
            "drive2": "Drive 2",
            "both": "Both Drives"
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
                except Exception as e:
                    failed_count += 1
                    success_for_row = False
                    log.insert(tk.END, f"Failed to delete {target}: {e}\n")

            if success_for_row or mode in ("drive1", "drive2", "both"):
                rows_to_remove.append((item, p1, p2))

        for item, p1, p2 in rows_to_remove:
            try:
                tree.delete(item)
            except:
                pass
            try:
                duplicates_list.remove((p1, p2))
            except ValueError:
                pass

        update_counters()
        hide_loading()

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
        messagebox.showwarning("No Duplicates", "There are no duplicate to delete.")
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
            "drive1": "Drive 1",
            "drive2": "Drive 2",
            "both": "Both Drives"
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

            for target in targets:
                try:
                    if os.path.exists(target):
                        os.remove(target)
                        deleted_count += 1
                        log.insert(tk.END, f"Deleted: {target}\n")
                    else:
                        failed_count += 1
                        log.insert(tk.END, f"File not found: {target}\n")
                except Exception as e:
                    failed_count += 1
                    log.insert(tk.END, f"Failed to delete {target}: {e}\n")

            rows_to_remove.append((item, p1, p2))

        for item, p1, p2 in rows_to_remove:
            try:
                tree.delete(item)
            except:
                pass
            try:
                duplicates_list.remove((p1, p2))
            except ValueError:
                pass

        update_counters()
        hide_loading()

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
    tree.column("Drive 1", width=70, anchor="center")
    tree.column("Drive 2", width=70, anchor="center")
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


# --- GUI Setup ---
root = tk.Tk()
root.title("Duplicate File Checker (Parallel) By: SpeedGamer21")
center_window(root, 1100, 750)

main_frame = tk.Frame(root)
main_frame.pack(padx=20, pady=20, fill="x")
main_frame.columnconfigure(4, weight=1)

# --- Square Image (Column 0) ---
try:
    image_path = r"D:/FinderApp/Jared_niala.jpg"
    original = Image.open(image_path).convert("RGBA")
    size = (150, 150)
    resized_square = original.resize(size, Image.LANCZOS)
    photo = ImageTk.PhotoImage(resized_square)

    img_label = tk.Label(main_frame, image=photo, borderwidth=2, relief="solid")
    img_label.grid(row=0, column=0, rowspan=2, padx=(0, 20), pady=10, sticky="nw")
    img_label.image = photo
except:
    tk.Label(main_frame, text="[No Image]", width=20, height=10, relief="sunken").grid(row=0, column=0, rowspan=2)

# --- Folder Selection ---
tk.Label(main_frame, text="Drive / Folder 1").grid(row=0, column=1, sticky="w", pady=5)
entry1 = tk.Entry(main_frame, width=45)
entry1.grid(row=0, column=2, padx=10, pady=5)
tk.Button(main_frame, text="Browse", width=10, command=browse1).grid(row=0, column=3, padx=5)

tk.Label(main_frame, text="Drive / Folder 2").grid(row=1, column=1, sticky="w", pady=5)
entry2 = tk.Entry(main_frame, width=45)
entry2.grid(row=1, column=2, padx=10, pady=5)
tk.Button(main_frame, text="Browse", width=10, command=browse2).grid(row=1, column=3, padx=5)

# --- STATUS BOX ---
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

# --- Control Buttons ---
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

# --- Progress Section ---
progress_frame = tk.Frame(root)
progress_frame.pack(fill="x", padx=30, pady=10)

progress = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
progress.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 10))

progress_label = tk.Label(progress_frame, text="0.00%", font=("Arial", 10, "bold"))
progress_label.pack(side=tk.RIGHT)

# --- Log Section ---
log_label = tk.Label(root, text="Activity Log:", font=("Arial", 9, "italic"))
log_label.pack(anchor="w", padx=30)

log = tk.Text(root, height=18)
log.pack(padx=30, pady=(0, 20), fill="both", expand=True)

root.mainloop()