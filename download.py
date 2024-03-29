#!/usr/bin/env python3
import asyncio
import logging
import os
import re
import sys
import threading
import urllib
import urllib.parse
from asyncio import ALL_COMPLETED
from logging import FileHandler
from typing import Optional, List, Dict, Tuple, Union

import discord
import filelock
from discord import Message, Attachment, File
from discord.abc import Messageable
from discord.iterators import HistoryIterator
from pathvalidate import sanitize_filename
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection

from discord_downloader.additional_data import AdditionalData
from discord_downloader.db import create_current_db_engine, RenderedDemo
from discord_downloader.demo_analyzer import DemoAnalyzer
from discord_downloader.demo_uploaders import FakeUploader, IgmdbUploader, OdfeDemoRenderer, \
    YoutubeUploader, VideoUploadException
from discord_downloader.local_queue import LocallyQueuedUploader, AutonomousRenderingQueue, PollingRenderingQueue, \
    RenderingQueue
from discord_downloader.local_rendering_queue import LocalRenderingQueue
from discord_downloader.movers import DeduplicatingRenamingMover
from discord_downloader.persistent_state import StoredState, Savepoint
from settings import DISCORD_TOKEN, CHANNELS, STATE_DIRECTORY, ATTACHMENTS_DIRECTORY, URLS_FILE, TEMP_DIRECTORY, \
    RENDERING_OUTPUT_CHANNEL, IGMDB_TOKEN, RENDERING_DONE_MESSAGE_PREFIX, RENDERING_DONE_MESSAGE_SUFFIX, \
    IGMDB_POLLING_INTERVAL, DEMOCLEANER_EXE, DEMO_RENDERING_PROVIDER, DEMO_RENDERING_LOCAL_PUBLISHING_DELAY, \
    DEMO_RENDERING_LOCAL_ODFE_DIR, DEMO_RENDERING_LOCAL_ODFE_EXECUTABLE, DEMO_RENDERING_LOCAL_ODFE_CONFIG, \
    DEMO_RENDERING_LOCAL_ODFE_DEMO, DEMO_RENDERING_LOCAL_ODFE_VIDEO, DEMO_RENDERING_LOCAL_ODFE_CONFIG_PREFIX, \
    DEMO_RENDERING_LOCAL_YOUTUBE_EXECUTABLE, DEMO_RENDERING_LOCAL_YOUTUBE_PARAMS, DISCORD_MAX_VIDEO_SIZE, \
    REACTIONS_WIP, REACTIONS_REJECTED, REACTIONS_DONE, REACTIONS_FAILED, \
    DEMO_RENDERING_LOCAL_YOUTUBE_DESCRIPTION_SUFFIX, DEMO_RENDERING_MISSING_DETAILS_REPORT_USER_ID, \
    already_rendered_message, RENDERING_DONE_MESSAGE_DISCORD


def extract_urls(msg):
    return re.findall(r'(https?://[^\s]+)', msg)


