import os
import hashlib
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading

def get_hash(file_path):
    hasher = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def scan_folder(folder):
    hashes = {}
    for root, dirs, files in os.walk(folder):
        for file in files:
            path = os.path.join(root, file)
            h = get_hash(path)
            if h:
                hashes[h] = path
    return hashes

def find_duplicates():
    folder1 = entry1.get()
    folder2 = entry2.get()

    if not folder1 or not folder2:
        messagebox.showerror("Error", "Please select both folders")
        return

    result_box.delete(1.0, tk.END)
    result_box.insert(tk.END, "Scanning...\n")

    def process():
        hashes1 = scan_folder(folder1)
        hashes2 = scan_folder(folder2)

        duplicates = []

        for h in hashes1:
            if h in hashes2:
                duplicates.append((hashes1[h], hashes2[h]))

        result_box.delete(1.0, tk.END)

        if duplicates:
            for f1, f2 in duplicates:
                result_box.insert(tk.END, f"{f1}\n== DUPLICATE ==\n{f2}\n\n")
        else:
            result_box.insert(tk.END, "No duplicates found.")

    threading.Thread(target=process).start()

def browse1():
    folder = filedialog.askdirectory()
    entry1.delete(0, tk.END)
    entry1.insert(0, folder)

def browse2():
    folder = filedialog.askdirectory()
    entry2.delete(0, tk.END)
    entry2.insert(0, folder)

app = tk.Tk()
app.title("Duplicate File Checker")
app.geometry("700x500")

tk.Label(app, text="Folder / Drive 1").pack()
entry1 = tk.Entry(app, width=80)
entry1.pack()

tk.Button(app, text="Browse", command=browse1).pack()

tk.Label(app, text="Folder / Drive 2").pack()
entry2 = tk.Entry(app, width=80)
entry2.pack()

tk.Button(app, text="Browse", command=browse2).pack()

tk.Button(app, text="Scan for Duplicates", command=find_duplicates, bg="green", fg="white").pack(pady=10)

result_box = scrolledtext.ScrolledText(app)
result_box.pack(fill="both", expand=True)

app.mainloop()