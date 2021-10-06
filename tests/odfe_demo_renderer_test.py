import os
import shutil
import unittest
from asyncio import run
from os import path, mkdir
from os.path import dirname
from tempfile import TemporaryDirectory

from discord_downloader.demo_uploaders import OdfeDemoRenderer


class OdfeDemoRendererTestCase(unittest.TestCase):

    def test_run(self):
        dn = path.join(dirname(__file__), 'odfe-demo-renderer-test')
        with TemporaryDirectory() as tmpdir:
            config_dir = path.join(tmpdir, 'config')
            demo_dir = path.join(tmpdir, 'demo')
            video_dir = path.join(tmpdir, 'video')
            executable_dir = path.join(tmpdir, 'executable')
            fake_odfe_file = path.join(executable_dir, 'fake-odfe.sh')
            tmpdirs = [config_dir, demo_dir, video_dir, executable_dir]
            for dir in tmpdirs:
                mkdir(dir)
            shutil.copy(path.join(dn, 'fake-odfe.sh'), fake_odfe_file)
            renderer = OdfeDemoRenderer(
                odfe_dir=dn,
                odfe_executable=fake_odfe_file,
                config_dir=config_dir,
                demo_dir=demo_dir,
                video_dir=video_dir,
                defrag_config="// prefix"
            )
            res = run(renderer.render('sdf.dm_62', b''))
            os.remove(fake_odfe_file)
            os.remove(res)
            for dir in tmpdirs:
                self.assertEqual(os.listdir(dir), [])
