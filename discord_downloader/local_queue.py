from abc import abstractmethod, ABC
from typing import Awaitable, Any, Union
from typing import List, Callable

from discord_downloader.demo_uploaders import DemoUploader, QueueFullException
from discord_downloader.persistent_state import StoredState


class RenderingQueue(ABC):

    @abstractmethod
    async def upload(self, url: str, resolution: int, title: str, description: str, additional_data=None) -> None:
        pass

    @abstractmethod
    def needs_polling(self) -> bool:
        pass


class AutonomousRenderingQueue(RenderingQueue):

    def needs_polling(self) -> bool:
        return False

    @abstractmethod
    def add_done_callback(self, done_callback: Callable[[str, Any], Awaitable[None]]):
        pass

    @abstractmethod
    def add_fail_callback(self, failed_callback: Callable[[int, Exception, Any], Awaitable[None]]):
        pass

    @abstractmethod
    async def run(self):
        pass


class PollingRenderingQueue(RenderingQueue):

    def needs_polling(self) -> bool:
        return True

    @abstractmethod
    async def check_for_done(self, done_callback: Callable[[str, Any], Awaitable[None]],
                             failed_callback: Callable[[int, Exception, Any], Awaitable[None]]):
        pass

    @abstractmethod
    async def retry_uploads(self):
        pass


class LocallyQueuedUploader(PollingRenderingQueue):

    def __init__(self, uploader: DemoUploader, state: StoredState):
        self._uploader = uploader
        self._state = state

    async def upload(self, url: str, resolution: int, title: str, description: str, additional_data = None) -> None:
        try:
            if self._queue_full:
                raise QueueFullException()
            await self._bare_upload(url=url, resolution=resolution, title=title, description=description,
                                    additional_data=additional_data)
            self._state.flush()
        except QueueFullException:
            self._queue_full = True
            self._local_queue_add(url, resolution, title, description, additional_data)

    def _local_queue_add(self, url: str, resolution: int, title: str, description: str, additional_data):
        self._local_queue.append([url, resolution, title, description, additional_data])
        self._state.flush()

    async def check_for_done(self, done_callback: Callable[[str, Any], Awaitable[None]],
                             failed_callback: Callable[[int, Exception, Any], Awaitable[None]]):
        for item in self._uploaded_queue:
            if isinstance(item, list):
                [id, additional_data] = item
            else:
                id = item
                additional_data = None
            try:
                status = await self._uploader.check_status(id)
                if status is not None:
                    await done_callback(status, additional_data)
                    self._uploaded_queue.remove(item)
                    self._state.flush()
            except Exception as e:
                await failed_callback(id, e, additional_data)
                self._uploaded_queue.remove(item)
                self._state.flush()

    async def retry_uploads(self):
        self._queue_full = False
        try:
            while len(self._local_queue) > 0:
                queue_top = self._local_queue[0]
                if len(queue_top) == 4:
                    # legacy
                    [url, resolution, title, description] = queue_top
                    additional_data = None
                elif len(queue_top) == 5:
                    [url, resolution, title, description, additional_data] = queue_top
                else:
                    raise AssertionError(f"Unexpected data in {queue_top}")
                await self._bare_upload(url=url, resolution=resolution, title=title, description=description,
                                        additional_data=additional_data)
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

    @property
    def _uploaded_queue(self) -> List[Union[List, int]]:
        return self._state.value['uploaded_queue']

    @property
    def _local_queue(self) -> List[list]:
        return self._state.value['local_queue']

    @staticmethod
    def get_default_state():
        return {"uploaded_queue": [], "local_queue": [], "queue_full": False}

    async def _bare_upload(self, url, resolution, title, description, additional_data):
        res = await self._uploader.upload(url=url, resolution=resolution, title=title, description=description)
        self._uploaded_queue.append([res.render_id, additional_data])
