class FileObject:
    """
    Represents an open file in memory.
    Stores the file name, its content, and optionally its segment layout
    (used when loading an existing file).
    """
    def __init__(self, name, content, existing_segments=None):
        self.name = name
        self.content = content          # string content
        self.segments = existing_segments or []   # metadata for existing files ie segment offsets


    def read(self, start=0, size=None):
        """Read up to 'size' bytes from 'start'."""
        if start < 0:
            start = 0
        if size is None or start + size > len(self.content):
            return self.content[start:]
        return self.content[start:start+size]
    

    def write(self, text, mode='append'):
        """
        Write text to the file.
        mode 'append' adds to the end; 'overwrite' replaces whole content.
        """
        if mode == 'append':
            self.content += text
        elif mode == 'overwrite':
            self.content = text
        else:
            raise ValueError("Mode must be 'append' or 'overwrite'")

    def write_at(self, pos, text):
        """Overwrite content at the given byte index and return the updated FileObject."""
        if pos < 0:
            pos = 0
        if pos > len(self.content):
            pos = len(self.content)
        self.content = self.content[:pos] + text + self.content[pos + len(text):]
        return self

    def move_within_file(self, start, size, target):
        chunk = self.content[start:start + size]         # grab the chunk
        without_chunk = self.content[:start] + self.content[start + size:]  # remove it

        # Adjust target since the string shifted after removal
        if target > start:
           target -= size

        self.content = without_chunk[:target] + chunk + without_chunk[target:]
        return self

    def truncate(self, max_size):
       self.content = self.content[:max_size]
       return self


    def close(self):
       """Clear in-memory content (actual persist happens via fs.write_file)."""
       self.content = ""
       self.segments = []