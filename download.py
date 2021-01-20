#!/usr/bin/env python3
import asyncio
import os
import re
import sys
import threading
import traceback
import urllib
import urllib.parse
from typing import TextIO, Optional, List

import discord
import filelock
from discord import Message, Attachment
from discord.abc import Messageable
from discord.iterators import HistoryIterator
from pathvalidate import sanitize_filename

from discord_downloader.demo_analyzer import DemoAnalyzer
from discord_downloader.demo_uploaders import DemoUploader, FakeUploader, IgmdbUploader
from discord_downloader.local_queue import LocallyQueuedUploader
from discord_downloader.movers import DeduplicatingRenamingMover
from discord_downloader.persistent_state import StoredState, Savepoint
from settings import DISCORD_TOKEN, CHANNELS, STATE_DIRECTORY, ATTACHMENTS_DIRECTORY, URLS_FILE, TEMP_DIRECTORY, \
    RENDERING_OUTPUT_CHANNEL, IGMDB_TOKEN, RENDERING_DONE_MESSAGE_PREFIX, RENDERING_DONE_MESSAGE_SUFFIX, \
    IGMDB_POLLING_INTERVAL, DEMOCLEANER_EXE


def extract_urls(msg):
    return re.findall(r'(https?://[^\s]+)', msg)


