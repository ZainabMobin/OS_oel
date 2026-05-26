import threading

class RWLock:
    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0

    def acquire_read(self):
        with self._read_ready:
            self._readers += 1

    def release_read(self):
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def acquire_write(self):
        self._read_ready.acquire()
        while self._readers > 0:
            self._read_ready.wait()

    def release_write(self):
        self._read_ready.notify_all()
        self._read_ready.release()


class FileObject:
    def __init__(self, name, content, existing_segments=None):
        self.name = name
        self.content = content
        self.segments = existing_segments or []
        self.lock = RWLock()

    def read(self, start=0, size=None):
        self.lock.acquire_read()
        try:
            if start < 0:
                start = 0
            if size is None or start + size > len(self.content):
                return self.content[start:]
            return self.content[start:start+size]
        finally:
            self.lock.release_read()

    def write(self, text, mode='append'):
        self.lock.acquire_write()
        try:
            if mode == 'append':
                self.content += text
            elif mode == 'overwrite':
                self.content = text
            else:
                raise ValueError("Mode must be 'append' or 'overwrite'")
        finally:
            self.lock.release_write()

    def write_at(self, pos, text):
        self.lock.acquire_write()
        try:
            if pos < 0:
                pos = 0
            if pos > len(self.content):
                pos = len(self.content)
            self.content = self.content[:pos] + text + self.content[pos + len(text):]
            return self
        finally:
            self.lock.release_write()

    def move_within_file(self, start, size, target):
        self.lock.acquire_write()
        try:
            chunk = self.content[start:start + size]
            without_chunk = self.content[:start] + self.content[start + size:]
            if target > start:
                target -= size
            self.content = without_chunk[:target] + chunk + without_chunk[target:]
            return self
        finally:
            self.lock.release_write()

    #truncates file by given size
    def truncate(self, max_size):
        self.lock.acquire_write()
        try:
            self.content = self.content[:max_size]
            return self
        finally:
            self.lock.release_write()

    #returns file size
    def get_size(self):
        self.lock.acquire_read()
        try:
            return len(self.content)
        finally:
            self.lock.release_read()

    #closes file
    def close(self):
        self.lock.acquire_write()
        try:
            self.content = ""
            self.segments = []
        finally:
            self.lock.release_write()
