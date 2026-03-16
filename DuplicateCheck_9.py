import os
import time
import hashlib
import threading
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor


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
        """
        First pass: collect files grouped by size.
        This avoids hashing files that can never match.
        """
        grouped = defaultdict(list)
        total_bytes = 0
        start = time.perf_counter()
        last_ui_update = start

        for root, _, files in os.walk(folder):
            if self.stop_event.is_set():
                break

            for name in files:
                if self.stop_event.is_set():
                    break

                path = os.path.join(root, name)

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
        """
        Hash only files that survived size filtering.
        """
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

        # Only sizes present in both drives can be duplicates
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