import asyncio
import datetime
import traceback
from asyncio import Event, FIRST_EXCEPTION
from datetime import timedelta
from typing import List, Callable, Any, Awaitable

from aiohttp import ClientSession

from discord_downloader.demo_uploaders import DemoRenderer, RenderedDemoUploader
from discord_downloader.local_queue import AutonomousRenderingQueue
from discord_downloader.persistent_state import StoredState


async def wait_until(instant: datetime.datetime):
    MAX_SLEEP = 5.0
    while instant > datetime.datetime.now():
        diff = instant - datetime.datetime.now()
        await asyncio.sleep(min(diff.total_seconds(), MAX_SLEEP))


class LocalRenderingQueue(AutonomousRenderingQueue):

    def __init__(self, demo_renderer: DemoRenderer, rendered_demo_uploader: RenderedDemoUploader, state: StoredState,
                 delay_before_publishing: timedelta):
        self._demo_renderer = demo_renderer
        self._rendered_demo_uploader = rendered_demo_uploader
        self._delay_before_publishing = delay_before_publishing
        self._state = state
        self._done_callbacks: List[Callable[[str, Any], Awaitable[None]]] = []
        self._fail_callbacks: List[Callable[[int, Exception, Any], Awaitable[None]]] = []
        self._rendering_queue_event = Event()
        self._upload_queue_event = Event()
        self._waiting_queue_event = Event()

    @property
    def _rendering_queue(self) -> List[List]:
        return self._state.value['rendering_queue']

    @property
    def _upload_queue(self) -> List[List]:
        return self._state.value['upload_queue']

    @property
    def _waiting_queue(self) -> List[List]:
        return self._state.value['waiting_queue']

    def add_done_callback(self, done_callback: Callable[[str, Any], Awaitable[None]]):
        self._done_callbacks.append(done_callback)

    def add_fail_callback(self, failed_callback: Callable[[int, Exception, Any], Awaitable[None]]):
        self._fail_callbacks.append(failed_callback)

    async def upload(self, url: str, resolution: int, title: str, description: str, additional_data=None) -> None:
        self._rendering_queue.append([url, title, description, additional_data])
        self._state.flush()
        self._rendering_queue_event.set()

    async def run(self):
        coros = [self._run_rendering(), self._run_uploads(), self._run_publishing()]
        loop = asyncio.get_running_loop()
        tasks = list(map(lambda c: loop.create_task(c), coros))
        await asyncio.wait(tasks, return_when=FIRST_EXCEPTION)
        for task in tasks:
            task.cancel()
            await task

    async def _run_rendering(self):
        while True:
            while len(self._rendering_queue) == 0:
                await self._rendering_queue_event.wait()  # prevents busy loop
                self._rendering_queue_event.clear()
            [url, title, description, additional_data] = self._rendering_queue[0]
            async with ClientSession() as session:
                try:
                    resp = await session.get(url)
                    video_file = await self._demo_renderer.render(url, await resp.read())
                    self._upload_queue.append([url, video_file, title, description, additional_data])
                except Exception as e:
                    await self._report_error(url, e, additional_data)
                self._rendering_queue.pop(0)
                self._state.flush()
                self._upload_queue_event.set()

    async def _run_uploads(self):
        while True:
            while len(self._upload_queue) == 0:
                await self._upload_queue_event.wait()  # prevents busy loop
                self._upload_queue_event.clear()
            [demo_url, video_file, title, description, additional_data] = self._upload_queue[0]
            try:
                video_url = await self._rendered_demo_uploader.upload(title, description, video_file)
                datetime_ready = (datetime.datetime.now() + self._delay_before_publishing).timestamp()
                self._waiting_queue.append([datetime_ready, video_url, additional_data, demo_url])
            except Exception as e:
                await self._report_error(demo_url, e, additional_data)

            self._upload_queue.pop(0)
            self._state.flush()
            self._waiting_queue_event.set()

    async def _run_publishing(self):
        while True:
            while len(self._waiting_queue) == 0:
                await self._waiting_queue_event.wait()  # prevents busy loop
                self._waiting_queue_event.clear()
            [datetime_ready, video_url, additional_data, demo_url] = self._waiting_queue[0]
            await wait_until(datetime.datetime.fromtimestamp(datetime_ready))
            for done_callback in self._done_callbacks:
                try:
                    await done_callback(video_url, additional_data)
                except Exception as e:
                    await self._report_error(demo_url, e, additional_data)
            self._waiting_queue.pop(0)
            self._state.flush()

    async def _report_error(self, id: int, e: Exception, additional_data: Any):
        for fail_callback in self._fail_callbacks:
            try:
                await fail_callback(id, e, additional_data)
            except BaseException as e:
                print(f"LocalRenderingQueue: Exception in fail callback {fail_callback}: {e}")
                traceback.print_exc()
                raise

    @classmethod
    def get_default_state(cls):
        return {
            'rendering_queue': [],
            'upload_queue': [],
            'waiting_queue': [],
        }
