import json
import os
import threading
import hashlib
from file_object import FileObject, RWLock

SEGMENT_SIZE = 512
SEPERATOR = b'<<<DATA>>> '
HEADER_SIZE = 65536
DATA_START = HEADER_SIZE + len(SEPERATOR)

class FileSystem:
    def __init__(self):
        self.filesystem_path = 'sample.dat'
        self.header = None
        self.data_start = 0

        # Per-directory locks
        self.dir_locks = {}
        self.dir_locks_lock = threading.Lock()

        # Shared file open registry
        self.open_files = {}
        self.open_files_lock = threading.Lock()

        # Mmap quiesce mechanism
        self.ops_lock = threading.Lock()
        self.ops_condition = threading.Condition(self.ops_lock)
        self.active_ops = 0
        self.quiescing = False

        self._load_or_init()

    # ------------------------------------------------------------------
    # Quiesce helpers
    # ------------------------------------------------------------------
    def _begin_op(self):
        with self.ops_condition:
            while self.quiescing:
                self.ops_condition.wait()
            self.active_ops += 1

    def _end_op(self):
        with self.ops_condition:
            self.active_ops -= 1
            if self.active_ops == 0:
                self.ops_condition.notify_all()

    # ------------------------------------------------------------------
    # Directory lock helpers
    # ------------------------------------------------------------------
    def _get_dir_lock(self, path):
        norm = self._normalize_path(path)
        with self.dir_locks_lock:
            if norm not in self.dir_locks:
                self.dir_locks[norm] = threading.Lock()
            return self.dir_locks[norm]

    # ------------------------------------------------------------------
    # File open registry helpers
    # ------------------------------------------------------------------
    def _get_file_lock(self, filename):
        with self.open_files_lock:
            if filename not in self.open_files:
                self.open_files[filename] = RWLock()
            return self.open_files[filename]

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------
    def _load_or_init(self):
        if not os.path.exists(self.filesystem_path):
            self._init_filesystem()
        self._load_filesystem()

    def _init_filesystem(self):
        header = {
            "directories": [{"id": 0, "name": "/", "parent": None, "type": "dir"}],
            "files": {},
            "dead_space": []
        }
        self._write_header_and_data(header, b'')

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------
    def _should_compact(self):
        if not self.header['dead_space']:
            return False
        total_dead = sum(block['size'] for block in self.header['dead_space'])
        num_blocks = len(self.header['dead_space'])
        avg_size = total_dead / num_blocks if num_blocks > 0 else 0
        return avg_size < 180

    def _compact_data_region(self):
        print("[FS] Compacting data region...")
        with open(self.filesystem_path, 'rb') as f:
            f.seek(DATA_START)
            data_bytes = f.read()

        live_segments = []
        for fname, meta in self.header['files'].items():
            for seg in meta['segments']:
                live_segments.append({
                    'fname': fname,
                    'offset': seg['offset'],
                    'length': seg['length'],
                    'data': data_bytes[seg['offset']:seg['offset'] + seg['length']]
                })

        new_data = bytearray()
        new_offset = 0
        for seg in live_segments:
            seg['new_offset'] = new_offset
            new_data.extend(seg['data'])
            new_offset += seg['length']

        with open(self.filesystem_path, 'r+b') as f:
            f.seek(DATA_START)
            f.write(new_data)
            f.truncate(DATA_START + len(new_data))

        for seg in live_segments:
            fname = seg['fname']
            old_offset = seg['offset']
            for file_seg in self.header['files'][fname]['segments']:
                if file_seg['offset'] == old_offset:
                    file_seg['offset'] = seg['new_offset']
                    break

        self.header['dead_space'] = []
        self._write_header_only()
        print(f"[FS] Compacted {len(live_segments)} segments, freed {len(data_bytes) - len(new_data)} bytes")

    # ------------------------------------------------------------------
    # Load / write
    # ------------------------------------------------------------------
    def _load_filesystem(self):
        with open(self.filesystem_path, 'rb') as f:
            header_bytes = f.read(HEADER_SIZE)
        header_json = header_bytes.rstrip(b'\x00').decode()
        try:
            self.header = json.loads(header_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON header: {e}")
        self.data_start = DATA_START
        if self._should_compact():
            self._compact_data_region()

    def _write_header_and_data(self, header_dict, data):
        header_json = json.dumps(header_dict).encode()
        padding_needed = HEADER_SIZE - len(header_json)
        if padding_needed > 0:
            header_json += b'\x00' * padding_needed
        with open(self.filesystem_path, 'wb') as f:
            f.write(header_json)
            f.write(SEPERATOR)
            f.write(data)
        self.header = header_dict

    def _write_header_only(self):
        header_json = json.dumps(self.header).encode()
        padding_needed = HEADER_SIZE - len(header_json)
        if padding_needed > 0:
            header_json += b'\x00' * padding_needed
        with open(self.filesystem_path, 'r+b') as f:
            f.seek(0)
            f.write(header_json)
            f.write(SEPERATOR)

    def _write_segment_at_offset(self, relative_offset, data):
        absolute_offset = DATA_START + relative_offset
        with open(self.filesystem_path, 'r+b') as f:
            f.seek(absolute_offset)
            f.write(data)

    # ------------------------------------------------------------------
    # Dead space
    # ------------------------------------------------------------------
    def _add_dead_space(self, offset, size):
        if size <= 0:
            return
        self.header['dead_space'].append({"offset": offset, "size": size})
        self._write_header_only()

    def _allocate_space(self, needed):
        for i, block in enumerate(self.header['dead_space']):
            if block['size'] >= needed:
                return block['offset'], i
        return None, None

    def _consume_dead_block(self, idx, used_length):
        block = self.header['dead_space'][idx]
        if block['size'] == used_length:
            self.header['dead_space'].pop(idx)
        else:
            block['offset'] += used_length
            block['size'] -= used_length

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------
    def open_file(self, filename, mode='read'):
        self._begin_op()
        try:
            if filename not in self.header['files']:
                print(f"[FS] Error: File '{filename}' not found.")
                return None

            file_lock = self._get_file_lock(filename)
            if mode == 'read':
                file_lock.acquire_read()
            else:
                file_lock.acquire_write()

            meta = self.header['files'][filename]
            with open(self.filesystem_path, 'rb') as f:
                f.seek(self.data_start)
                data_bytes = f.read()
            content_bytes = bytearray()
            for seg in meta['segments']:
                start = seg['offset']
                end = start + seg['length']
                content_bytes.extend(data_bytes[start:end])
            content_str = self._deserialize(content_bytes)
            return FileObject(filename, content_str, existing_segments=meta['segments'])
        except Exception as e:
            print(f"[FS] Error opening '{filename}': {e}")
            return None
        finally:
            self._end_op()

    def close_file(self, filename, mode='read'):
        file_lock = self._get_file_lock(filename)
        if mode == 'read':
            file_lock.release_read()
        else:
            file_lock.release_write()

    def write_file(self, file_obj):
        self._begin_op()
        try:
            self._write_file_internal(file_obj)
        finally:
            self._end_op()

    def _write_file_internal(self, file_obj):
        name = file_obj.name
        content_bytes = self._serialize(file_obj.content)

        if name in self.header['files']:
            old_meta = self.header['files'][name]
            for seg in old_meta['segments']:
                self._add_dead_space(seg['offset'], seg['length'])

        segments_data = self._divide_into_segments(content_bytes)
        file_size = os.path.getsize(self.filesystem_path) if os.path.exists(self.filesystem_path) else 0
        data_region_size = file_size - DATA_START if file_size >= DATA_START else 0
        next_append_pos = data_region_size
        new_segments = []

        for seg_bytes in segments_data:
            seg_len = len(seg_bytes)
            alloc_offset, block_idx = self._allocate_space(seg_len)
            if alloc_offset is not None:
                self._write_segment_at_offset(alloc_offset, seg_bytes)
                new_segments.append({'offset': alloc_offset, 'length': seg_len})
                self._consume_dead_block(block_idx, seg_len)
            else:
                self._write_segment_at_offset(next_append_pos, seg_bytes)
                new_segments.append({'offset': next_append_pos, 'length': seg_len})
                next_append_pos += seg_len

        self.header['files'][name] = {
            'size': len(content_bytes),
            'segments': new_segments
        }
        self._write_header_only()
        print(f"[FS] Written '{name}' ({len(content_bytes)} bytes) in {len(new_segments)} segment(s).")

    def create_file(self, filename, parent_path):
        self._begin_op()
        try:
            with self._get_dir_lock(parent_path):
                self._add_item_in_directory(filename, parent_path, 'file')
                self.header['files'][filename] = {'size': 0, 'segments': []}
                self._write_header_only()
        finally:
            self._end_op()

    def delete_file(self, fname, parent_path):
        self._begin_op()
        try:
            with self._get_dir_lock(parent_path):
                if fname not in self.header['files']:
                    print(f"[FS] Error: File '{fname}' not found.")
                    return False
                for seg in self.header['files'][fname]['segments']:
                    self._add_dead_space(seg['offset'], seg['length'])
                del self.header['files'][fname]
                self._remove_item_from_directory(fname, parent_path)
                self._write_header_only()
                print(f"[FS] Deleted '{fname}', segments returned to dead_space.")
                return True
        finally:
            self._end_op()

    def create_folder(self, folder_name, parent_path):
        self._begin_op()
        try:
            with self._get_dir_lock(parent_path):
                self._add_item_in_directory(folder_name, parent_path, 'dir')
                self._write_header_only()
        finally:
            self._end_op()

    def move_file_to_directory(self, filename, old_path, new_path):
        self._begin_op()
        try:
            lock1, lock2 = sorted(
                [self._get_dir_lock(old_path), self._get_dir_lock(new_path)],
                key=id
            )
            with lock1, lock2:
                self._remove_item_from_directory(filename, old_path)
                self._add_item_in_directory(filename, new_path, 'file')
                self._write_header_only()
        finally:
            self._end_op()

    def move_within_file(self, file_obj, start, size, target):
        self._begin_op()
        try:
            file_obj.move_within_file(start, size, target)
            self._write_file_internal(file_obj)
        finally:
            self._end_op()

    def truncate_file(self, file_obj, max_size):
        self._begin_op()
        try:
            file_obj.truncate(max_size)
            self._write_file_internal(file_obj)
        finally:
            self._end_op()

    # ------------------------------------------------------------------
    # Memory map
    # ------------------------------------------------------------------
    def show_memory_map(self):
        with self.ops_condition:
            self.quiescing = True
            while self.active_ops > 0:
                self.ops_condition.wait()
        try:
            text = "-------------------- Memory Map --------------------"
            entries = []
            for fname, meta in self.header['files'].items():
                for i, seg in enumerate(meta['segments']):
                    entries.append({
                        'offset': seg['offset'],
                        'length': seg['length'],
                        'status': 'LIVE',
                        'file': f"{fname} (seg {i+1})"
                    })
            for block in self.header['dead_space']:
                entries.append({
                    'offset': block['offset'],
                    'length': block['size'],
                    'status': 'DEAD',
                    'file': '(free)'
                })
            entries.sort(key=lambda x: x['offset'])

            expected = 0
            with open(self.filesystem_path, 'rb') as f:
                f.seek(self.data_start)
                data_bytes = f.read()
            total_data_len = len(data_bytes)

            for e in entries:
                if e['offset'] > expected:
                    text += f"\n{expected:8d}  {e['offset']-expected:6d}  GAP      (unaccounted)"
                text += f"\n{e['offset']:8d}  {e['length']:6d}  {e['status']:6s}  {e['file']}"
                expected = e['offset'] + e['length']

            if expected < total_data_len:
                text += f"\n{expected:8d}  {total_data_len-expected:6d}  FREE     (end of data)"
            text += "\n----------------------------------------------------"
            return text
        finally:
            with self.ops_condition:
                self.quiescing = False
                self.ops_condition.notify_all()

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------
    def _normalize_path(self, path):
        if not path.startswith('/'):
            path = '/' + path
        return path.rstrip('/') or '/'

    def _hash_path(self, path):
        norm = self._normalize_path(path)
        path_bytes = norm.encode('utf-8')
        full_hash = hashlib.sha256(path_bytes).digest()
        return int.from_bytes(full_hash[:8], byteorder='big')

    def _add_item_in_directory(self, item_name, folderpath, type):
        normal_path = self._normalize_path(folderpath)
        item_path = normal_path + '/' + item_name if normal_path != '/' else item_name
        item_id = self._hash_path(item_path)
        parent_id = 0 if normal_path == '/' else self._hash_path(normal_path)
        self.header['directories'].append({
            "id": item_id,
            "name": item_name,
            "parent": parent_id,
            "type": type
        })

    def _remove_item_from_directory(self, item_name, parent_path):
        normal_path = self._normalize_path(parent_path)
        item_path = normal_path + '/' + item_name if normal_path != '/' else item_name
        item_id = self._hash_path(item_path)
        parent_id = 0 if normal_path == '/' else self._hash_path(normal_path)
        idx = next(
            (i for i, d in enumerate(self.header['directories'])
             if d['id'] == item_id and d['parent'] == parent_id),
            None
        )
        if idx is not None:
            self.header['directories'].pop(idx)
        else:
            print(f"[FS] Warning: '{item_name}' not found in '{parent_path}'")

    def folder_exists(self, foldername, parent_path):
        parent_id = 0 if self._normalize_path(parent_path) == '/' else self._hash_path(self._normalize_path(parent_path))
        return any(
            d['name'] == foldername
            and d['type'] == 'dir'
            and d.get('parent') == parent_id
            for d in self.header['directories']
        )

    def file_exists(self, filename):
        return filename in self.header['files']

    def list_files(self):
        return list(self.header['files'].keys())

    def list_contents(self, directory_path):
        parent_id = 0 if self._normalize_path(directory_path) == '/' else self._hash_path(self._normalize_path(directory_path))
        return self.get_children_from_parentid(parent_id)

    def get_children_from_parentid(self, parent_id):
        return [
            entry["id"] for entry in self.header["directories"]
            if entry.get("parent") == parent_id
        ]

    def get_name_from_id(self, id):
        for d in self.header["directories"]:
            if d['id'] == id:
                return d['name']
        return None

    def get_dir_size_from_id(self, id):
        total_size = 0
        children = self.get_children_from_parentid(id)
        for child_id in children:
            entry = next((d for d in self.header["directories"] if d["id"] == child_id), None)
            if entry is None:
                continue
            if entry["type"] == "file":
                filename = entry["name"]
                file_meta = self.header["files"].get(filename)
                if file_meta:
                    total_size += file_meta.get("size", 0)
        return total_size

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _divide_into_segments(self, content_bytes):
        return [content_bytes[i:i+SEGMENT_SIZE] for i in range(0, len(content_bytes), SEGMENT_SIZE)]

    def _serialize(self, content_str):
        return content_str.encode('utf-8')

    def _deserialize(self, data_bytes):
        return data_bytes.decode('utf-8')