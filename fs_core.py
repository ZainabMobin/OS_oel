import json
import os
from file_object import FileObject 
# HEADER_LIMIT = 5  #assume header limit is set to 5 MB
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

    def update_header(self):
        """Update only the header region without touching data."""
        self._write_header_only() 

    def _add_dead_space(self, offset, size):
        if size <= 0:
            return
        self.header['dead_space'].append({
            "offset": offset,
            "size": size,
        })
        self.update_header()

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
        

    def create_file(self, filename):
        #add new file in metadata array with empty content, then write the file to the data region using write_file function, this will create an empty file in the filesystem with the given filename and update the header metadata accordingly
        self.header['files'][filename] = {
            'size': 0,
            'segments': []
        }
        self.update_header() #updates and adds file metadata to the header
    
    def _delete_file(self, fname):
        # 1. Check file exists
        if fname not in self.header['files']:
           print(f"[FS] Error: File '{fname}' not found.")
           return False

        # 2. Free its data segments → mark as dead space
        for seg in self.header['files'][fname]['segments']:
           self._add_dead_space(seg['offset'], seg['length'])
           # Note: _add_dead_space already calls update_header(), 
          # but we'll do a final write below anyway

        # 3. Remove from in-memory header (RAM)
        del self.header['files'][fname]

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
    def file_exists(self, filename):
        return filename in self.header['files']

    def list_files(self):
        return list(self.header['files'].keys())

    def show_memory_map(self):
        """Simple memory map showing live segments and dead space."""
        print("\n--- Memory Map ---")
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
        print("------------------\n")


    def divide_into_segments(self, content):
        # This function will divide the file content into segments of size SEGMENT_SIZE and return a list of segments
        return [content[i:i + SEGMENT_SIZE] for i in range(0, len(content), SEGMENT_SIZE)]


    def serialize_helper(self, file_object):
        # This function will convert a FileObject instance into a format suitable for storage in the data region
        return file_object.content.encode()  # Convert string content to bytes

    def reconstruct_file_object(self, name, content):
        # This function will create a FileObject instance from the given name and content
        # read all segments serially,  deserialize them using helper function
        # after deserialization, reorderng done via offset order from metadata, then return the file object instance
        ...

    def read_serialized_content(self, offset, size=None):
        # This function will read the serialized content from the data region of filesystem.dat using the given offset and size
        with open(self.filesystem_path, 'rb') as f:
            f.seek(offset)
            if size is None:
                return f.read()  # Read until the end of file
            return f.read(size) #read until specific length of file
        
    def deserialize_helper(self, data):
        # This function converts serialized data back into a FileObject instance
        ...

    # def add_dummy_file(self):
    #     # This function is just for testing purposes to add a dummy file to the filesystem
    #     with open('filesystem.dat', 'r') as f:
    #         filesystem_structure = json.load(f)
        
    #     # Add a dummy file metadata
    #     filesystem_structure['files']['dummy.txt'] = {
    #         "size": 100,  # Size in bytes
    #         "offset": HEADER_LIMIT * 1024 * 1024  # Assuming data starts right after the header limit
    #     }
        
    #     # Update the dead space array (for simplicity, we won't actually manage it here)
    #     filesystem_structure['dead_space'].append({
    #         "offset": HEADER_LIMIT * 1024 * 1024 + 100,  # Next free offset after the dummy file
    #         "size": 900  # Remaining free space in this block
    #     })
        
    #     # Write the updated structure back to filesystem.dat
    #     with open('filesystem.dat', 'w') as f:
    #         json.dump(filesystem_structure, f)