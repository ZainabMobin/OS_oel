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
        ... 

    def move_within_file(self, start, size, target):
        ...

    def truncate(self, max_size):
        ...

    def close(self):
        ...