import asyncio
import itertools
import os
import tempfile
import unittest
from typing import Optional
from unittest.mock import MagicMock, call

from discord_downloader.demo_uploaders import NopUploader, UploadResult, DemoUploader, QueueFullException
from discord_downloader.local_queue import LocallyQueuedUploader
from discord_downloader.persistent_state import StoredState


async def async_result(result):
    return result


def sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def raise_it(e):
    raise e


class LocallyQueuedUploaderTestCase(unittest.TestCase):

    fake_uploader: Optional[DemoUploader]
    lqu: Optional[LocallyQueuedUploader]

    def __init__(self, methodName: str = ...):
        super().__init__(methodName)

    def raise_queue_full(self, **kwargs):
        raise QueueFullException()

    def test_successful_upload(self):
        self.upload_single()
        self.check_single_unfinished_upload()
        self.check_single_finished_upload()
        self.check_no_finished_upload()

    def test_successful_upload_crossinstance_1(self):
        self.upload_single()
        self.simulate_restart()
        self.check_single_unfinished_upload()
        self.simulate_restart()
        self.check_single_finished_upload()
        self.check_no_finished_upload()

    def test_successful_upload_crossinstance_2(self):
        self.upload_single()
        self.check_single_unfinished_upload()
        self.simulate_restart()
        self.check_single_finished_upload()
        self.check_no_finished_upload()

    def test_successful_upload_crossinstance_3(self):
        self.upload_single()
        self.check_single_unfinished_upload()
        self.simulate_restart()
        self.check_single_finished_upload()
        self.check_no_finished_upload()

    def test_successful_upload_crossinstance_4(self):
        self.upload_single()
        self.check_single_unfinished_upload()
        self.check_single_finished_upload()
        self.simulate_restart()
        self.check_no_finished_upload()

    def upload_single(self, id=42863, url='a', resolution=1, title='asdfsd', description='sdfdsf', queue_full=False,
                      queue_already_full=False):
        self.fake_uploader.upload = (MagicMock(side_effect=self.raise_queue_full) if queue_full else
                                     MagicMock(return_value=async_result(UploadResult(True, id))))

        sync(self.lqu.upload(url, resolution, title, description))

        if queue_already_full:
            self.fake_uploader.upload.assert_not_called()
        else:
            self.fake_uploader.upload.assert_called_once_with(
                url=url, resolution=resolution, title=title, description=description
            )

    def check_single_unfinished_upload(self):
        self.fake_uploader.check_status = MagicMock(return_value=async_result(None))
        self.assertEqual(self.check_for_done(), [])
        self.fake_uploader.check_status.assert_called_once_with(42863)

    def check_no_finished_upload(self):
        self.fake_uploader.check_status = MagicMock(return_value=async_result(None))
        self.assertEqual(self.check_for_done(), [])
        self.fake_uploader.check_status.assert_not_called()

    def check_single_finished_upload(self):
        self.fake_uploader.check_status = MagicMock(return_value=async_result('https://www.example.com/uploaded_video'))
        self.assertEqual(self.check_for_done(), [('ok', 'https://www.example.com/uploaded_video', None)])
        self.fake_uploader.check_status.assert_called_once_with(42863)

    def throw_check_status_error(self, _):
        raise Exception('Foo error')

    def check_single_failed_upload(self):
        self.fake_uploader.check_status = MagicMock(side_effect=self.throw_check_status_error)
        self.assertEqual(str(self.check_for_done()), str([('error', 42863, Exception('Foo error'))]))
        self.fake_uploader.check_status.assert_called_once_with(42863)

    def test_full_queue(self):
        self.upload_single(id=1)
        self.upload_single(id=2)
        self.upload_single(id=3)
        self.upload_single(id=4)
        self.upload_single(id=5, queue_full=True, url='x')
        self.upload_single(id=6, queue_already_full=True, url='y')
        self.upload_single(id=7, queue_already_full=True, url='z')
        self.upload_single(id=8, queue_already_full=True, url='alpha')
        self.upload_single(id=8, queue_already_full=True, url='beta')

        self.fake_uploader.upload = MagicMock(side_effect=itertools.chain(map(lambda id: async_result(UploadResult(True, id)), [
            5, 6
        ]), map(raise_it, [QueueFullException()])))
        sync(self.lqu.retry_uploads())
        self.assertEqual(self.fake_uploader.upload.call_count, 3)  # Including QueueFullException
        self.fake_uploader.upload.assert_has_calls([
            call(url='x', resolution=1, title='asdfsd', description='sdfdsf'),
            call(url='y', resolution=1, title='asdfsd', description='sdfdsf'),
            call(url='z', resolution=1, title='asdfsd', description='sdfdsf'),
        ])

        self.fake_uploader.upload = MagicMock(side_effect=itertools.chain(map(lambda id: async_result(UploadResult(True, id)), [
            7
        ]), map(raise_it, [QueueFullException()])))
        sync(self.lqu.retry_uploads())
        self.assertEqual(self.fake_uploader.upload.call_count, 2)  # Including QueueFullException
        self.fake_uploader.upload.assert_has_calls([
            call(url='z', resolution=1, title='asdfsd', description='sdfdsf'),
            call(url='alpha', resolution=1, title='asdfsd', description='sdfdsf'),
        ])

    def test_full_queue_with_restarts(self):
        self.upload_single(id=1)
        self.simulate_restart()
        self.upload_single(id=2)
        self.simulate_restart()
        self.upload_single(id=3)
        self.simulate_restart()
        self.upload_single(id=4)
        self.simulate_restart()
        self.upload_single(id=5, queue_full=True, url='x')
        self.simulate_restart()
        self.upload_single(id=6, queue_already_full=True, url='y')
        self.simulate_restart()
        self.upload_single(id=7, queue_already_full=True, url='z')
        self.simulate_restart()
        self.upload_single(id=8, queue_already_full=True, url='alpha')
        self.simulate_restart()
        self.upload_single(id=8, queue_already_full=True, url='beta')
        self.simulate_restart()

        self.fake_uploader.upload = MagicMock(side_effect=itertools.chain(map(lambda id: async_result(UploadResult(True, id)), [
            5, 6
        ]), map(raise_it, [QueueFullException()])))
        sync(self.lqu.retry_uploads())
        self.assertEqual(self.fake_uploader.upload.call_count, 3)  # Including QueueFullException
        self.fake_uploader.upload.assert_has_calls([
            call(url='x', resolution=1, title='asdfsd', description='sdfdsf'),
            call(url='y', resolution=1, title='asdfsd', description='sdfdsf'),
            call(url='z', resolution=1, title='asdfsd', description='sdfdsf'),
        ])
        self.simulate_restart()

        self.fake_uploader.upload = MagicMock(side_effect=itertools.chain(map(lambda id: async_result(UploadResult(True, id)), [
            7
        ]), map(raise_it, [QueueFullException()])))
        sync(self.lqu.retry_uploads())
        self.assertEqual(self.fake_uploader.upload.call_count, 2)  # Including QueueFullException
        self.fake_uploader.upload.assert_has_calls([
            call(url='z', resolution=1, title='asdfsd', description='sdfdsf'),
            call(url='alpha', resolution=1, title='asdfsd', description='sdfdsf'),
        ])

    def test_failed_upload(self):
        self.upload_single()
        self.check_single_unfinished_upload()
        self.check_single_failed_upload()
        self.check_no_finished_upload()

    def test_failed_upload_with_restarts(self):
        self.upload_single()
        self.simulate_restart()
        self.check_single_unfinished_upload()
        self.simulate_restart()
        self.check_single_failed_upload()
        self.simulate_restart()
        self.check_no_finished_upload()

    # def test_transient_error(self):
    #     self.upload_single()
    #     self.check_single_unfinished_upload()
    #     self.check_single_transient_error()
    #     self.check_single_unfinished_upload()
    #
    # def test_transient_error_with_restarts(self):
    #     self.upload_single()
    #     self.simulate_restart()
    #     self.check_single_unfinished_upload()
    #     self.simulate_restart()
    #     self.check_single_transient_error()
    #     self.simulate_restart()
    #     self.check_single_unfinished_upload()

    def setUp(self) -> None:
        self.tmp_file = tempfile.mktemp()
        self.simulate_start()
        super().setUp()

    def simulate_start(self):
        self.state = StoredState(self.tmp_file, LocallyQueuedUploader.get_default_state())
        self.fake_uploader = NopUploader()
        self.lqu = LocallyQueuedUploader(self.fake_uploader, self.state)

    def tearDown(self) -> None:
        super().tearDown()
        os.unlink(self.tmp_file)
        self.tmp_file = None
        self.simulate_shutdown()

    def simulate_shutdown(self):
        self.state = None
        self.fake_uploader = None
        self.lqu = None

    def check_for_done(self):
        events = []

        async def done_callback(url, additional_data):
            events.append(('ok', url, additional_data))

        async def failed_callback(id, e, data):
            events.append(('error', id, e))

        sync(self.lqu.check_for_done(done_callback, failed_callback))
        return events

    def simulate_restart(self):
        self.simulate_shutdown()
        self.simulate_start()


if __name__ == '__main__':
    unittest.main()
