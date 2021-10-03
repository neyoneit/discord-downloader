import unittest
from asyncio import run
from os import path
from os.path import dirname

from discord_downloader.demo_uploaders import YoutubeUploader, VideoUploadException


class YoutubeUploaderTestCase(unittest.TestCase):

    def _mock_test(self, return_code: int, stderr_file: str, stdout_file: str):
        dn = path.join(dirname(__file__), 'youtube-uploader-test')
        return YoutubeUploader(
            youtube_uploader_executable=path.join(dn, 'yt-uploader-mock.sh'),
            youtube_uploader_params=[str(return_code), path.join(dn, stdout_file), path.join(dn, stderr_file)]
        )

    def test_successful_upload(self):
        up = self._mock_test(0, stderr_file='success-stderr.txt', stdout_file='success-stdout.txt')
        self.assertEqual(run(up.upload('hello', 'world', 'fakefile')), 'https://youtu.be/RAZfS6r-LLM')

    def test_failed_upload(self):
        up = self._mock_test(3, stderr_file='fail-stderr.txt', stdout_file='fail-stdout.txt')
        try:
            run(up.upload('title', 'descr', 'fajl'))
            self.fail('upload did not raise an excpetion')
        except VideoUploadException as e:
            self.assertEqual(
                e.message['error']['message'],
                "The request cannot be completed because you have exceeded your "
                "\u003ca href=\"/youtube/v3/getting-started#quota\"\u003equota\u003c/a\u003e."
            )
