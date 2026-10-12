"""打包相关的单元测试：python -m unittest test_packaging"""

import os
import sys
import tempfile
import unittest
from unittest import mock

import random_draw
from draw_core import get_config_path


class TestAutostartTarget(unittest.TestCase):
    """开机自启脚本必须指向真实存在的程序，而不是一次性解压目录。"""

    def test_source_run_points_at_this_file(self):
        self.assertEqual(
            random_draw.autostart_target(),
            os.path.abspath(random_draw.__file__),
        )

    def test_frozen_build_points_at_executable(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(random_draw.autostart_target(), sys.executable)

    def test_frozen_build_does_not_use_bundle_dir(self):
        """回归：曾经写成 "sys.executable __file__"，__file__ 退出后即被删除。"""
        bundle_dir = os.path.abspath(random_draw.__file__)
        with mock.patch.object(sys, "frozen", True, create=True):
            target = random_draw.autostart_target()
        self.assertNotIn(bundle_dir, target)
        self.assertEqual(target, sys.executable)


class TestAutostartBatch(unittest.TestCase):
    """直接检查写入的批处理内容。"""

    def _write_batch(self, frozen):
        home = tempfile.mkdtemp()
        with mock.patch.object(random_draw.sys, "platform", "win32"), \
             mock.patch.object(random_draw.os.path, "expanduser", return_value=home), \
             mock.patch.object(sys, "frozen", frozen, create=True), \
             mock.patch.object(sys, "executable", r"C:\Tools\app.exe"):
            self.assertTrue(random_draw.set_autostart(True))
            path = random_draw.get_autostart_path()
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_frozen_batch_launches_only_the_exe(self):
        """打包后批处理里不能出现一次性解压目录。"""
        content = self._write_batch(frozen=True)
        self.assertEqual(content, '@echo off\n"C:\\Tools\\app.exe"\n')

    def test_frozen_batch_has_no_second_argument(self):
        """回归：旧写法是 "sys.executable __file__"，多出的参数指向已删目录。"""
        content = self._write_batch(frozen=True)
        line = content.splitlines()[1].strip()
        self.assertEqual(line.count('"'), 2, f"应只有一组引号：{line}")

    def test_batch_removal(self):
        home = tempfile.mkdtemp()
        with mock.patch.object(random_draw.sys, "platform", "win32"), \
             mock.patch.object(random_draw.os.path, "expanduser", return_value=home), \
             mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", r"C:\Tools\app.exe"):
            random_draw.set_autostart(True)
            path = random_draw.get_autostart_path()
            self.assertTrue(os.path.exists(path))
            self.assertTrue(random_draw.set_autostart(False))
            self.assertFalse(os.path.exists(path))


class TestConfigPathUnderFrozen(unittest.TestCase):
    """config.json 必须落在 exe 旁边，而不是临时解压目录。"""

    def test_source_run_uses_script_dir(self):
        self.assertEqual(
            get_config_path(),
            os.path.join(os.path.dirname(os.path.abspath(random_draw.__file__)), "config.json"),
        )

    def test_frozen_uses_executable_dir(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", os.path.join(r"C:\Tools", "app.exe")):
            self.assertEqual(get_config_path(), os.path.join(r"C:\Tools", "config.json"))


if __name__ == "__main__":
    unittest.main()