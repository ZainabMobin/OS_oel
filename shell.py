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

    READ = "read"
    WRITE = "write"
    WRITE_AT = "write_at"
    MOVE_WITHIN = "move_within"
    TRUNCATE = "truncate"
    
    MMAP = "mmap"
    MAN = "man"
    LS = "ls"
    QUIT = "q"
    HELP = "help"

class Shell:
    def __init__(self):
        self.fs = FileSystem()
        self.running = True #loop runs by default
        self.opened_file = None #initially no file is opened
        self._init_handlers()


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


    def run(self): #main loop
        print("Filesystem Shell. Type 'man' for help, 'q' to quit.")
        while self.running:
            try:
                user_input = input(">> ").strip()
                if not user_input:
                    continue
                cmd, args = self.parse_command(user_input)
                if cmd is None:
                    continue
                handler = self.handlers.get(cmd)
                if not handler:
                    print(f"Command '{cmd.value}' not yet implemented.")
                    continue
                
                handler(args)
            except KeyboardInterrupt:
                print("\nUse 'q' to quit.")
            except Exception as e:
                print(f"Error: {e}")


    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------
    def handle_create(self, args):
        if len(args) < 1:
            print("Usage: create <filename>")
            return
        
        fname = args[0] if args else None
        if self.fs.file_exists(fname):
            print(f"File '{fname}' already exists.")
            return
        self.fs.create_file(fname)
        print(f"Succesfully created file:{fname}")
        ...


    def handle_delete(self, args):
        if len(args) < 1:
            print("Usage: delete <filename>")
            return
        fname = args[0] if args else None
        if not self.fs._delete_file(fname):
            print(f"File: {fname} could not be deleted")
            return
        print(f"File: {fname} has been deleted")
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


    def handle_open(self, args): # args passed = [mode, filename, ...]
        if len(args) < 2:
            print("Usage: open [mode] <filename> ")
            return

        mode_str = args[0]
        filename = args[1]
        extra = args[2:]

        if not self.fs.file_exists(filename):
            print(f"File '{filename}' not found.")
            return

        # check next command is from openMode enum, call appropriate func handler
        fileObj = self.fs.open_file(filename)
        if fileObj is None:
            print(f"Error: Could not open file '{filename}'.")
            return
        
        self.opened_file = fileObj  # store the currently open file object for subsequent operations

         # Convert string to MainCommand enum
        try:
            mode_enum = MainCommand(mode_str)
        except ValueError:
            print(f"Invalid mode '{mode_str}'")
            return

        handler = self.handlers.get(mode_enum) #lookup handler command using enum
        if not handler:
            print(f"Invalid mode '{mode_str}'")
            return
        
        if mode_enum == MainCommand.READ:
            self.handle_read(extra)   # pass fileObj and remaining args
        elif mode_enum == MainCommand.WRITE:
            self.handle_write(extra)   # pass remaining args
        elif mode_enum == MainCommand.WRITE_AT:
            self.handle_write_at(extra)
        elif mode_enum == MainCommand.MOVE:
            ...
        elif mode_enum == MainCommand.TRUNCATE:
            ...
        else:
            print(f"Mode '{mode_str}' is not supported with open.")

    
    def handle_write(self, args):
        text = self.extract_text(args)
        self.opened_file.write(text, mode='append')  # append text to file, args[0] is the text to write
        self.fs.write_file(self.opened_file) # write the updated file object back to the filesystem.dat


    def extract_text(self, args):
        """Extract text from args, handling quotes if present."""
        if not args:
            return ""
        if args[0].startswith("'") and args[-1].endswith("'"):
            return ' '.join(args)[1:-1]  # remove surrounding quotes
        return ' '.join(args)  # no quotes, just join


    def handle_read(self, args):
        start = int(args[0]) if len(args) > 0 else 0
        size = int(args[1]) if len(args) > 1 else None
        content = self.opened_file.read(start, size)
        #display content on the terminal, with some sort of line numbering for ease of positions for write to place func
        if not content:
            print("(empty file)")
            return
        print(content)


    def handle_write_at(self, args):
        if len(args) < 2:
            print("Usage: open write_at <filename> <position> 'text'")
            return
        if self.opened_file is None:
            print("No file is currently open.")
            return

        try:
            position = int(args[0])
        except ValueError:
            print("Position must be an integer.")
            return

        text = self.extract_text(args[1:])
        self.opened_file.write_at(position, text)
        self.fs.write_file(self.opened_file)
        print(f"Wrote at position {position} in '{self.opened_file.name}'.")


    def handle_move_within(self, args):
        if len(args) < 3:
           print("Usage: open move_within <filename> <start> <size> <target>")
           return
        if self.opened_file is None:
           print("No file is currently open.")
           return
        try:
           start  = int(args[0])
           size   = int(args[1])
           target = int(args[2])
        except ValueError:
           print("start, size, and target must be integers.")
           return

        file_size = len(self.opened_file.content)
        if target > file_size:
           print(f"Error: target {target} exceeds file size {file_size}.")
           return

        self.fs.move_within_file(self.opened_file, start, size, target)
        print(f"Moved {size} bytes from {start} → {target} in '{self.opened_file.name}'.")

    def handle_truncate(self, args):
        if len(args) < 1:
           print("Usage: open truncate <filename> <max_size>")
           return
        if self.opened_file is None:
           print("No file is currently open.")
           return
        try:
           max_size = int(args[0])
        except ValueError:
           print("max_size must be an integer.")
           return
        if max_size < 0:
           print("max_size must be non-negative.")
           return

        self.fs.truncate_file(self.opened_file, max_size)
        print(f"Truncated '{self.opened_file.name}' to {max_size} bytes.")

    def handle_close(self, args):
        if len(args) < 1:
            print("Usage: close <filename>")
            return
        ...


    def handle_mmap(self, args):
        self.fs.show_memory_map()

    def handle_man(self, args):
        print("""
Available commands:
  create <filename>                                          - Create an empty file
  delete <filename>                                          - Delete a file
  mkdir <dirname>                                            - Create a directory
  chdir <dirname>                                            - Change directory
  move <src> <dst>                                           - Move a file
  --------------------------------------------------------------------------------------------
  Open:   Opens a file (modes: read, write, append, move, truncate)
  open read <filename>                                       - Read from an open file
  open read <filename> [start] [size]                        - Read from a specific position
  open write <filename> 'text'                               - Append text at the end
  open write_at <filename> <pos> 'text'                      - Overwrite at specific position
  open move_within <filename> <start> <size> <target>        - Move block within file
  open truncate <filename> <max_size>                        - Truncate file to given size
  --------------------------------------------------------------------------------------------
  close <filename>                                           - Close an open file
  mmap                                                       - Show memory map
  ls                                                         - List all files/directories
  man                                                        - Show Manual
  q                                                          - Quit the shell
""")

    def handle_ls(self, args):
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
        self.running = False

    def handle_help(self, args):
        self.handle_man(args)

def main():
    shell = Shell()
    shell.run()

if __name__ == "__main__":
    main()