from enum import Enum
from fs_core import FileSystem
from file_object import FileObject

class MainCommand(Enum):
    CREATE = "create"
    DELETE = "delete"
    MKDIR = "mkdir"
    CHDIR = "chdir"
    MOVE = "move"
    OPEN = "open"
    CLOSE = "close"
    WRITE = "write"
    READ = "read"
    WRITE_AT = "write_at"
    MOVE_WITHIN = "move_within"
    TRUNCATE = "truncate"
    MMAP = "mmap"
    MAN = "man"
    LS = "ls"
    QUIT = "q"
    HELP = "help"

class OpenMode(Enum):
    READ = "read"
    WRITE = "write"
    APPEND = "append"
    MOVE = "move"
    TRUNCATE = "truncate"

class Shell:
    def __init__(self):
        self.fs = FileSystem()
        self.running = True
        self._init_handlers()
        self.open_file = None

    def _init_handlers(self):
        """Map each command enum to its handler method."""
        self.handlers = {
            MainCommand.CREATE: self.handle_create,
            MainCommand.DELETE: self.handle_delete,
            MainCommand.MKDIR: self.handle_mkdir,
            MainCommand.CHDIR: self.handle_chdir,
            MainCommand.MOVE: self.handle_move,
            MainCommand.OPEN: self.handle_open,
            MainCommand.CLOSE: self.handle_close,
            MainCommand.WRITE: self.handle_write,
            MainCommand.READ: self.handle_read,
            MainCommand.WRITE_AT: self.handle_write_at,
            MainCommand.MOVE_WITHIN: self.handle_move_within,
            MainCommand.TRUNCATE: self.handle_truncate,
            MainCommand.MMAP: self.handle_mmap,
            MainCommand.MAN: self.handle_man,
            MainCommand.LS: self.handle_ls,
            MainCommand.QUIT: self.handle_quit,
            MainCommand.HELP: self.handle_help,
        }

    # ------------------------------------------------------------------
    # Command parsing and dispatch
    # ------------------------------------------------------------------
    def parse_command(self, user_input):
        """Convert user input string into (command_enum, args_list)."""
        parts = user_input.strip().split()
        if not parts:
            return None, []
        cmd_str = parts[0].lower()
        args = parts[1:]
        try:
            cmd = MainCommand(cmd_str)
        except ValueError:
            return None, args   # unknown command
        return cmd, args

    def run(self):
        print("Filesystem Shell. Type 'man' for help, 'q' to quit.")
        while self.running:
            try:
                user_input = input(">> ").strip()
                if not user_input:
                    continue
                cmd, args = self.parse_command(user_input)
                if cmd is None:
                    print(f"Unknown command: '{user_input.split()[0]}'")
                    continue
                handler = self.handlers.get(cmd)
                if handler:
                    handler(args)
                else:
                    print(f"Command '{cmd.value}' not yet implemented.")
            except KeyboardInterrupt:
                print("\nUse 'q' to quit.")
            except Exception as e:
                print(f"Error: {e}")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------
    def handle_create(self, args):
        ...

    def handle_delete(self, args):
        if len(args) < 1:
            print("Usage: delete <filename>")
            return
        ...
        
    def handle_mkdir(self, args):
        if len(args) < 1:
            print("Usage: mkdir <dirname>")
            return
        ...

    def handle_chdir(self, args):
        if len(args) < 1:
            print("Usage: chdir <dirname>")
            return
        ...

    def handle_move(self, args):
        if len(args) < 2:
            print("Usage: move <source> <target>")
            return
        src, tgt = args[0], args[1]
        if src not in self.fs.header['files']:
            print(f"Source '{src}' not found.")
            return
        ...

    def handle_open(self, args):
        if len(args) < 1:
            print("Usage: open <filename> [mode]")
            return
        ...

    def handle_close(self, args):
        if len(args) < 1:
            print("Usage: close <filename>")
            return
        ...
        

    def handle_write(self, args):
        if len(args) < 2:
            print("Usage: write <filename> <text>")
            return
        ...

    def handle_read(self, args):
        if len(args) < 1:
            print("Usage: read <filename> [start] [size]")
            return
        ...

    def handle_write_at(self, args):
        if len(args) < 3:
            print("Usage: write_at <filename> <position> <text>")
            return
        ...

    def handle_move_within(self, args):
        if len(args) < 4:
            print("Usage: move_within <filename> <start> <size> <target>")
            return
        ...

    def handle_truncate(self, args):
        if len(args) < 2:
            print("Usage: truncate <filename> <max_size>")
            return
        ...

    def handle_mmap(self):
        self.fs.show_memory_map()

    def handle_man(self):
        print("""
Available commands:
  create <filename>               - Create an empty file
  delete <filename>               - Delete a file
  mkdir <dirname>                 - Create a directory (basic)
  chdir <dirname>                 - Change directory (not fully implemented)
  move <src> <dst>                - Move/rename a file
  open <filename> [mode]          - Open a file (modes: read, write, append, move, truncate)
  close <filename>                - Close an open file
  write <filename> <text>         - Append text to an open file
  read <filename> [start] [size]  - Read from an open file
  write_at <filename> <pos> <text>- Overwrite at specific position
  move_within <f> <start> <size> <target> - Move block within file
  truncate <filename> <max_size>  - Truncate file to given size
  mmap                            - Show memory map (segments and dead space)
  ls                              - List all files/directories
  man                             - Show Manual
  q                               - Quit the shell
""")

    def handle_ls(self):
        entries = self.fs.list_files()
        if entries:
            for name in entries:
                meta = self.fs.header['files'][name]
                if meta.get('type') == 'dir':
                    print(f"[DIR]  {name}")
                else:
                    size = meta.get('size', 0)
                    print(f"[FILE] {name} ({size} bytes)")
        else:
            print("(empty)")

    def handle_quit(self, args):
        print("Exiting shell.")
        self.running = False

    def handle_help(self, args):
        self.handle_man(args)

def main():
    shell = Shell()
    shell.run()

if __name__ == "__main__":
    main()