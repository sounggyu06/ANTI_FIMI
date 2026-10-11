import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import run_connected as connected


class ConnectedTests(unittest.TestCase):
    def test_port_collision_is_reported_without_stopping_owner(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(connected.LaunchError):
                connected.require_free_port(port)
            self.assertEqual(listener.getsockname()[1], port)

    def test_paths_follow_moved_parent_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            d4d = Path(directory) / 'D4D copied'
            (d4d / 'ANTI_FIMI').mkdir(parents=True)
            (d4d / 'ANTI_FIMI/server.py').touch()
            (d4d / 'fimi-dashboard/dist').mkdir(parents=True)
            (d4d / 'fimi-dashboard/dist/index.html').touch()
            with patch.object(connected, 'ROOT', d4d / 'veil-crawler'):
                folder, engine, db = connected.connected_paths(None)
            self.assertEqual(folder, d4d.resolve())
            self.assertEqual(engine, d4d.resolve() / 'ANTI_FIMI/server.py')
            self.assertEqual(db, d4d.resolve() / 'ANTI_FIMI_DEMO_DATA/ANTI_FIMI_veil_live.sqlite3')

    def test_stop_request_targets_matching_instance_only(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = Path(directory) / 'connected.stop'
            stop.write_text(json.dumps({'token': 'previous'}))
            with patch.object(connected, 'STOP', stop):
                self.assertFalse(connected.stop_requested('current'))
                self.assertTrue(connected.stop_requested('previous'))

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Object lifecycle test')
    def test_job_ends_owned_grandchild_and_preserves_unrelated_process(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        owner = connected.ChildProcesses()
        grandchild_handle = None
        try:
            with tempfile.TemporaryDirectory() as directory:
                pid_file = Path(directory) / 'grandchild.pid'
                script = ("import subprocess,time; from pathlib import Path; time.sleep(0.2); "
                          f"child=subprocess.Popen([{sys.executable!r},'-c','import time; time.sleep(60)']); "
                          f"Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(60)")
                with (Path(directory) / 'child.log').open('w') as log:
                    child = owner.start([sys.executable, '-c', script], directory, log)
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(pid_file.exists())
                    grandchild_handle = kernel.OpenProcess(0x100000, False, int(pid_file.read_text()))
                    self.assertTrue(grandchild_handle)
                    owner.close()
                    self.assertIsNotNone(child.poll())
                    self.assertEqual(kernel.WaitForSingleObject(grandchild_handle, 5000), 0)
                    self.assertIsNone(unrelated.poll())
        finally:
            owner.close()
            if grandchild_handle:
                kernel.CloseHandle(grandchild_handle)
            unrelated.terminate()
            unrelated.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
