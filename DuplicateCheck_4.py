import os
import hashlib
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from concurrent.futures import ThreadPoolExecutor

stop_scan = False
total_files = 0
scanned_files = 0

def get_file_hash(file_path, chunk_size=8192):
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                if stop_scan:
                    return None
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def count_files(path):
    count = 0
    for root, dirs, files in os.walk(path):
        count += len(files)
    return count

def scan_drive(path, file_hashes, log, drive_name):
    global stop_scan, scanned_files
    for root, dirs, files in os.walk(path):
        if stop_scan:
            break
        for file in files:
            if stop_scan:
                break
            filepath = os.path.join(root, file)
            log.insert(tk.END, f"[{drive_name}] Checking: {filepath}\n")
            log.see(tk.END)
            file_hash = get_file_hash(filepath)
            if file_hash:
                file_hashes[file_hash] = filepath
            scanned_files += 1
            progress['value'] = scanned_files / total_files * 100

def start_scan():
    global stop_scan, total_files, scanned_files
    stop_scan = False
    scanned_files = 0
    log.delete(1.0, tk.END)
    
    drive1 = entry1.get()
    drive2 = entry2.get()
    
    # Count total files
    total_files = count_files(drive1) + count_files(drive2)
    
    # Disable Start button and enable Stop button
    btn_start.config(state=tk.DISABLED)
    btn_stop.config(state=tk.NORMAL)
    
    thread = threading.Thread(target=run_scan, args=(drive1, drive2))
    thread.start()

def stop_scan_func():
    global stop_scan
    stop_scan = True
    log.insert(tk.END, "\nScan stopped by user\n")

def run_scan(drive1, drive2):
    global stop_scan
    hashes1 = {}
    hashes2 = {}
    
    log.insert(tk.END, "Starting parallel scan...\n")
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(scan_drive, drive1, hashes1, log, "Drive 1")
        future2 = executor.submit(scan_drive, drive2, hashes2, log, "Drive 2")
        future1.result()
        future2.result()
    
    if stop_scan:
        btn_start.config(state=tk.NORMAL)
        btn_stop.config(state=tk.DISABLED)
        return
    
    log.insert(tk.END, "\nComparing files for duplicates...\n")
    
    duplicates_found = False
    for h in hashes1:
        if h in hashes2:
            duplicates_found = True
            log.insert(tk.END, f"DUPLICATE:\n{hashes1[h]}  <==>  {hashes2[h]}\n\n")
            log.see(tk.END)
    
    if not duplicates_found:
        log.insert(tk.END, "No duplicates found!\n")
    
    log.insert(tk.END, "\nScan Completed\n")
    
    # Re-enable Start button and disable Stop button
    btn_start.config(state=tk.NORMAL)
    btn_stop.config(state=tk.DISABLED)

def browse1():
    folder = filedialog.askdirectory()
    entry1.delete(0, tk.END)
    entry1.insert(0, folder)

def browse2():
    folder = filedialog.askdirectory()
    entry2.delete(0, tk.END)
    entry2.insert(0, folder)

# Tkinter GUI setup
root = tk.Tk()
root.title("Duplicate File Checker (Parallel)")

frame = tk.Frame(root)
frame.pack(padx=10, pady=10)

tk.Label(frame, text="Drive / Folder 1").grid(row=0, column=0)
entry1 = tk.Entry(frame, width=50)
entry1.grid(row=0, column=1)
tk.Button(frame, text="Browse", command=browse1).grid(row=0, column=2)

tk.Label(frame, text="Drive / Folder 2").grid(row=1, column=0)
entry2 = tk.Entry(frame, width=50)
entry2.grid(row=1, column=1)
tk.Button(frame, text="Browse", command=browse2).grid(row=1, column=2)

btn_start = tk.Button(frame, text="Start Scan", command=start_scan)
btn_start.grid(row=2, column=0)
btn_stop = tk.Button(frame, text="Stop Scan", command=stop_scan_func, state=tk.DISABLED)
btn_stop.grid(row=2, column=1)

progress = ttk.Progressbar(root, orient="horizontal", length=500, mode="determinate")
progress.pack(pady=5)

log = tk.Text(root, height=25, width=100)
log.pack()

root.mainloop()