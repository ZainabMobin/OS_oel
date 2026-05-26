import os
import sys
import threading
from enum import Enum
from fs_core import FileSystem


class MainCommand(Enum):
    CREATE      = "create"
    DELETE      = "delete"
    MKDIR       = "mkdir"
    CHDIR       = "chdir"
    MOVE        = "move"
    OPEN        = "open"
    CLOSE       = "close"
    READ        = "read"
    WRITE       = "write"
    WRITE_AT    = "write_at"
    MOVE_WITHIN = "move_within"
    TRUNCATE    = "truncate"
    MMAP        = "mmap"
    MAN         = "man"
    CWD         = "cwd"
    LS          = "ls"
    QUIT        = "q"
    HELP        = "help"


class Shell:
    def __init__(self, k):
        self.fs = FileSystem()
        self.running = True
        self.num_threads = k
        self.threads = []
        self.thread_local = threading.local()
        self._init_handlers()
        self._init_threads()

    def _ensure_thread_state(self):
        if not hasattr(self.thread_local, "cwd"):
            self.thread_local.cwd = "/"
            self.thread_local.opened_file = None
            self.thread_local.opened_file_mode = None

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------
    def _thread_task(self, id):
        self._ensure_thread_state()
        in_file  = f"io/input_thread{id}.txt"
        out_file = f"io/output_thread{id}.txt"
        result   = ""
        try:
            with open(in_file, "r") as infile:
                for line in infile:
                    cmd = line.strip()
                    if cmd:
                        result += (self.execute_command(cmd) or "") + "\n"
        except FileNotFoundError:
            result += f"{in_file} not found\n"
        with open(out_file, "w") as outfile:
            outfile.write(result)

    def _init_threads(self):
        os.makedirs("io", exist_ok=True)
        for i in range(1, self.num_threads + 1):
            t = threading.Thread(target=self._thread_task, args=(i,))
            self.threads.append(t)
            t.start()
        for t in self.threads:
            t.join()

    def _init_handlers(self):
        self.handlers = {
            MainCommand.CREATE:      self.handle_create,
            MainCommand.DELETE:      self.handle_delete,
            MainCommand.MKDIR:       self.handle_mkdir,
            MainCommand.CHDIR:       self.handle_chdir,
            MainCommand.MOVE:        self.handle_move,
            MainCommand.OPEN:        self.handle_open,
            MainCommand.CLOSE:       self.handle_close,
            MainCommand.WRITE:       self.handle_write,
            MainCommand.READ:        self.handle_read,
            MainCommand.WRITE_AT:    self.handle_write_at,
            MainCommand.MOVE_WITHIN: self.handle_move_within,
            MainCommand.TRUNCATE:    self.handle_truncate,
            MainCommand.MMAP:        self.handle_mmap,
            MainCommand.MAN:         self.handle_man,
            MainCommand.CWD:         self.handle_cwd,
            MainCommand.LS:          self.handle_ls,
            MainCommand.QUIT:        self.handle_quit,
            MainCommand.HELP:        self.handle_help,
        }

    # ------------------------------------------------------------------
    # Command parsing and dispatch
    # ------------------------------------------------------------------
    def execute_command(self, command):
        if not command:
            return "Command not recognized"
        cmd, args = self.parse_command(command)
        if cmd is None:
            return f"Command not recognized: '{command}'"
        handler = self.handlers.get(cmd)
        if not handler:
            return f"Command '{cmd.value}' not yet implemented."
        return handler(args)

    def parse_command(self, user_input):
        parts = user_input.strip().split()
        if not parts:
            return None, []
        cmd_str = parts[0].lower()
        args = parts[1:]
        try:
            cmd = MainCommand(cmd_str)
        except ValueError:
            return None, args
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
                    print("Command not recognized")
                    continue
                handler = self.handlers.get(cmd)
                if not handler:
                    print(f"Command '{cmd.value}' not yet implemented.")
                    continue
                result = handler(args)
                if result:
                    print(result)
            except KeyboardInterrupt:
                print("\nUse 'q' to quit.")
            except Exception as e:
                print(f"Error: {e}")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------
    def handle_create(self, args):
        self._ensure_thread_state()
        if len(args) < 1:
            return "Usage: create <filename>"
        fname = args[0]
        if self.fs.file_exists(fname):
            return f"File '{fname}' already exists."
        self.fs.create_file(fname, self.thread_local.cwd)
        return f"Successfully created file: {fname}"

    def handle_delete(self, args):
        self._ensure_thread_state()
        if len(args) < 1:
            return "Usage: delete <filename>"
        fname = args[0]
        if not self.fs.delete_file(fname, self.thread_local.cwd):
            return f"File '{fname}' could not be deleted."
        return f"File '{fname}' has been deleted."

    def handle_mkdir(self, args):
        self._ensure_thread_state()
        if len(args) < 1:
            return "Usage: mkdir <dirname>"
        self.fs.create_folder(args[0], self.thread_local.cwd)
        return f"Directory '{args[0]}' created in '{self.thread_local.cwd}'."

    def handle_chdir(self, args):
        self._ensure_thread_state()
        if len(args) < 1:
            return "Usage: chdir <dirname>"
        target = args[0]
        if target == "..":
            if self.thread_local.cwd != "/":
                self.thread_local.cwd = "/".join(
                    self.thread_local.cwd.rstrip("/").split("/")[:-1]
                ) or "/"
            return f"Changed directory to: {self.thread_local.cwd}"
        if not self.fs.folder_exists(target, self.thread_local.cwd):
            return f"Directory '{target}' not found in '{self.thread_local.cwd}'."
        self.thread_local.cwd = self.thread_local.cwd.rstrip("/") + "/" + target
        return f"Changed directory to: {self.thread_local.cwd}"

    def handle_move(self, args):
        self._ensure_thread_state()
        if len(args) < 2:
            return "Usage: move <source> <target_folder>"
        src, tgt_folder = args[0], args[1]
        if not self.fs.file_exists(src):
            return f"Source file '{src}' not found."
        if not self.fs.folder_exists(tgt_folder, self.thread_local.cwd):
            return f"Target folder '{tgt_folder}' not found."
        self.fs.move_file_to_directory(src, self.thread_local.cwd, tgt_folder)
        return f"Moved '{src}' to '{tgt_folder}'."

    def handle_open(self, args):
        self._ensure_thread_state()
        if len(args) < 2:
            return "Usage: open <mode> <filename> [extra args]"

        mode_str = args[0]
        filename = args[1]
        extra    = args[2:]

        write_modes = {'write', 'write_at', 'move_within', 'truncate'}
        fs_mode = 'write' if mode_str in write_modes else 'read'

        if self.thread_local.opened_file is not None:
            if self.thread_local.opened_file.name != filename:
                return f"Error: File '{self.thread_local.opened_file.name}' is already open. Close it first."
            # same file — skip reopening
        else:
            if not self.fs.file_exists(filename):
                return f"File '{filename}' not found."
            file_obj = self.fs.open_file(filename, mode=fs_mode)
            if file_obj is None:
                return f"Error: Could not open file '{filename}'."
            self.thread_local.opened_file = file_obj
            self.thread_local.opened_file_mode = fs_mode

        return_text = f"File '{filename}' opened | "

        try:
            mode_enum = MainCommand(mode_str)
            
            if mode_enum == MainCommand.READ:
                return_text += self.handle_read(extra)
            elif mode_enum == MainCommand.WRITE:
                return_text += self.handle_write(extra)
            elif mode_enum == MainCommand.WRITE_AT:
                return_text += self.handle_write_at(extra)
            elif mode_enum == MainCommand.MOVE_WITHIN:
                return_text += self.handle_move_within(extra)
            elif mode_enum == MainCommand.TRUNCATE:
                return_text += self.handle_truncate(extra)
            else:
                return_text += f"Mode '{mode_str}' is not supported with open."

            return return_text
            
        except ValueError:
            return return_text + f"Invalid mode '{mode_str}'."
                
        finally:
            #closes file automatically
            if self.thread_local.opened_file:
                name = self.thread_local.opened_file.name
                mode = getattr(self.thread_local, 'opened_file_mode', 'read')
                self._close_file(name, mode)


    def handle_write(self, args):
        self._ensure_thread_state()
        if self.thread_local.opened_file is None:
            return "No file currently open."
        text = self._extract_text(args)
        self.thread_local.opened_file.write(text, mode='append')
        self.fs.write_file(self.thread_local.opened_file)
        return f"Wrote to '{self.thread_local.opened_file.name}' successfully."

    def handle_read(self, args):
        self._ensure_thread_state()
        if self.thread_local.opened_file is None:
            return "No file currently open."
        start = int(args[0]) if len(args) > 0 else 0
        size  = int(args[1]) if len(args) > 1 else None
        content = self.thread_local.opened_file.read(start, size)
        if not content:
            return f"File '{self.thread_local.opened_file.name}' is empty."
        return content

    def handle_write_at(self, args):
        self._ensure_thread_state()
        if self.thread_local.opened_file is None:
            return "No file currently open."
        if len(args) < 2:
            return "Usage: open write_at <filename> <position> 'text'"
        try:
            position = int(args[0])
        except ValueError:
            return "Position must be an integer."
        text = self._extract_text(args[1:])
        self.thread_local.opened_file.write_at(position, text)
        self.fs.write_file(self.thread_local.opened_file)
        return f"Wrote at position {position} in '{self.thread_local.opened_file.name}'."

    def handle_move_within(self, args):
        self._ensure_thread_state()
        if self.thread_local.opened_file is None:
            return "No file currently open."
        if len(args) < 3:
            return "Usage: open move_within <filename> <start> <size> <target>"
        try:
            start  = int(args[0])
            size   = int(args[1])
            target = int(args[2])
        except ValueError:
            return "start, size, and target must be integers."
        file_size = len(self.thread_local.opened_file.content)
        if target > file_size:
            return f"Error: target {target} exceeds file size {file_size}."
        self.fs.move_within_file(self.thread_local.opened_file, start, size, target)
        return f"Moved {size} bytes from {start} to {target} in '{self.thread_local.opened_file.name}'."

    def handle_truncate(self, args):
        self._ensure_thread_state()
        if self.thread_local.opened_file is None:
            return "No file currently open."
        if len(args) < 1:
            return "Usage: open truncate <filename> <max_size>"
        try:
            max_size = int(args[0])
        except ValueError:
            return "max_size must be an integer."
        if max_size < 0:
            return "max_size must be non-negative."
        
        curr_file = self.thread_local.opened_file
        # if truncate operation is successful
        if self.fs.truncate_file(curr_file, max_size):
            return f"Truncated '{curr_file.name}' to {max_size} bytes."
        # truncate exceeds file size
        return f"Error Filesize exceeded: {curr_file.name} cannot be truncated by {max_size} units"


    def handle_close(self, args):
        self._ensure_thread_state()
        if self.thread_local.opened_file is None:
            return "No file currently open."
        name = self.thread_local.opened_file.name
        mode = getattr(self.thread_local, 'opened_file_mode', 'read')
        self._close_file(name, mode)
        
    
    def _close_file(self, name, mode):
        self.thread_local.opened_file.close()
        self.fs.close_file(name, mode)
        self.thread_local.opened_file = None
        self.thread_local.opened_file_mode = None
        return f"[ '{name}' closed ]"


    def handle_mmap(self, args):
        return self.fs.show_memory_map()


    def handle_cwd(self, args):
        self._ensure_thread_state()
        return self.thread_local.cwd

    def handle_ls(self, args):
        self._ensure_thread_state()
        entries = self.fs.list_contents(self.thread_local.cwd)
        if not entries:
            return "(empty)"
        lines = []
        for id in entries:
            entry = next((d for d in self.fs.header['directories'] if d['id'] == id), None)
            if entry is None:
                continue
            if entry['type'] == 'dir':
                size = self.fs.get_dir_size_from_id(id)
                lines.append(f"[DIR]  {entry['name']} ({size} bytes)")
            else:
                filename = entry['name']
                file_meta = self.fs.header['files'].get(filename, {})
                size = file_meta.get('size', 0)
                lines.append(f"[FILE] {filename} ({size} bytes)")
        return "\n".join(lines)

    def handle_man(self, args):
        return """
Available commands:
  create <filename>                                          - Create an empty file in current dir
  delete <filename>                                          - Delete a file
  mkdir <dirname>                                            - Create a directory in current dir
  chdir <dirname>                                            - Change directory
  chdir ..                                                   - Move up to parent directory
  move <src> <dst>                                           - Move a file to another directory
  --------------------------------------------------------------------------------------------------
  open read <filename> [start] [size]                        - Read from a file
  open write <filename> 'text'                               - Append text to a file
  open write_at <filename> <pos> 'text'                      - Overwrite at specific position
  open move_within <filename> <start> <size> <target>        - Move block within file
  open truncate <filename> <max_size>                        - Truncate file to given size
  --------------------------------------------------------------------------------------------------
  close <filename>                                           - Close an open file
  mmap                                                       - Show memory map
  cwd                                                        - Show current working directory
  ls                                                         - List files and directories
  man                                                        - Show this manual
  q                                                          - Quit
"""

    def handle_quit(self, args):
        self.running = False
        return "Quitting."


    def handle_help(self, args):
        return self.handle_man(args)


    def _extract_text(self, args):
        if not args:
            return ""
        if args[0].startswith("'") and args[-1].endswith("'"):
            return ' '.join(args)[1:-1]
        return ' '.join(args)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <num_of_threads>")
        return
    k = int(sys.argv[1])
    shell = Shell(k)
    shell.run()


if __name__ == "__main__":
    main()
