import os
import hashlib
import threading
import tkinter as tk
from tkinter import filedialog, ttk

stop_scan = False

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


def scan_drive(path, file_hashes, log):
    for root, dirs, files in os.walk(path):
        if stop_scan:
            break

        for file in files:
            if stop_scan:
                break

            filepath = os.path.join(root, file)

            log.insert(tk.END, f"Checking: {filepath}\n")
            log.see(tk.END)

            file_hash = get_file_hash(filepath)

            if file_hash:
                file_hashes[file_hash] = filepath
            break

        for file in files:
            if stop_scan:
                break

            filepath = os.path.join(root, file)

            log.insert(tk.END, f"Checking: {filepath}\n")
            log.see(tk.END)

            file_hash = get_file_hash(filepath)

            if file_hash:
                file_hashes[file_hash] = filepath


def start_scan():
    global stop_scan
    stop_scan = False

    log.delete(1.0, tk.END)

    drive1 = entry1.get()
    drive2 = entry2.get()

    thread = threading.Thread(target=run_scan, args=(drive1, drive2))
    thread.start()


def stop_scan_func():
    global stop_scan
    stop_scan = True
    log.insert(tk.END, "\nScan stopped by user\n")


def run_scan(drive1, drive2):

    hashes1 = {}
    hashes2 = {}

    log.insert(tk.END, "Scanning Drive 1...\n")
    scan_drive(drive1, hashes1, log)

    if stop_scan:
        return

    log.insert(tk.END, "\nScanning Drive 2...\n")
    scan_drive(drive2, hashes2, log)

    if stop_scan:
        return

    log.insert(tk.END, "\nComparing files...\n")

    for h in hashes1:
        if h in hashes2:
            log.insert(tk.END, f"DUPLICATE:\n{hashes1[h]}\n{hashes2[h]}\n\n")

    log.insert(tk.END, "\nScan Completed\n")


def browse1():
    folder = filedialog.askdirectory()
    entry1.delete(0, tk.END)
    entry1.insert(0, folder)


def browse2():
    folder = filedialog.askdirectory()
    entry2.delete(0, tk.END)
    entry2.insert(0, folder)


root = tk.Tk()
root.title("Duplicate File Checker")

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

tk.Button(frame, text="Start Scan", command=start_scan).grid(row=2, column=0)
tk.Button(frame, text="Stop Scan", command=stop_scan_func).grid(row=2, column=1)

progress = ttk.Progressbar(root, orient="horizontal", length=400)
progress.pack(pady=5)

log = tk.Text(root, height=20, width=80)
log.pack()

root.mainloop()