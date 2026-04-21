import json
import os
from file_object import FileObject 
import hashlib # for sha-256 hashing

SEGMENT_SIZE = 512 # assume 512 bytes for each file metadata entry in the header
SEPERATOR = b'<<<DATA>>> ' # binary separator between header and data region in filesystem.dat
HEADER_SIZE = 65536  # 64 KB fixed header region
SEPARATOR_POS = HEADER_SIZE  # Separator always at byte 65536
DATA_START = HEADER_SIZE + len(SEPERATOR)  # Data always starts here

class FileSystem:
    def __init__(self):
        self.filesystem_path = 'filesystem.dat'
        self.header = None  # This will hold the header metadata structure and dead array after loading from filesystem.dat
        self.data_start = 0
        self._load_or_init()


    def _load_or_init(self):
        if not os.path.exists(self.filesystem_path):
            # Create the initial structure for the filesystem
            self._init_filesystem()
            
        self._load_filesystem()
        

    # init the file metadata ie json header schema for file structure and the dead space array as well if there doesnt exist filesysatem.dat, then put thatinto filesystem.dat 
    def _init_filesystem(self):
            header = {
                "directories": [{"id":0, "name":"/", "parent": None, "type": "dir"},], #directory structure is a flat list to prevent deep recursion  
                "files": {},  # This will hold file metadata
                "dead_space": []  # This will track free space in the data region
            }
            self._write_header_and_data(header, b'')


    def _should_compact(self):
        """Decide if compaction is needed based on dead space fragmentation."""
        if not self.header['dead_space']:
            return False
        
        # Calculate average dead block size
        total_dead = sum(block['size'] for block in self.header['dead_space'])
        num_blocks = len(self.header['dead_space'])
        avg_size = total_dead / num_blocks if num_blocks > 0 else 0
        
        # Threshold: if average dead block < 180 bytes, compaction needed
        threshold = 180
        return avg_size < threshold


    def _compact_data_region(self):
        """Compact the data region by rewriting live segments contiguously."""
        print("[FS] Compacting data region...")
        
        # Read entire data region (educational - in production, stream)
        with open(self.filesystem_path, 'rb') as f:
            f.seek(DATA_START)
            data_bytes = f.read()
        
        # Collect all live segments in logical order (as they appear in metadata)
        live_segments = []
        for fname, meta in self.header['files'].items():
            for seg in meta['segments']:
                live_segments.append({
                    'fname': fname,
                    'offset': seg['offset'],
                    'length': seg['length'],
                    'data': data_bytes[seg['offset']:seg['offset'] + seg['length']]
                })
        
        # Build new compacted data
        new_data = bytearray()
        new_offset = 0
        for seg in live_segments:
            seg['new_offset'] = new_offset
            new_data.extend(seg['data'])
            new_offset += seg['length']
        
        # Write compacted data back
        with open(self.filesystem_path, 'r+b') as f:
            f.seek(DATA_START)
            f.write(new_data)
            f.truncate(DATA_START + len(new_data))  # Remove orphaned bytes
        
        # Update metadata with new offsets
        for seg in live_segments:
            fname = seg['fname']
            old_offset = seg['offset']
            new_offset = seg['new_offset']
            # Find and update the segment in header
            for file_seg in self.header['files'][fname]['segments']:
                if file_seg['offset'] == old_offset:
                    file_seg['offset'] = new_offset
                    break
        
        # Clear dead space
        self.header['dead_space'] = []
        
        # Write updated header
        self._write_header_only()

        print(f"[FS] Compacted {len(live_segments)} segments, freed {len(data_bytes) - len(new_data)} bytes")


    def _load_filesystem(self):
        with open(self.filesystem_path, 'rb') as f:
           header_bytes = f.read(HEADER_SIZE)

        header_json = header_bytes.rstrip(b'\x00').decode()
       
        try:
            self.header = json.loads(header_json)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON header {e}")
        self.data_start = DATA_START
        
        # Check if compaction needed
        if self._should_compact():
            self._compact_data_region()


    def _write_header_and_data(self, header_dict, data):
        header_json = json.dumps(header_dict).encode()  # Convert header dict to JSON bytes
        padding_needed = HEADER_SIZE - len(header_json)
        if padding_needed > 0:
            header_json += b'\x00' * padding_needed
        # Now header_json is exactly HEADER_SIZE bytes
        with open(self.filesystem_path, 'wb') as f:
            f.write(header_json)
            f.write(SEPERATOR)
            f.write(data)

        self.header = header_dict  # Update the in-memory header after writing
    

    def _write_header_only(self):
        """Write only the header (with padding) and separator. Data region untouched."""
        header_json = json.dumps(self.header).encode()
        padding_needed = HEADER_SIZE - len(header_json)
        if padding_needed > 0:
            header_json += b'\x00' * padding_needed
        with open(self.filesystem_path, 'r+b') as f:
            f.seek(0)
            f.write(header_json)
            f.write(SEPERATOR)
    

    def _write_segment_at_offset(self, relative_offset, data):
        """Write segment bytes at a specific offset in the data region."""
        absolute_offset = DATA_START + relative_offset
        with open(self.filesystem_path, 'r+b') as f:
            f.seek(absolute_offset)
            f.write(data)
 

    def _add_dead_space(self, offset, size):
        if size <= 0:
            return
        self.header['dead_space'].append({
            "offset": offset,
            "size": size,
        })
        self._write_header_only()


    def _allocate_space(self, needed):
        """
        Find a dead block that can hold 'needed' bytes.
        Returns (offset, block_index) or (None, None) if no suitable block.
        (First‑fit strategy, you can change to best‑fit if desired.)
        """
        for i, block in enumerate(self.header['dead_space']):
            if block['size'] >= needed:
                return block['offset'], i
        return None, None


    def _consume_dead_block(self, idx, used_length):
        """
        Remove or shrink a dead block after allocation.
        If the block is exactly used up, remove it; otherwise reduce its offset and size.
        """
        block = self.header['dead_space'][idx]
        if block['size'] == used_length:
            self.header['dead_space'].pop(idx)
        else:
            block['offset'] += used_length
            block['size'] -= used_length

    # ----------------------------------------------------------------------
    # File operations
    # ----------------------------------------------------------------------
    def write_file(self, file_obj):
        """
        Write (or overwrite) a file's content into the filesystem.
        - Old segments (if any) are freed to dead_space.
        - Content is divided into segments.
        - Each segment tries to allocate from dead_space first, else appends at end.
        - Only segment bytes are written (via seek/write).
        - Header is updated separately (via _write_header_only).
        """
        name = file_obj.name
        content_bytes = self._serialize(file_obj.content)

        # If file already exists, free its old segments
        if name in self.header['files']:
            old_meta = self.header['files'][name]
            for seg in old_meta['segments']:
                self._add_dead_space(seg['offset'], seg['length'])

        # Divide into segments
        segments_data = self._divide_into_segments(content_bytes)

        # Calculate current data region end
        file_size = os.path.getsize(self.filesystem_path) if os.path.exists(self.filesystem_path) else 0
        data_region_size = file_size - DATA_START if file_size >= DATA_START else 0
        next_append_pos = data_region_size

        new_segments = []

        for seg_bytes in segments_data:
            seg_len = len(seg_bytes)
            
            # Try to allocate from dead space first
            alloc_offset, block_idx = self._allocate_space(seg_len)
            
            if alloc_offset is not None:
                # Use dead space
                self._write_segment_at_offset(alloc_offset, seg_bytes)
                new_segments.append({'offset': alloc_offset, 'length': seg_len})
                self._consume_dead_block(block_idx, seg_len)
            else:
                # Append at end of data region
                self._write_segment_at_offset(next_append_pos, seg_bytes)
                new_segments.append({'offset': next_append_pos, 'length': seg_len})
                next_append_pos += seg_len

        # Update metadata
        self.header['files'][name] = {
            'size': len(content_bytes),
            'segments': new_segments
        }

        # Write only header (data already written via seek/write)
        self._write_header_only()

        print(f"[FS] Written '{name}' ({len(content_bytes)} bytes) in {len(new_segments)} segment(s).")


    # fileobject passed with name, verified from filesystem structure, then read the content from the data region of filesystem.dat using the offset and size from metadata
    # and return deserialized content
    def open_file(self, filename):
        """
        Retrieve a file's content from the data section using its metadata.
        Returns a FileObject instance or None if the file does not exist.
        """
        try:
            if filename not in self.header['files']:
                print(f"[FS] Error: File '{filename}' not found.")
                return None

            meta = self.header['files'][filename]

            # Read all segments from the data section
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
        

    #generic function that handles both file and folder 
    def _add_item_in_directory(self, item_name, folderpath, type):
        normal_path = self._normalize_path(folderpath)
        item_path = normal_path + '/' + item_name if normal_path != '/' else item_name #construct filepath
        id = self._hash_path(item_path)
        parent_id = self._hash_path(normal_path) if normal_path != '/' else 0
        self.header['directories'].append({
            "id": id,
            "name": item_name,
            "parent": parent_id,
            "type": type
        })


    def move_file_to_directory(self, filename, old_path, new_path):
        """ moves file from old to new directory """
        old_norm = self._normalize_path(old_path)
        new_norm = self._normalize_path(new_path)
        self._remove_item_from_directory(filename, old_norm) #remove file entry from current directory
        self._add_item_in_directory(filename, new_norm, 'file') #place it in the new directory
        self._write_header_only() #updates header with new file entry in directory


    def _remove_item_from_directory(self, item_name, parent_path):
        normal_path = self._normalize_path(parent_path)
        item_path = normal_path + '/' + item_name if normal_path != '/' else item_name #construct filepath
        id = self._hash_path(item_path)
        
        parent_id = self._hash_path(normal_path) if normal_path != '/' else 0
        del self.header['directories'][next(i for i, d in enumerate(self.header['directories']) if d['id'] == id and d['parent'] == parent_id)]


    def _hash_path(self, path):
        """Returns a 64‑bit integer derived from the file path using SHA‑256."""
        norm = self._normalize_path(path) #normalize path
        path_bytes = norm.encode('utf-8') # Ensure consistent encoding
        full_hash = hashlib.sha256(path_bytes).digest() # Full SHA-256 hash (32 bytes)
        return int.from_bytes(full_hash[:8], byteorder='big') # Take the first 8 bytes (64 bits) and convert to integer
    

    def create_folder(self, folder_name, parent_path):
        """creates a folder in the given parent folder"""
        norm_path = self._normalize_path(parent_path)
        folder_path = norm_path + '/' + folder_name if norm_path != '/' else folder_name
        self._add_item_in_directory(folder_path, norm_path, 'dir')
        self._write_header_only() #updates header with new folder 


    def create_file(self, filename, parent_path):
        """add new file in metadata array with empty content, then write the file to the data region using write_file function, this will create an empty file in the filesystem with the given filename and update the header metadata accordingly"""
        self._add_item_in_directory(filename, parent_path, 'file') #file entry added in folder
        self.header['files'][filename] = {
            'size': 0,
            'segments': []
        }
        self._write_header_only() #updates and adds file metadata to the header
    

    def delete_file(self, fname, parent_path):
        """delete a file from the filesystem"""
        # 1. Check file exists
        if fname not in self.header['files']:
           print(f"[FS] Error: File '{fname}' not found.")
           return False

        # 2. Free its data segments → mark as dead space
        for seg in self.header['files'][fname]['segments']:
           self._add_dead_space(seg['offset'], seg['length'])
           # Note: _add_dead_space already calls _write_header_only(), 
          # but we'll do a final write below anyway

        # 3. Remove from in-memory header (RAM)
        del self.header['files'][fname]
        self._remove_item_from_directory(fname, parent_path) #remove file entry from directory

        # 4. Write updated header to filesystem.dat 
        #    (_write_header_only keeps it exactly HEADER_SIZE = 64KB via padding)
        self._write_header_only()

        print(f"[FS] Deleted '{fname}', segments returned to dead_space.")
        return True
        

    def move_within_file(self, file_obj, start, size, target):
       file_obj.move_within_file(start, size, target)   # mutate string in RAM
       self.write_file(file_obj)                         # re-segment and persist


    def truncate_file(self, file_obj, max_size):
       file_obj.truncate(max_size)   # trim string in RAM
       self.write_file(file_obj)     # re-segment and persist

       
    # ----------------------------------------------------------------------
    # Helper methods (segmentation, serialisation)
    # ----------------------------------------------------------------------
    def _divide_into_segments(self, content_bytes):
        """Split bytes into chunks of SEGMENT_SIZE."""
        return [content_bytes[i:i+SEGMENT_SIZE] for i in range(0, len(content_bytes), SEGMENT_SIZE)]


    def _serialize(self, content_str):
        """Convert a string to bytes (UTF-8)."""
        return content_str.encode('utf-8')


    def _deserialize(self, data_bytes):
        """Convert bytes back to a UTF-8 string."""
        return data_bytes.decode('utf-8')

    # ----------------------------------------------------------------------
    # Additional utilities
    # ----------------------------------------------------------------------
    
    def folder_exists(self, foldername, parent_path):
        parent_id = self._hash_path(self._normalize_path(parent_path)) if parent_path != '/' else 0
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
    

    def _normalize_path(self, path):
        """Return absolute path starting with '/' and no trailing slash (except root)."""
        if not path.startswith('/'):
            path = '/' + path
        return path.rstrip('/') or '/'


    def list_contents(self, directory_path):
        parent_id = self._hash_path(self._normalize_path(directory_path)) if directory_path != '/' else 0
        return self.get_children_from_parentid(parent_id)


    def get_children_from_parentid(self, parent_id):
        """return list of names of files and folders whose parent is the given directory id"""
        children = [
            entry["id"] for entry in self.header["directories"]
            if entry.get("parent") == parent_id
        ]
        return children


    def get_name_from_id(self, id):
        """return name of item from the given id"""
        for d in self.header["directories"]:
            if d['id'] == id:
                return d['name']
        return None
    

    def get_dir_size_from_id(self, id):
        """calculate total size of all files in the directory with the given id"""
        total_size = 0
        children = self.get_children_from_parentid(id)
        for child_id in children:
            # Find the directory entry for this child
            entry = next((d for d in self.header["directories"] if d["id"] == child_id), None)
            if entry is None:
                continue
            if entry["type"] == "file":
                filename = entry["name"]
                file_meta = self.header["files"].get(filename)
                if file_meta:
                    total_size += file_meta.get("size", 0)
        return total_size
    

    def show_memory_map(self):
        """Simple memory map showing live segments and dead space."""
        print("\n-------------------- Memory Map --------------------")
        # Collect all segments with file info
        entries = []
        for fname, meta in self.header['files'].items():
            for i, seg in enumerate(meta['segments']):
                entries.append({
                    'offset': seg['offset'],
                    'length': seg['length'],
                    'status': 'LIVE',
                    'file': f"{fname} (seg {i+1})"
                })
        # Add dead space
        for block in self.header['dead_space']:
            entries.append({
                'offset': block['offset'],
                'length': block['size'],
                'status': 'DEAD',
                'file': '(free)'
            })
        # Sort by offset
        entries.sort(key=lambda x: x['offset'])

        # Print with gap detection
        expected = 0
        with open(self.filesystem_path, 'rb') as f:
            f.seek(self.data_start)
            data_bytes = f.read()
        total_data_len = len(data_bytes)

        for e in entries:
            if e['offset'] > expected:
                print(f"{expected:8d}  {e['offset']-expected:6d}  GAP      (unaccounted)")
            print(f"{e['offset']:8d}  {e['length']:6d}  {e['status']:6s}  {e['file']}")
            expected = e['offset'] + e['length']

        if expected < total_data_len:
            print(f"{expected:8d}  {total_data_len-expected:6d}  FREE     (end of data)")
        print("----------------------------------------------------\n")


    def divide_into_segments(self, content):
        # This function will divide the file content into segments of size SEGMENT_SIZE and return a list of segments
        return [content[i:i + SEGMENT_SIZE] for i in range(0, len(content), SEGMENT_SIZE)]


    def serialize_helper(self, file_object):
        # This function will convert a FileObject instance into a format suitable for storage in the data region
        return file_object.content.encode()  # Convert string content to bytes


    def read_serialized_content(self, offset, size=None):
        # This function will read the serialized content from the data region of filesystem.dat using the given offset and size
        with open(self.filesystem_path, 'rb') as f:
            f.seek(offset)
            if size is None:
                return f.read()  # Read until the end of file
            return f.read(size) #read until specific length of file