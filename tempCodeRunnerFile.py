import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fs_core import FileSystem
from file_object import FileObject
from shell import Shell


class TestFilesystem(unittest.TestCase):

    def setUp(self):
        # Fresh filesystem for every test
        if os.path.exists('filesystem.dat'):
            os.remove('filesystem.dat')
        self.fs = FileSystem()
        self.shell = Shell()
        self.shell.fs = self.fs  # share same fs instance

    def tearDown(self):
        if os.path.exists('filesystem.dat'):
            os.remove('filesystem.dat')

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------
    def test_create_file(self):
        self.fs.create_file('hello.txt')
        self.assertIn('hello.txt', self.fs.header['files'])
        self.assertEqual(self.fs.header['files']['hello.txt']['size'], 0)

    def test_create_duplicate_raises(self):
        self.fs.create_file('dup.txt')
        # shell should reject duplicate
        self.shell.handle_create(['dup.txt'])
        # still only one entry
        self.assertEqual(list(self.fs.header['files'].keys()).count('dup.txt'), 1)

    # ------------------------------------------------------------------
    # write / read
    # ------------------------------------------------------------------
    def test_write_and_read_back(self):
        self.fs.create_file('a.txt')
        fo = self.fs.open_file('a.txt')
        fo.write('Hello, world!', mode='append')
        self.fs.write_file(fo)

        result = self.fs.open_file('a.txt')
        self.assertEqual(result.content, 'Hello, world!')

    def test_write_large_content_segments(self):
        # content > 512 bytes should produce multiple segments
        self.fs.create_file('big.txt')
        fo = self.fs.open_file('big.txt')
        fo.write('X' * 1200, mode='append')
        self.fs.write_file(fo)

        meta = self.fs.header['files']['big.txt']
        self.assertGreater(len(meta['segments']), 1)

        result = self.fs.open_file('big.txt')
        self.assertEqual(result.content, 'X' * 1200)

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------
    def test_delete_file(self):
        self.fs.create_file('del.txt')
        fo = self.fs.open_file('del.txt')
        fo.write('some data', mode='append')
        self.fs.write_file(fo)

        ok = self.fs._delete_file('del.txt')
        self.assertTrue(ok)
        self.assertNotIn('del.txt', self.fs.header['files'])

    def test_delete_frees_dead_space(self):
        self.fs.create_file('d2.txt')
        fo = self.fs.open_file('d2.txt')
        fo.write('A' * 600, mode='append')
        self.fs.write_file(fo)

        before = len(self.fs.header['dead_space'])
        self.fs._delete_file('d2.txt')
        after = len(self.fs.header['dead_space'])
        self.assertGreater(after, before)

    def test_delete_nonexistent_returns_false(self):
        result = self.fs._delete_file('ghost.txt')
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # write_at
    # ------------------------------------------------------------------
    def test_write_at(self):
        self.fs.create_file('w.txt')
        fo = self.fs.open_file('w.txt')
        fo.write('Hello World', mode='append')
        self.fs.write_file(fo)

        fo = self.fs.open_file('w.txt')
        fo.write_at(6, 'Python')
        self.fs.write_file(fo)

        result = self.fs.open_file('w.txt')
        self.assertEqual(result.content, 'Hello Python')

    # ------------------------------------------------------------------
    # move_within_file
    # ------------------------------------------------------------------
    def test_move_within_file_object(self):
        fo = FileObject('test.txt', 'ABCDE')
        fo.move_within_file(0, 2, 4)   # move 'AB' to position 4 -> 'CDEAB'
        # After removing 'AB' string is 'CDE', target 4 > start 0 so adjusted to 4-2=2
        # insert at 2 -> 'CD' + 'AB' + 'E' = 'CDABE'
        self.assertEqual(fo.content, 'CDABE')

    def test_move_within_via_fs(self):
        self.fs.create_file('mv.txt')
        fo = self.fs.open_file('mv.txt')
        fo.write('ABCDE', mode='append')
        self.fs.write_file(fo)

        fo = self.fs.open_file('mv.txt')
        self.fs.move_within_file(fo, 0, 2, 4)

        result = self.fs.open_file('mv.txt')
        self.assertEqual(result.content, 'CDABE')

    def test_shell_move_within_target_too_large(self):
        self.fs.create_file('ov.txt')
        fo = self.fs.open_file('ov.txt')
        fo.write('Hello', mode='append')
        self.fs.write_file(fo)

        self.shell.opened_file = self.fs.open_file('ov.txt')
        # target=999 > len('Hello')=5 → should print error and not crash
        self.shell.handle_move_within(['0', '2', '999'])
        # content should be unchanged
        result = self.fs.open_file('ov.txt')
        self.assertEqual(result.content, 'Hello')

    # ------------------------------------------------------------------
    # truncate
    # ------------------------------------------------------------------
    def test_truncate_file_object(self):
        fo = FileObject('t.txt', 'Hello, world!')
        fo.truncate(5)
        self.assertEqual(fo.content, 'Hello')

    def test_truncate_via_shell(self):
        self.fs.create_file('tr.txt')
        fo = self.fs.open_file('tr.txt')
        fo.write('Hello, world!', mode='append')
        self.fs.write_file(fo)

        self.shell.opened_file = self.fs.open_file('tr.txt')
        self.shell.handle_truncate(['5'])

        result = self.fs.open_file('tr.txt')
        self.assertEqual(result.content, 'Hello')

    # ------------------------------------------------------------------
    # dead space reuse
    # ------------------------------------------------------------------
    def test_dead_space_reused_on_new_write(self):
        self.fs.create_file('reuse.txt')
        fo = self.fs.open_file('reuse.txt')
        fo.write('A' * 600, mode='append')
        self.fs.write_file(fo)
        self.fs._delete_file('reuse.txt')

        dead_before = sum(b['size'] for b in self.fs.header['dead_space'])

        self.fs.create_file('new.txt')
        fo2 = self.fs.open_file('new.txt')
        fo2.write('B' * 500, mode='append')
        self.fs.write_file(fo2)

        dead_after = sum(b['size'] for b in self.fs.header['dead_space'])
        self.assertLess(dead_after, dead_before)

    # ------------------------------------------------------------------
    # header stays 64 KB
    # ------------------------------------------------------------------
    def test_header_always_64kb(self):
        self.fs.create_file('size_check.txt')
        fo = self.fs.open_file('size_check.txt')
        fo.write('Some content', mode='append')
        self.fs.write_file(fo)

        with open('filesystem.dat', 'rb') as f:
            header_bytes = f.read(65536)
        self.assertEqual(len(header_bytes), 65536)

    # ------------------------------------------------------------------
    # list files
    # ------------------------------------------------------------------
    def test_list_files(self):
        self.fs.create_file('f1.txt')
        self.fs.create_file('f2.txt')
        files = self.fs.list_files()
        self.assertIn('f1.txt', files)
        self.assertIn('f2.txt', files)


if __name__ == '__main__':
    unittest.main(verbosity=2)