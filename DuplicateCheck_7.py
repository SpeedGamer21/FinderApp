import os
import hashlib
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageTk

# --- Global Variables ---
stop_scan = False
total_files = 0
scanned_files = 0
duplicates_list = []

# --- Logic Functions ---
def get_file_hash(file_path, chunk_size=1024*1024): 
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
    for root, dirs, files in os.walk(path):
        count += len(files)
    return count

def update_status(text, bg_color):
    """Updates the status box background color and the text."""
    status_label.config(text=text)
    status_frame.config(bg=bg_color)
    status_label.config(bg=bg_color)
    speed_label1.config(bg=bg_color)
    speed_label2.config(bg=bg_color)

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
            root.after(0, lambda p=filepath: (log_widget.insert(tk.END, f"[{drive_name}] Checking: {p}\n"), log_widget.see(tk.END)))
            
            file_hash, bytes_processed = get_file_hash(filepath)
            total_bytes_processed += bytes_processed
            
            elapsed = time.time() - start_time
            if elapsed > 0.5: 
                mb_per_sec = (total_bytes_processed / (1024 * 1024)) / elapsed
                root.after(0, lambda s=mb_per_sec: speed_label.config(text=f"{drive_name}: {s:.2f} MB/s"))

            if file_hash:
                file_hashes[file_hash] = filepath
            
            scanned_files += 1
            progress_value = (scanned_files / total_files * 100) if total_files > 0 else 0
            root.after(0, lambda v=progress_value: (
                progress.configure(value=v),
                progress_label.config(text=f"{v:.2f}%")
            ))
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
    duplicates_list = []
    log.delete(1.0, tk.END)
    progress['value'] = 0
    progress_label.config(text="0.00%")
    
    total_files = count_files(d1) + count_files(d2)
    btn_start.config(state=tk.DISABLED)
    btn_stop.config(state=tk.NORMAL)
    
    thread = threading.Thread(target=run_scan, args=(d1, d2), daemon=True)
    thread.start()

def stop_scan_func():
    global stop_scan
    stop_scan = True
    update_status("STOPPED", "#e74c3c")
    speed_label1.config(text="Drive 1: 0.00 MB/s")
    speed_label2.config(text="Drive 2: 0.00 MB/s")
    log.insert(tk.END, "\nScan stopping...\n")

def run_scan(drive1, drive2):
    global stop_scan, duplicates_list
    hashes1, hashes2 = {}, {}
    log.insert(tk.END, "Starting parallel scan...\n")
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(scan_drive, drive1, hashes1, log, "Drive 1", speed_label1)
        future2 = executor.submit(scan_drive, drive2, hashes2, log, "Drive 2", speed_label2)
        future1.result()
        future2.result()
    
    if stop_scan:
        root.after(0, lambda: (btn_start.config(state=tk.NORMAL), btn_stop.config(state=tk.DISABLED)))
        return
    
    log.insert(tk.END, "\nComparing files for duplicates...\n")
    for h in hashes1:
        if h in hashes2:
            duplicates_list.append((hashes1[h], hashes2[h]))
    
    root.after(0, lambda: (btn_start.config(state=tk.NORMAL), btn_stop.config(state=tk.DISABLED)))
    update_status("DONE", "#2ecc71")
    log.insert(tk.END, "\nScan Completed\n")
    if duplicates_list:
        root.after(0, show_duplicates)

def show_duplicates():
    dup_window = tk.Toplevel(root)
    dup_window.title("Duplicate Files Found")
    dup_window.geometry("1100x600")

    tk.Label(dup_window, text="Duplicate Results Table", font=("Arial", 14, "bold")).pack(pady=10)

    # Frame for Treeview and Scrollbars
    frame = tk.Frame(dup_window)
    frame.pack(fill="both", expand=True, padx=20, pady=10)

    # Define Columns
    cols = ("File Name", "Drive 1", "Drive 2", "Path 1", "Path 2")
    tree = ttk.Treeview(frame, columns=cols, show="headings")

    # Set Headings
    for col in cols:
        tree.heading(col, text=col)

    # Set Column Widths
    tree.column("File Name", width=200, anchor="w")
    tree.column("Drive 1", width=70, anchor="center")
    tree.column("Drive 2", width=70, anchor="center")
    tree.column("Path 1", width=350, anchor="w")
    tree.column("Path 2", width=350, anchor="w")

    # Striped Rows Styling
    tree.tag_configure('evenrow', background="#f0f8ff") # Light Blue
    tree.tag_configure('oddrow', background="white")

    # Scrollbars
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    # Layout using grid
    tree.grid(row=0, column=0, sticky='nsew')
    vsb.grid(row=0, column=1, sticky='ns')
    hsb.grid(row=1, column=0, sticky='ew')

    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(0, weight=1)

    # Insert Data with Drive Identification
    for i, (p1, p2) in enumerate(duplicates_list):
        fname = os.path.basename(p1)
        d1_label = os.path.splitdrive(p1)[0] or "Dir 1"
        d2_label = os.path.splitdrive(p2)[0] or "Dir 2"
        
        tag = 'evenrow' if i % 2 == 0 else 'oddrow'
        tree.insert("", tk.END, values=(fname, d1_label, d2_label, p1, p2), tags=(tag,))

    tk.Button(dup_window, text="Dismiss", width=20, command=dup_window.destroy).pack(pady=10)

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
root.geometry("1100x750")

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

# --- STATUS BOX (Full Box Color) ---
status_frame = tk.Frame(main_frame, bg="#ecf0f1", relief="ridge", borderwidth=3)
status_frame.grid(row=0, column=4, rowspan=2, sticky="nsew", padx=(20, 0), pady=5)

status_label = tk.Label(status_frame, text="IDLE", font=("Arial Black", 24), fg="black", bg="#ecf0f1")
status_label.pack(expand=True, pady=(10, 0))

speed_label1 = tk.Label(status_frame, text="Drive 1: 0.00 MB/s", font=("Courier New", 11, "bold"), fg="black", bg="#ecf0f1")
speed_label1.pack()
speed_label2 = tk.Label(status_frame, text="Drive 2: 0.00 MB/s", font=("Courier New", 11, "bold"), fg="black", bg="#ecf0f1")
speed_label2.pack(pady=(0, 10))

# --- Control Buttons ---
btn_container = tk.Frame(root)
btn_container.pack(pady=15)

btn_start = tk.Button(btn_container, text="Start Scan", width=15, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=start_scan)
btn_start.pack(side=tk.LEFT, padx=10)

btn_stop = tk.Button(btn_container, text="Stop Scan", width=15, bg="#f44336", fg="white", font=("Arial", 10, "bold"), command=stop_scan_func, state=tk.DISABLED)
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