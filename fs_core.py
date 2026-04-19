import json
import os
import file_object
# HEADER_LIMIT = 5  #assume header limit is set to 5 MB
SEGMENT_SIZE = 512 # assume 512 bytes for each file metadata entry in the header
SEPERATOR = b'<<<DATA>>> ' # binary separator between header and data region in filesystem.dat

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
        

    # init  the file metadata ie json header schema for file structure and the dead space array as well if there doesnt exist filesysatem.dat, then put thatinto filesystem.dat 
    def _init_filesystem(self):
            header = {
                "files": {},  # This will hold file metadata
                "dead_space": []  # This will track free space in the data region
            }
            self._write_header_and_data(header, b'')

    def _load_filesystem(self):
        with open(self.fileststem_path, 'rb') as f:
            raw = f.read()
        
        sep_offset = raw.find(SEPERATOR)
        if sep_offset == -1:
            raise ValueError("Invalid filesystem.dat format: Missing separator")
        
        header_bytes = raw[:sep_offset]
        self.data_start = sep_offset + len(SEPERATOR)

        try:
            self.header = json.loads(header_bytes.decode())
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON header {e}")

    def write_header_and_data(self, header_dict, data):
        header_json = json.dumps(header_dict).encode()  # Convert header dict to JSON bytes
        with open(self.filesystem_path, 'wb') as f:
            f.write(header_json)
            f.write(SEPERATOR)
            f.write(data)

        self.header = header_dict  # Update the in-memory header after writing
        self.data_start = len(header_json) + len(SEPERATOR)  # Update data start offset

    def update_header(self):
        temp_fs = FileSystem() # create a temporary instance to load the current header and data, then write it back with the updated header, this is to ensure that we are not losing any data while updating the header
        
        #if current loaded heaser is different thatn the stored one, update the header in the file with the current loaded one, and rewrite the data region as well since it will be shifted due to change in header size
        #  
        data_bytes = temp_fs.read_serialized_content()

        self._write_header_and_data(self.header, data_bytes)
        ##feels like an issue, to rewrite the whole data region every time we update the header also not to mention how raw json will frastically take up space with verbose headings 
        # it should have either a limit for the header, or be stored in a seperate file itself, 

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
            if block['length'] >= needed:
                return block['offset'], i
        return None, None

    def _consume_dead_block(self, idx, used_length):
        """
        Remove or shrink a dead block after allocation.
        If the block is exactly used up, remove it; otherwise reduce its offset and length.
        """
        block = self.header['dead_space'][idx]
        if block['length'] == used_length:
            self.header['dead_space'].pop(idx)
        else:
            block['offset'] += used_length
            block['length'] -= used_length

    # ----------------------------------------------------------------------
    # File operations
    # ----------------------------------------------------------------------
    def write_file(self, file_obj):
        """
        Write (or overwrite) a file's content into the filesystem.
        - Old segments (if any) are freed.
        - Content is divided into fixed‑size segments.
        - Each segment is written to the end of the data section (for simplicity).
        - Header is updated with new segment list and size.
        - Dead space is updated with the old segments.
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

        # Determine where new data will be written.
        # For simplicity we always append at the end of the current data section.
        # (You can later enhance to reuse dead space using _allocate_space.)
        with open(self.dat_path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            current_end = f.tell()

        # But wait: the data section may not extend to the end of file if we only
        # update the header. So we actually need to know the real end of data section.
        # We'll read the whole data section to know its current length.
        with open(self.dat_path, 'rb') as f:
            f.seek(self.data_start)
            data_bytes = f.read()
        data_len = len(data_bytes)

        new_segments = []
        write_pos = self.data_start + data_len   # append at the end

        for seg_bytes in segments_data:
            seg_len = len(seg_bytes)
            new_segments.append({'offset': write_pos - self.data_start, 'length': seg_len})
            # Append this segment to the data bytes
            data_bytes += seg_bytes
            write_pos += seg_len

        # Update metadata
        self.header['files'][name] = {
            'size': len(content_bytes),
            'segments': new_segments
        }

        # Write everything back (header + updated data section)
        self._write_header_and_data(self.header, data_bytes)

        print(f"[FS] Written '{name}' ({len(content_bytes)} bytes) in {len(new_segments)} segment(s).")

    def open_file(self, filename):
        """
        Retrieve a file's content from the data section using its metadata.
        Returns a FileObject instance or None if the file does not exist.
        """
        if filename not in self.header['files']:
            print(f"[FS] Error: File '{filename}' not found.")
            return None

        meta = self.header['files'][filename]

        # Read all segments from the data section
        with open(self.dat_path, 'rb') as f:
            f.seek(self.data_start)
            data_bytes = f.read()

        content_bytes = bytearray()
        for seg in meta['segments']:
            start = seg['offset']
            end = start + seg['length']
            content_bytes.extend(data_bytes[start:end])

        content_str = self._deserialize(content_bytes)
        return file_object(filename, content_str, existing_segments=meta['segments'])

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
                'length': block['length'],
                'status': 'DEAD',
                'file': '(free)'
            })
        # Sort by offset
        entries.sort(key=lambda x: x['offset'])

        # Print with gap detection
        expected = 0
        with open(self.dat_path, 'rb') as f:
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

    def write_file(self, file_object):
        # This function will write the file content to the data region of filesystem.dat
        # and update the metadata structure accordingly
        ...

    def open_file(self, file_object):
        # fileobject passed with name, verified from filesystem structure, then read the content from the data region of filesystem.dat using the offset and size from metadata
        # and return deserialized content
        ...

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

    def read_serialized_content(self, offset, size):
        # This function will read the serialized content from the data region of filesystem.dat using the given offset and size
        with open(self.filesystem_path, 'rb') as f:
            f.seek(offset)
            return f.read(size)
        
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
