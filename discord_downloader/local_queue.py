from typing import Awaitable
from typing import List, Callable

from discord_downloader.demo_uploaders import DemoUploader, QueueFullException
from discord_downloader.persistent_state import StoredState


class LocallyQueuedUploader:

    def __init__(self, uploader: DemoUploader, state: StoredState):
        self._uploader = uploader
        self._state = state

    async def upload(self, url: str, resolution: int, title: str, description: str) -> None:
        try:
            if self._queue_full:
                raise QueueFullException()
            await self._bare_upload(url=url, resolution=resolution, title=title, description=description)
            self._state.flush()
        except QueueFullException:
            self._queue_full = True
            self._local_queue_add(url, resolution, title, description)

    def _local_queue_add(self, url: str, resolution: int, title: str, description: str):
        self._local_queue.append([url, resolution, title, description])
        self._state.flush()

    async def check_for_done(self, done_callback: Callable[[str], Awaitable[None]],
                             failed_callback: Callable[[int, Exception], Awaitable[None]]):
        for id in self._uploaded_queue():
            try:
                status = await self._uploader.check_status(id)
                if status is not None:
                    await done_callback(status)
                    self._uploaded_queue().remove(id)
                    self._state.flush()
            except Exception as e:
                await failed_callback(id, e)
                self._uploaded_queue().remove(id)
                self._state.flush()

    async def retry_uploads(self):
        self._queue_full = False
        try:
            while len(self._local_queue) > 0:
                [url, resolution, title, description] = self._local_queue[0]
                await self._bare_upload(url=url, resolution=resolution, title=title, description=description)
                self._local_queue.pop(0)
                self._state.flush()
        except QueueFullException:
            pass

    @property
    def _queue_full(self) -> bool:
        return self._state.value["queue_full"]

    @_queue_full.setter
    def _queue_full(self, value: bool):
        self._state.value["queue_full"] = value

    def _uploaded_queue(self) -> List[int]:
        return self._state.value['uploaded_queue']

    @property
    def _local_queue(self) -> List[list]:
        return self._state.value['local_queue']

    @staticmethod
    def get_default_state():
        return {"uploaded_queue": [], "local_queue": [], "queue_full": False}

    async def _bare_upload(self, url, resolution, title, description):
        res = await self._uploader.upload(url=url, resolution=resolution, title=title, description=description)
        self._uploaded_queue().append(res.render_id)
