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
            dom = xml.dom.minidom.parseString(self._preprocess_xml(self._clean_stdout_mess(stdout).decode('utf-8')))
            root: xml.dom.minidom.Element = dom.childNodes[0]
            return dict(map(lambda element: (self._postprocess_string(element.nodeName), self._postprocess_dict(element.attributes.items())), root.childNodes))
        except BaseException as e:
            raise Exception(f"Fail when processing {file}") from e
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

    def _preprocess_xml(self, s: str):
        # This preprocesses XML string in order to make the XML from DemoCleaner3 parseable. The problem is in entities
        # with low character code, because they are invalid in XML 1.0.
        # XML 1.1 from 2004 would be probably a good solution to this problem. But we would need a XML 1.1 parser,
        # which is hard to find in 2021. I've found just few of them for Java, but nothing directly usable in Python.
        # Even the W3C validator cannot validate XML 1.1 in 2021.
        # When you preprocess XML this way, it allows you to parse the XML from DemoCleaner3. However, you need to
        # postprocess all the XML strings using _postprocess_string.
        return s.replace('@', '@40;').replace('&#x', '@')

    def _postprocess_string(self, s: str):
        parts = s.split('@')
        first = parts[0]
        others = parts[1:]

        def process_hexa(chunk: str):
            try:
                entity_end = chunk.index(';')
            except ValueError:
                raise Exception(f"No semicolon found in {chunk}")
            hexa = chunk[0:entity_end]
            char = chr(int(hexa, 16))
            rest = chunk[entity_end+1:]
            return char+rest


        return first + ("".join(map(process_hexa, others)))

    def _postprocess_dict(self, indict):
        return dict(map(lambda x: (self._postprocess_string(x[0]), self._postprocess_string(x[1])), indict))

    def _remove_raw(self, xml: bytes):
        return re.sub(b'<raw .* />', b'', xml)

