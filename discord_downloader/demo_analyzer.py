import asyncio
import re
import subprocess
import sys
import xml.dom.minidom
import xml.etree
from typing import Dict


class DemoAnalyzer:

    def __init__(self, democleaner_exe: str):
        self._democleaner_exe = democleaner_exe

    async def analyze(self, file: str) -> Dict[str, Dict[str, str]]:
        proc: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            self._democleaner_exe, "--xml", file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        try:
            stdout, stderr = await proc.communicate()
            if stderr not in [b'', b'Could not set X locale modifiers\n']:
                raise Exception("Error when analyzing demo: "+str(stderr))
            dom = xml.dom.minidom.parseString(self._remove_raw(self._clean_stdout_mess(stdout)))
            root: xml.dom.minidom.Element = dom.childNodes[0]
            return dict(map(lambda element: (element.nodeName, dict(element.attributes.items())), root.childNodes))
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    @staticmethod
    def _clean_stdout_mess(stdout: bytes):
        if sys.platform == 'linux':
            # Remove Mono's mess:
            end_marker = b'</demoFile>'
            try:
                end_pos = stdout.rindex(end_marker)
            except ValueError:
                # end_marker not found
                return stdout
            stdout_len = end_pos + len(end_marker)
            return stdout[0:stdout_len]
        else:
            return stdout

    def _remove_raw(self, xml: bytes):
        return re.sub(b'<raw .* />', b'', xml)

