import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import launcher_utils as utils


class LauncherTests(unittest.TestCase):
    def test_active_server_requires_matching_session(self):
        with tempfile.TemporaryDirectory() as folder:
            metadata=Path(folder)/"web-instance.json"
            metadata.write_text(json.dumps({"port":5173,"session_id":"expected","url":"https://elsewhere.example/",
                                            'project_root':str(utils.ROOT.resolve())}))
            with patch.object(utils,"WEB_INFO",metadata), patch.object(utils,"fetch_json",return_value={"app":"veil-social","sessionId":"expected"}):
                self.assertEqual(utils.active_web()["url"],"http://127.0.0.1:5173/")
            with patch.object(utils,"WEB_INFO",metadata), patch.object(utils,"fetch_json",return_value={"app":"veil-social","sessionId":"another"}):
                self.assertIsNone(utils.active_web())

    def test_moved_project_does_not_reuse_another_folders_site(self):
        with tempfile.TemporaryDirectory() as folder:
            metadata=Path(folder)/"web-instance.json"
            metadata.write_text(json.dumps({'port':5180,'session_id':'previous',
                                            'project_root':str(Path(folder)/'old-project')}))
            with patch.object(utils,'WEB_INFO',metadata), patch.object(utils,'fetch_json') as fetch:
                self.assertIsNone(utils.active_web())
                fetch.assert_not_called()

    def test_no_web_is_explained_before_crawler_setup_or_output_change(self):
        import run_crawler
        with patch.object(run_crawler,"launch_lock") as lock, patch.object(run_crawler,"active_web",return_value=None), patch.object(run_crawler,"ensure_python") as prepare:
            lock.return_value.__enter__.return_value=None
            self.assertEqual(run_crawler.main(),1)
            prepare.assert_not_called()

    def test_duplicate_launch_lock_does_not_allow_parallel_writers(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(utils,"RUNTIME",Path(folder)):
            with utils.launch_lock("crawler"):
                with self.assertRaises(utils.LaunchError):
                    with utils.launch_lock("crawler"):
                        self.fail("second writer entered")
            # Metadata can remain; ownership belongs to the OS file handle, not a stale PID.
            with utils.launch_lock("crawler"):
                pass

    def test_stale_pid_metadata_does_not_block_or_signal_process(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(utils,"RUNTIME",Path(folder)):
            (Path(folder)/"web.lock").write_text(json.dumps({"pid":os.getpid()}))
            with patch.object(os,"kill",side_effect=AssertionError("must not signal a process")):
                with utils.launch_lock("web"):
                    pass

    def test_lock_is_released_after_abrupt_owner_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            script = ("from pathlib import Path; import os; import launcher_utils as u; "
                      f"u.RUNTIME=Path({folder!r}); "
                      "lock=u.launch_lock('crash'); lock.__enter__(); os._exit(0)")
            subprocess.run([sys.executable,"-c",script],cwd=utils.ROOT,check=True,timeout=10)
            with patch.object(utils,"RUNTIME",Path(folder)):
                with utils.launch_lock("crash"):
                    pass

    def test_live_owner_blocks_another_process_without_signalling(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(utils,"RUNTIME",Path(folder)):
            with utils.launch_lock("cross-process"):
                script = ("from pathlib import Path; import launcher_utils as u; "
                          f"u.RUNTIME=Path({folder!r}); "
                          "lock=u.launch_lock('cross-process'); lock.__enter__()")
                result=subprocess.run([sys.executable,"-X","utf8","-c",script],cwd=utils.ROOT,
                                      capture_output=True,text=True,encoding="utf-8",timeout=10)
                self.assertNotEqual(result.returncode,0)
                self.assertIn("LaunchError",result.stderr)


if __name__=="__main__":
    unittest.main()