class DownloaderClient(discord.Client):
    _expected_thread = None
    _output_channels: Dict[Optional[str], List[Messageable]]
    _dirty = False

    def __init__(self, uploader: RenderingQueue, demo_analyzer: DemoAnalyzer, loop, conn: AsyncEngine):
        super(DownloaderClient, self).__init__(loop=loop)
        self._uploader = uploader
        self.ret = 0
        self._conn = conn
        self._loop = loop
        self._lock = asyncio.Lock(loop=loop)
        self._check_thread()
        self._prepared = False
        self._demo_analyzer = demo_analyzer
        self._logger = logging.getLogger('DownloaderClient')
        if not self._uploader.needs_polling():
            self._uploader: AutonomousRenderingQueue
            self._uploader.add_done_callback(self._after_upload)
            self._uploader.add_fail_callback(self._after_error)

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
                self._logger.info("Initial check done")
                self._prepared = True
                if self._dirty:
                    self._logger.info("I am dirty!")
                    await self._download_news()
                    self._check_thread()
                    self._dirty = False
                if self._uploader.needs_polling():
                    self._uploader: PollingRenderingQueue
                    while True:
                        self._check_thread()
                        await asyncio.sleep(IGMDB_POLLING_INTERVAL)
                        self._check_thread()
                        await self._check_uploads()
                        self._check_thread()
                else:
                    self._uploader: AutonomousRenderingQueue
                    await self._uploader.run()

            finally:
                await self.close()
                self._check_thread()
        except Exception as e:
            self.ret = 1
            self._logger.exception("Exception in on_ready")

    async def on_error(self, event_method, *args, **kwargs):
        self._logger.exception("Unhandled fatal error:")
        self._loop.stop()
        sys.exit(2)

    async def on_message(self, message: Message):
        if os.environ.get('SIMULATE_EXCEPTION') == '1':
            raise Exception('Simulantenbande!')
        self._check_thread()
        if not self._prepared:
            self._dirty = True
        else:
            channel_name = self._reverse_channels.get(message.channel)
            if channel_name is None:
                self._logger.warning(f"skipping message due to unknow channel name: {message.channel} / {message}")
                return
            self._logger.info(f"new message in channel: {channel_name} ({message.channel})")
            check_all_messages = channel_name in CHANNELS
            self._logger.info("Checking single channel…")
            await self._download_channel(channel_name, message.channel, check_all_messages)
            self._check_thread()
            self._logger.info("on_message: done")

    async def _check_uploads(self):
        if self._uploader is not None and self._uploader.needs_polling():
            self._uploader: PollingRenderingQueue
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
                    await self._after_error(None, e, None)
                    self._check_thread()

    async def _after_upload(self, url: str, additional_data_raw):
        additional_data = AdditionalData.reconstruct(additional_data_raw)
        message_id = additional_data.message_id
        self._check_thread()
        output_channels = await self._get_output_channels(additional_data.in_channel)
        self._logger.info(f"_after_upload: output_channels: {output_channels}")
        for channel in output_channels:
            self._logger.info(f"_after_upload: Fetching message {message_id} in channel {channel}")
            if message_id is not None:
                try:
                    original_message = await channel.fetch_message(message_id)
                    original_message_ref = (original_message).to_reference()
                    self._logger.info(f"_after_upload: Fetched: {original_message_ref}")
                except discord.errors.NotFound as e:
                    self._logger.info(f"_after_upload: Cannot find message {message_id}: {e}")
                    original_message = None  # fallback
                    original_message_ref = None  # fallback
            else:
                original_message = None
                original_message_ref = None
            await channel.send(
                content=f"{RENDERING_DONE_MESSAGE_PREFIX}{url}{RENDERING_DONE_MESSAGE_SUFFIX}",
                reference=original_message_ref
            )
            if original_message is not None:
                await self._replace_reactions(original_message, REACTIONS_DONE)
            await self._record_uploaded_video(url, additional_data)
            self._check_thread()
        if additional_data.has_unknown:
            notification_user = await self.fetch_user(DEMO_RENDERING_MISSING_DETAILS_REPORT_USER_ID)
            await notification_user.send(f'Video with some unknown: {url}')
        self._logger.info(f"_after_upload: result url: {url}")

    async def _post_video_directly_to_discord(self, additional_data_raw, filename: str, e: VideoUploadException):
        self._logger.warning(f"_post_video_directly_to_discord: Video upload failed; uploading directly to Discord: {e}")
        additional_data = AdditionalData.reconstruct(additional_data_raw)
        self._logger.info(f"_post_video_directly_to_discord: round_id: {additional_data.rerendering_round}")
        max_size = DISCORD_MAX_VIDEO_SIZE
        video_size = os.path.getsize(e.video_file)
        next_round = 0 if additional_data.rerendering_round is None else additional_data.rerendering_round + 1
        if video_size > max_size:
            self._logger.warning(f"_post_video_directly_to_discord: Video size {video_size}B is larger than maximum ({max_size}), rendering again")
            new_additional_data = AdditionalData(
                in_channel=additional_data.in_channel,
                message_id=additional_data.message_id,
                title=additional_data.title,
                description=additional_data.description,
                rerendering_round=next_round,
                url=additional_data.url,
                has_unknown=additional_data.has_unknown,
                filename=additional_data.filename
            )
            await self._uploader.upload(
                url=additional_data.url,
                resolution=28,
                title=additional_data.title,
                description=additional_data.description,
                additional_data=new_additional_data.serialize()
            )

        else:
            in_channel = additional_data.in_channel
            message_id = additional_data.message_id
            self._check_thread()
            out_channels = await self._get_output_channels(in_channel)
            self._logger.info(f"_post_video_directly_to_discord: out_channels: {out_channels}")
            for channel in out_channels:
                self._logger.info(f"_post_video_directly_to_discord: get message ref {channel} {message_id}")
                channel: Messageable
                try:
                    original_message = await channel.fetch_message(message_id)
                    original_message_ref = original_message.to_reference() if message_id is not None else None
                except discord.errors.NotFound as nfe:
                    original_message = None
                    original_message_ref = None
                message_content = f"{RENDERING_DONE_MESSAGE_DISCORD}"
                self._logger.info(f"_post_video_directly_to_discord: before send {channel} {type(channel)} "
                                  f"{e.video_file} {original_message_ref}.")
                self._logger.info(f"_post_video_directly_to_discord: sending message: {message_content}")
                with open(e.video_file, 'rb') as fp:
                    out_msg = await channel.send(
                        content=message_content,
                        file=File(fp, filename),
                        reference=original_message_ref
                    )
                    await self._record_uploaded_video(url=out_msg.jump_url, additional_data=additional_data)
                    if original_message is not None:
                        await self._replace_reactions(original_message, REACTIONS_DONE)

                self._logger.info(f"_post_video_directly_to_discord: after send")
            if additional_data.has_unknown:
                notification_user = await self.fetch_user(DEMO_RENDERING_MISSING_DETAILS_REPORT_USER_ID)
                await notification_user.send(f'Video with some unknown: {additional_data}')
            self._logger.info(f"_post_video_directly_to_discord: Discord upload done")
            return

    async def _get_output_channels(self, in_channel):
        return self._output_channels.get(in_channel, None) or [self._channels.get(in_channel)]

    async def _after_error(self, identifier: Optional[int], e: Exception, additional_data_raw, filename: Optional[str] = None):
        self._check_thread()
        if isinstance(e, VideoUploadException):
            try:
                await self._post_video_directly_to_discord(additional_data_raw, filename, e)
                addi_data = AdditionalData.reconstruct(additional_data_raw) if additional_data_raw is not None else None
                if addi_data.rerendering_round is None:  # don't spam on re-renders
                    notification_user = await self.fetch_user(DEMO_RENDERING_MISSING_DETAILS_REPORT_USER_ID)
                    await notification_user.send(
                        f'Video upload failed: {addi_data.url},\n'
                        f'message: {addi_data.message_id},\n'
                        f'channel: {addi_data.in_channel},\n'
                        f'title: {addi_data.title}\n'
                        f'description: {addi_data.description}\n'
                        f'error details: {e.message}\n'
                        f'video file: {e.video_file}\n'
                    )

            except Exception as e2:
                self._logger.exception(f"_after_error: Exception in error handler")
                await self._after_error(identifier, e2, additional_data_raw, filename)

        self._logger.exception(f"_after_error:Logging error for #{identifier} ({filename}; {additional_data_raw}):\n")
        additional_data = AdditionalData.reconstruct(additional_data_raw) if additional_data_raw is not None else None
        if (additional_data is not None) and (not isinstance(e, VideoUploadException)):
            for channel in await self._get_output_channels(additional_data.in_channel):
                try:
                    original_message = await channel.fetch_message(additional_data.message_id)
                    await self._replace_reactions(original_message, REACTIONS_FAILED)
                except discord.errors.NotFound as e:
                    pass
                except Exception as e:
                    self._logger.exception(f"_after_error: failure when adding reactions")

    async def _init_channels(self):
        self._logger.info(f"_init_channels: Connected")

        self._check_thread()
        self._channels = await self._get_channels()
        self._reverse_channels = {v: k for k, v in self._channels.items()}
        self._check_thread()
        missing = CHANNELS.keys() - self._channels.keys()
        if len(missing) > 0:
            raise Exception(f"Some channels were not found: {missing}")
        self._output_channels = {
            # legacy channel
            None: self._translate_output_channels(RENDERING_OUTPUT_CHANNEL),
            # new channel
            **{k: self._translate_output_channels(v) for k, v in CHANNELS.items()}
        }

    def _translate_output_channels(self, output_channel_names):
        output_channel_names_list = [output_channel_names] if isinstance(output_channel_names, str) else output_channel_names
        return list(map(self._get_output_channel, output_channel_names_list))

    def _get_output_channel(self, name):
        channel = self._channels.get(name)
        if channel is None:
            raise Exception(f"Output channel in RENDERING_OUTPUT_CHANNEL not found: {name}")
        else:
            return channel

    async def _download_news(self):
        async with self._lock:
            self._logger.info("Checking individual channels")
            channel: Messageable
            for name, channel in self._channels.items():
                check_all_mesages = name in CHANNELS
                self._logger.info(f"## {name} (check all: {check_all_mesages})")
                await self._download_channel_without_lock(name, channel, check_all_mesages)
                self._check_thread()
            self._logger.info("_download_news: Everything done")

    async def _get_channels(self):
        channels = {}
        for channel in self.get_all_channels():
            if hasattr(channel, "history") and hasattr(channel, "name") and hasattr(channel, "guild"):
                name = f"{channel.guild}--{channel.name}"
                if channels.get(name) is not None:
                    raise Exception(f"Multiple channels for name {name}")
                channels[name] = channel
        return channels

    async def _download_channel(self, name: str, channel: Messageable, check_all_messages: bool):
        async with self._lock:
            self._check_thread()
            await self._download_channel_without_lock(name, channel, check_all_messages)
            self._check_thread()

    async def _download_channel_without_lock(self, name: str, channel: Messageable, check_all_messages: bool):
        self._check_thread()
        savepoint = Savepoint(os.path.join(STATE_DIRECTORY, urllib.parse.quote(name) + ".txt"))
        mover = DeduplicatingRenamingMover()
        last_processed_message_id = savepoint.get()  # messages have increasing ids; we can use it to mark what messages we have seen
        self._logger.info(f"channel: {type(channel)} {channel}")
        history: HistoryIterator = channel.history(
            limit=None,
            oldest_first=True,
            after=discord.Object(891111111283456789) if last_processed_message_id is None else discord.Object(last_processed_message_id)
        )
        with open(URLS_FILE, "a") as urls_file:
            def before_sync():
                self._logger.info("Syncing… ")
                urls_file.flush()
                os.fsync(urls_file.fileno())

            def after_sync():
                self._logger.info("Sync done")

            async def archive_message(message: Message):
                self._logger.info(f"#{message.id} {message.created_at}: {message.content}")
                urls = extract_urls(message.content)
                if len(urls) > 0:
                    for url in urls:
                        urls_file.write(f"{url} ({message.jump_url})\n")

                attachment: Attachment
                for i, attachment in enumerate(message.attachments):
                    tmp_file = os.path.join(TEMP_DIRECTORY, f"{message.id}-{attachment.id}-{i}-{os.getpid()}")
                    sanitized_attachment_filename = sanitize_filename(attachment.filename, replacement_text='-')
                    out_file = os.path.join(
                        ATTACHMENTS_DIRECTORY,
                        sanitized_attachment_filename
                    )
                    with open(tmp_file, mode="wb") as f:
                        await attachment.save(f)
                        self._check_thread()
                        f.flush()
                        os.fsync(f.fileno())
                    new_attachment_filename, is_new = mover.move(tmp_file, out_file)

                    if self._is_dm6x_filename(attachment):
                        if is_new:
                            await self._add_reactions(message, REACTIONS_WIP)
                            await self._post_to_igmdb(attachment, new_attachment_filename, name, message)
                            self._check_thread()
                        else:
                            render_url = await self._get_rendered_video_url(sanitized_attachment_filename)
                            if render_url is not None:
                                await self._add_reactions(message, REACTIONS_REJECTED)
                                await message.reply(already_rendered_message(render_url))
                            else:
                                # We have already rendered it, but we don't have the YT URL
                                await self._add_reactions(message, REACTIONS_WIP)
                                await self._post_to_igmdb(attachment, new_attachment_filename, name, message)
                                self._check_thread()

                    self._logger.info(f"* {attachment} (new: {new_attachment_filename})")

            try:
                async for m in history:
                    if check_all_messages or self.user in m.mentions:
                        await archive_message(m)
                    savepoint.set(m.id, before_sync=before_sync, after_sync=after_sync)  # mark as done
            except discord.errors.Forbidden:
                self._logger.warning(f"No access to channel {channel}")
        savepoint.close()

    def _is_dm6x_filename(self, filename) -> bool:
        return re.compile(".*\\.dm_6[0-9]$").match(filename.filename) is not None

    async def _post_to_igmdb(self, attachment: Attachment, local_filename: str, channel_name: str, message: Message):
        self._check_thread()
        has_unknown = False
        try:
            demo_info = await self._demo_analyzer.analyze(local_filename)
            self._check_thread()

            def unknown_if_none(inp: Optional[str]):
                if inp is None:
                    nonlocal has_unknown
                    has_unknown = True
                    return '<unknown>'
                else:
                    return inp

            nick = unknown_if_none(demo_info['player'].get('uncoloredName') or demo_info['player'].get('df_name'))
            mapname = unknown_if_none(demo_info['client'].get('mapname'))
            physics = unknown_if_none(self._extract_physics(demo_info['game'].get('gameplay')))
            time = unknown_if_none(demo_info['record'].get('bestTime'))
            title = f"DeFRaG: {nick} {time} {physics} {mapname}".replace('<', '_').replace('>', '_')
            description_orig = f"Nickname: {nick}\nTime: {time}\nPhysics: {physics}\nMap: {mapname}\n" \
                               f"{DEMO_RENDERING_LOCAL_YOUTUBE_DESCRIPTION_SUFFIX}"
            description = description_orig.replace('<', '_').replace('>', '_')
            additional_data = AdditionalData(
                in_channel=channel_name,
                message_id=message.id,
                title=title,
                description=description,
                rerendering_round=None,
                url=attachment.url,
                has_unknown=has_unknown,
                filename=os.path.basename(local_filename)
            )
        except Exception as e:
            self._check_thread()
            await self._after_error(attachment.id, e, None, filename=attachment.filename)
            return

        try:
            await self._uploader.upload(
                url=attachment.url,
                resolution=28,
                title=title,
                description=description,
                additional_data=additional_data.serialize()
            )
        except Exception as e:
            self._check_thread()
            await self._after_error(attachment.id, e, additional_data.serialize(), filename=attachment.filename)
        self._check_thread()

    def _check_thread(self):
        if self._expected_thread is None:
            self._expected_thread = threading.current_thread()
            if self._expected_thread is None:
                raise Exception("WTF: current thread is None!")
        else:
            if self._expected_thread != threading.current_thread():
                raise Exception(f"Bad Thread: {self._expected_thread} != {threading.current_thread()}")
            if self._loop != asyncio.get_running_loop():
                raise Exception(f"Bad event loop: {self._loop} != {asyncio.get_running_loop()}")

    def _extract_physics(self, gameplay):
        if gameplay is None:
            return None
        match = re.compile('.*\\((.*)\\)$').match(gameplay)
        if match is None:
            return gameplay
        else:
            return match.group(1)

    async def _remove_reactions(self, message: Message):
        my_reactions = filter(lambda m: m.me, message.reactions)
        aws = list(map(lambda reaction: message.remove_reaction(reaction.emoji, self.user), my_reactions))
        done, pending = await asyncio.wait(aws, return_when=ALL_COMPLETED)
        assert len(pending) == 0
        for result in done:
            try:
                await result
            except Exception as e:
                self._logger.exception(f'exception when removing reaction from {message}:', exc_info=e)

    async def _add_reactions(self, message: Message, reactions: Union[List[str], str]):
        if isinstance(reactions, str):
            return await self._add_reactions(message, [reactions])
        for reaction in reactions:
            try:
                await message.add_reaction(reaction)
            except Exception as e:
                raise Exception(f'Error when addinng reaction {reaction}') from e

    async def _replace_reactions(self, message: Message, reactions: Union[List[str], str]):
        await self._remove_reactions(message)
        await self._add_reactions(message, reactions)

    async def _record_uploaded_video(self, url: str, additional_data: AdditionalData):
        async with self._conn.begin() as connection:
            connection: AsyncConnection
            await connection.execute(insert(RenderedDemo).values(url=url, filename=additional_data.filename))

    async def _get_rendered_video_url(self, filename):
        async with self._conn.begin() as conn:
            conn: AsyncConnection
            res = await conn.execute(select(RenderedDemo).where(RenderedDemo.filename == filename))
            all = res.fetchall()
            if len(all) == 0:
                return None
            if len(all) == 1:
                [record] = all
                record: RenderedDemo
                return record.url
            raise Exception(f"WTF: {all} {filename}")


