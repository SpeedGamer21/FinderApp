import os
import hashlib
from concurrent.futures import ThreadPoolExecutor

def get_file_hash(file_path, chunk_size=8192):
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def scan_drive(drive_path):
    file_hashes = {}
    for root, dirs, files in os.walk(drive_path):
        for file in files:
            path = os.path.join(root, file)
            file_hash = get_file_hash(path)
            if file_hash:
                file_hashes[file_hash] = path
    return file_hashes

def find_duplicates(drive1, drive2):

    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(scan_drive, drive1)
        future2 = executor.submit(scan_drive, drive2)

        hashes1 = future1.result()
        hashes2 = future2.result()

    duplicates = []

    for h in hashes1:
        if h in hashes2:
            duplicates.append((hashes1[h], hashes2[h]))

    return duplicates


if __name__ == "__main__":
    drive1 = "D:\\"
    drive2 = "E:\\"

    duplicates = find_duplicates(drive1, drive2)

    print("\nDuplicate Files Found:\n")

    for file1, file2 in duplicates:
        print(f"{file1} <==> {file2}")