class DownloaderClient(discord.Client):

    _expected_thread = None
    _lock = asyncio.Lock()
    _output_channels: List[Messageable]
    _dirty=False

    def __init__(self, uploader: DemoUploader, igmdb_state: StoredState, demo_analyzer: DemoAnalyzer,
                 error_log: TextIO):
        super(DownloaderClient, self).__init__()
        self._uploader = LocallyQueuedUploader(uploader, igmdb_state) if uploader is not None else None
        self.ret = 0
        self._check_thread()
        self._error_log = error_log
        self._prepared = False
        self._demo_analyzer = demo_analyzer

    async def on_ready(self):
        try:
            try:
                self._check_thread()
                await self._init_channels()
                self._check_thread()
                await self._check_uploads()
                self._check_thread()
                await self._download_news()
                self._check_thread()
                print("Initial check done")
                self._prepared = True
                if self._dirty:
                    print("I am dirty!")
                    await self._download_news()
                    self._check_thread()
                    self._dirty = False
                while True:
                    self._check_thread()
                    await asyncio.sleep(IGMDB_POLLING_INTERVAL)
                    self._check_thread()
                    await self._check_uploads()
                    self._check_thread()

            finally:
                await self.logout()
                self._check_thread()
        except Exception as e:
            self.ret = 1
            traceback.print_exc(file=sys.stderr)

    async def on_error(self, event_method, *args, **kwargs):
        print("Unhandled error:")
        traceback.print_exc()
        self._error_log.write("Unhandled error:")
        traceback.print_exc(file=self._error_log)
        sys.exit(2)

    async def on_message(self, message: Message):
        self._check_thread()
        channel_name = self._reverse_channels.get(message.channel)
        print(f"new message in channel: {channel_name} ({message.channel})")
        if channel_name in CHANNELS:
            if not self._prepared:
                self._dirty = True
            else:
                print("Checking single channel…")
                await self._download_channel(channel_name, message.channel)
                self._check_thread()
                print("done")
        else:
            print("I am not interested in this channel!")

    async def _check_uploads(self):
        if self._uploader is not None:
            async with self._lock:
                self._check_thread()
                try:
                    await self._uploader.check_for_done(
                        done_callback=self._after_upload,
                        failed_callback=self._after_error,
                    )
                    self._check_thread()
                    await self._uploader.retry_uploads()
                    self._check_thread()
                except Exception as e:
                    await self._after_error(None, e)
                    self._check_thread()

    async def _after_upload(self, url: str):
        self._check_thread()
        for channel in self._output_channels:
            await channel.send(f"{RENDERING_DONE_MESSAGE_PREFIX}{url}{RENDERING_DONE_MESSAGE_SUFFIX}")
            self._check_thread()
        print(f"result url: {url}")

    async def _after_error(self, identifier: Optional[int], e: Exception, filename: Optional[str] = None):
        self._check_thread()
        print(f"Logging error for #{identifier} ({filename}): {e}\n")
        self._error_log.write(f"Error for #{identifier} ({filename}): {e}\n")
        traceback.print_exc(file=self._error_log)
        self._error_log.flush()

    async def _init_channels(self):
        print("Connected")

        self._check_thread()
        self._channels = await self._get_channels()
        self._reverse_channels = {v: k for k, v in self._channels.items()}
        self._check_thread()
        missing = CHANNELS - self._channels.keys()
        if len(missing) > 0:
            raise Exception(f"Some channels were not found: {missing}")

        output_channel_names = [RENDERING_OUTPUT_CHANNEL] if isinstance(RENDERING_OUTPUT_CHANNEL, str) else RENDERING_OUTPUT_CHANNEL

        def get_output_channel(name):
            channel = self._channels.get(name)
            if channel is None:
                raise Exception(f"Output channel in RENDERING_OUTPUT_CHANNEL not found: {name}")
            else:
                return channel

        self._output_channels = list(map(get_output_channel, output_channel_names))

    async def _download_news(self):
        async with self._lock:
            print("Checking individual channels")
            channel: Messageable
            for name, channel in self._channels.items():
                if name in CHANNELS:
                    print(f"## {name}")
                    await self._download_channel_without_lock(name, channel)
                    self._check_thread()
            print("Everything done")

    async def _get_channels(self):
        channels = {}
        for channel in self.get_all_channels():
            if hasattr(channel, "history") and hasattr(channel, "name") and hasattr(channel, "guild"):
                name = f"{channel.guild}--{channel.name}"
                if channels.get(name) is not None:
                    raise Exception(f"Multiple channels for name {name}")
                channels[name] = channel
        return channels

    async def _download_channel(self, name: str, channel: Messageable):
        async with self._lock:
            self._check_thread()
            await self._download_channel_without_lock(name, channel)
            self._check_thread()

    async def _download_channel_without_lock(self, name: str, channel: Messageable):
        self._check_thread()
        savepoint = Savepoint(os.path.join(STATE_DIRECTORY, urllib.parse.quote(name) + ".txt"))
        mover = DeduplicatingRenamingMover()
        last_processed_message_id = savepoint.get()  # messages have increasing ids; we can use it to mark what messages we have seen
        history: HistoryIterator = channel.history(
            limit=None,
            oldest_first=True,
            after=None if last_processed_message_id is None else discord.Object(last_processed_message_id)
        )
        with open(URLS_FILE, "a") as urls_file:
            def before_sync():
                print("Syncing… ", end="")
                urls_file.flush()
                os.fsync(urls_file.fileno())

            def after_sync():
                print("Done")

            message: Message
            async for message in history:
                print(f"#{message.id} {message.created_at}: {message.content}")
                urls = extract_urls(message.content)
                if len(urls) > 0:
                    for url in urls:
                        urls_file.write(f"{url} ({message.jump_url})\n")

                attachment: Attachment
                for i, attachment in enumerate(message.attachments):
                    tmp_file = os.path.join(TEMP_DIRECTORY, f"{message.id}-{attachment.id}-{i}-{os.getpid()}")
                    out_file = os.path.join(
                        ATTACHMENTS_DIRECTORY,
                        sanitize_filename(attachment.filename, replacement_text='-')
                    )
                    with open(tmp_file, mode="wb") as f:
                        await attachment.save(f)
                        self._check_thread()
                        f.flush()
                        os.fsync(f.fileno())
                    new_attachment_filename = mover.move(tmp_file, out_file)

                    if (new_attachment_filename is not None) and re.compile(".*\\.dm_6[0-9]$").match(attachment.filename) is not None:
                        await self._post_to_igmdb(attachment, new_attachment_filename)
                        self._check_thread()

                    print(f"* {attachment} (new: {new_attachment_filename})")
                savepoint.set(message.id, before_sync=before_sync, after_sync=after_sync)  # mark as done
        savepoint.close()

    async def _post_to_igmdb(self, attachment: Attachment, local_filename: str):
        self._check_thread()
        try:
            demo_info = await self._demo_analyzer.analyze(local_filename)
            self._check_thread()

            nick = demo_info['player']['df_name']
            mapname = demo_info['client']['mapname']
            physics = self._extract_physics(demo_info['game']['gameplay'])
            time = demo_info['record']['bestTime']

            await self._uploader.upload(
                url=attachment.url,
                resolution=28,
                title=f"DeFRaG: {nick} {time} {physics} {mapname}",
                description=f"Nickname: {nick}\nTime: {time}\nPhysics: {physics}\nMap: {mapname}",
            )
        except Exception as e:
            self._check_thread()
            await self._after_error(attachment.id, e, filename=attachment.filename)
        self._check_thread()

    def _check_thread(self):
        if self._expected_thread is None:
            self._expected_thread = threading.current_thread()
            if self._expected_thread is None:
                raise Exception("WTF: current thread is None!")
        else:
            if self._expected_thread != threading.current_thread():
                raise Exception(f"Bad Thread: {self._expected_thread} != {threading.current_thread()}")

    def _extract_physics(self, gameplay):
        match = re.compile('.*\\((.*)\\)$').match(gameplay)
        if match is None:
            return gameplay
        else:
            return match.group(1)


def create_uploader():
    if IGMDB_TOKEN is not None:
        if IGMDB_TOKEN == 'fake-uploader':
            return FakeUploader()
        else:
            return IgmdbUploader(IGMDB_TOKEN)


def main():
    try:
        with filelock.FileLock(os.path.join(STATE_DIRECTORY, "run.lock")).acquire(timeout=10):
            with open(os.path.join(STATE_DIRECTORY, "errors.log"), "a") as error_log:
                print("Connecting…")
                upload_queue_json_file = os.path.join(STATE_DIRECTORY, "igmdb-upload-queue.json")
                igmdb_state = StoredState(upload_queue_json_file, LocallyQueuedUploader.get_default_state())
                client = DownloaderClient(
                    uploader=create_uploader(),
                    igmdb_state=igmdb_state,
                    demo_analyzer=DemoAnalyzer(DEMOCLEANER_EXE),
                    error_log=error_log
                )
                client.run(DISCORD_TOKEN)
                igmdb_state.close()
                sys.exit(client.ret)
    except filelock.Timeout:
        print("Unable to acquire lock. It looks like this process is already running…")


if __name__ == "__main__":
    main()