def create_igmdb_uploader():
    if IGMDB_TOKEN is not None:
        if IGMDB_TOKEN == 'fake-uploader':
            return FakeUploader()
        else:
            return IgmdbUploader(IGMDB_TOKEN)


def create_uploader() -> Tuple[StoredState, RenderingQueue]:
    if DEMO_RENDERING_PROVIDER == 'igmdb':
        up = create_igmdb_uploader()
        upload_queue_json_file = os.path.join(STATE_DIRECTORY, "igmdb-upload-queue.json")
        igmdb_state = StoredState(upload_queue_json_file, LocallyQueuedUploader.get_default_state())
        return igmdb_state, (LocallyQueuedUploader(up, igmdb_state) if up is not None else None)
    elif DEMO_RENDERING_PROVIDER == 'local-rendering':
        upload_queue_json_file = os.path.join(STATE_DIRECTORY, "local-rendering-queue.json")
        local_queue_state = StoredState(upload_queue_json_file, LocalRenderingQueue.get_default_state())
        queue = LocalRenderingQueue(
            demo_renderer=OdfeDemoRenderer(
                odfe_dir=DEMO_RENDERING_LOCAL_ODFE_DIR,
                odfe_executable=DEMO_RENDERING_LOCAL_ODFE_EXECUTABLE,
                config_dir=DEMO_RENDERING_LOCAL_ODFE_CONFIG,
                demo_dir=DEMO_RENDERING_LOCAL_ODFE_DEMO,
                video_dir=DEMO_RENDERING_LOCAL_ODFE_VIDEO,
                defrag_config=DEMO_RENDERING_LOCAL_ODFE_CONFIG_PREFIX
            ),
            rendered_demo_uploader=YoutubeUploader(
                youtube_uploader_executable=DEMO_RENDERING_LOCAL_YOUTUBE_EXECUTABLE,
                youtube_uploader_params=DEMO_RENDERING_LOCAL_YOUTUBE_PARAMS
            ),
            state=local_queue_state,
            delay_before_publishing=DEMO_RENDERING_LOCAL_PUBLISHING_DELAY
        )
        return local_queue_state, queue
    elif DEMO_RENDERING_PROVIDER is not None:
        raise Exception(f"Unexpected DEMO_RENDERING_PROVIDER: {DEMO_RENDERING_PROVIDER}")


async def main():
    try:
        conn = create_current_db_engine()
        with filelock.FileLock(os.path.join(STATE_DIRECTORY, "run.lock")).acquire(timeout=10):
            file_handler = FileHandler(filename=os.path.join(STATE_DIRECTORY, "errors.log"))
            file_handler.setLevel(logging.WARNING)
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
                handlers=[file_handler, logging.StreamHandler()]
            )
            logging.getLogger().info("Connecting…")
            state, uploader = create_uploader()
            client = DownloaderClient(
                uploader=uploader,
                demo_analyzer=DemoAnalyzer(DEMOCLEANER_EXE),
                loop=loop,
                conn=conn
            )
            try:
                await client.start(DISCORD_TOKEN)
            finally:
                await client.close()
            state.close()
            sys.exit(client.ret)
    except filelock.Timeout:
        logging.getLogger().error("Unable to acquire lock. It looks like this process is already running…")


if __name__ == "__main__":
    loop = asyncio.ProactorEventLoop() if sys.platform == 'win32' else asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
