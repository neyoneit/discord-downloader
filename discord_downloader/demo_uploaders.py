import abc
import asyncio
import datetime
import json
import os.path
import random
import re
import shutil
import subprocess
import uuid
from abc import abstractmethod
from os import path
from typing import NamedTuple, Optional, List

from aiohttp import ClientSession


class UploadResult(NamedTuple):
     success: bool
     render_id: int


class DemoUploader(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    async def upload(self, url: str, resolution: int, title: str, description: str) -> UploadResult:
        pass

    @abc.abstractmethod
    async def check_status(self, id: int) -> Optional[str]:
        pass


class NopUploader(DemoUploader):

    async def upload(self, url: str, resolution: int, title: str, description: str) -> UploadResult:
        pass

    async def check_status(self, id: int) -> Optional[str]:
        return None


class UploadException(Exception):
    pass


class QueueFullException(UploadException):

    def __init__(self) -> None:
        super().__init__('Upload queue is full')


class ProbablyAlreadyUploadedException(UploadException):

    def __init__(self, url) -> None:
        super().__init__(f'Upload seems to have been already submitted: {url}')


class RenderedDemoUploader(abc.ABC):

    @abstractmethod
    async def upload(self, title: str, description: str, file: str):
        pass


class DemoRenderer(abc.ABC):
    @abstractmethod
    async def render(self, demo_filename: str, demo_data: bytes) -> str:
        pass


class YoutubeUploader(RenderedDemoUploader):

    def __init__(self, youtube_uploader_executable: str, youtube_uploader_params: List[str]):
        self._youtube_uploader_executable = youtube_uploader_executable
        self._youtube_uploader_params = youtube_uploader_params

    async def upload(self, title: str, description: str, file: str):
        proc: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            self._youtube_uploader_executable,
            *self._youtube_uploader_params,
            f"--description={description}",
            f"--title={title}",
            "--",
            file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        try:
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                res = stdout.split(b'[RequestError] Server response:', 1)
                if len(res) == 2:
                    [_prefix, json_message] = res
                    msg = json.loads(json_message)
                    raise VideoUploadException(msg, file)
                else:
                    raise VideoUploadException(f'YT uploader: Bad return errorcode {proc.returncode}', file)
            if stderr not in [b'']:
                raise VideoUploadException("Error when uploading video: " + str(stderr), file)
            stream_identifier = stdout.splitlines()[-1].decode('ASCII')
            return f"https://youtu.be/{stream_identifier}"
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass


class VideoUploadException(Exception):

    def __init__(self, message, video_file):
        super().__init__((message, video_file))
        self.message = message
        self.video_file = video_file



DEMO_EXT_REGEX = re.compile(".*\\.(dm_6[0-9])$")

class OdfeDemoRenderer(DemoRenderer):

    def __init__(self, odfe_dir: str, odfe_executable: str, config_dir: str, demo_dir: str, video_dir: str,
                 defrag_config: str):
        self._odfe_dir = odfe_dir
        self._odfe_executable = odfe_executable
        self._config_dir = config_dir
        self._demo_dir = demo_dir
        self._video_dir = video_dir
        self._defrag_config = defrag_config

    async def render(self, demo_filename: str, demo_data: bytes) -> str:
        id = f"{datetime.datetime.now().timestamp()}-{uuid.uuid4().hex}"
        demo_ext = DEMO_EXT_REGEX.match(demo_filename).group(1)
        demo_tmp_basename = f"{id}.{demo_ext}"
        demo_tmp_file = os.path.join(self._demo_dir, demo_tmp_basename)
        with open(demo_tmp_file, 'wb') as f:
            f.write(demo_data)
        cfg_file_content = "".join(map(lambda x: x+"\n", [
            self._defrag_config,
            f'demo "{demo_tmp_basename}"',
            f'video-pipe "{id}"',
            'set nextdemo "wait 100; quit"',
        ]))
        cfg_bare_file_name = f"file-{id}.cfg"
        cfg_file_name = os.path.join(self._config_dir, cfg_bare_file_name)
        with open(cfg_file_name, "w") as f:
            f.write(cfg_file_content)
        proc: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            path.join(self._odfe_dir, self._odfe_executable),
            "+exec",
            cfg_bare_file_name,
            cwd=self._odfe_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        try:
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise Exception(
                    f'Demo renderer: Bad return errorcode {proc.returncode}; stdout {stdout}; stderr {stderr}')
            #if stderr not in [b'']:
            #    raise Exception("Error when rendering video: " + str(stderr))
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            os.remove(cfg_file_name)
            os.remove(demo_tmp_file)

        return os.path.join(self._video_dir, f"{id}.mp4")


class IgmdbUploader(DemoUploader):

    def __init__(self, token):
        self._token = token

    async def upload(self, url: str, resolution: int, title: str, description: str) -> UploadResult:
        async with ClientSession() as session:
            data = {
                'api_key': self._token,
                'demo_url': url,
                'resolution': resolution,
                # 1 will output the rendered demo directly to YouTube, 4 is needed for custom channel (though not much
                # officially documented)
                'output': 4,
                'stream_title': title,
                'stream_description': description,
            }
            async with session.post('https://www.igmdb.org/processor.php?action=submitDemo', data = data) as response:
                resp_s = await response.read()
                print(f"resp_s: {resp_s}")
                resp = json.loads(resp_s.replace(b"\\'", b"'"))
                success = resp['success']
                render_id = resp['render_id']
                print(str(resp))
                if success and not render_id:
                    raise ProbablyAlreadyUploadedException(url)
                if not success:
                    error = resp['error']
                    if error == "Can't submit; you are banned or have reached the maximum number of demos in queue":
                        raise QueueFullException()
                    else:
                        data_safe = data.copy()
                        del data_safe['api_key']
                        raise UploadException(f"{error}; data={json.dumps(data_safe)}")
                return UploadResult(success = success, render_id = render_id)

    async def check_status(self, id: int) -> Optional[str]:
        async with ClientSession() as session:
            async with session.get(f'https://www.igmdb.org/processor.php?action=getRenderInformation&render_id={id}') as response:
                resp_s = await response.read()
                resp = json.loads(resp_s)
                if resp['success']:
                    if resp['output']['status_final'] == '1':
                        stream_identifier = resp['output'].get('donator_stream_identifier') or \
                                            resp['output']['stream_identifier']
                        if stream_identifier == "":
                            raise Exception(f"Empty stream identifier for {resp_s}")
                        return f"https://youtu.be/{stream_identifier}"
                    else:
                        return None
                else:
                    raise Exception(
                        resp['output']['error'] if 'error' in resp['output'] else f"Unknown error when checking status: {resp_s}"
                    )


class FakeUploader(DemoUploader):

    async def upload(self, url: str, resolution: int, title: str, description: str) -> UploadResult:
        print(f"Simulating upload of {url}: title: {title}, resolution: {resolution}, description: {description}")
        r = random.randrange(100)
        if r < 33: raise QueueFullException()
        if r < 43: raise ProbablyAlreadyUploadedException(url)
        if r < 53: raise UploadException('Generic upload exception')
        return UploadResult(True, random.randrange(65536))

    async def check_status(self, id: int) -> Optional[str]:
        print(f"Simulating check_status for {id}")
        r = random.randrange(100)
        if r < 20: return f"https://example.com/#{random.randrange(65536)}"
        if r < 90: return None
        raise Exception('Some random exception')
