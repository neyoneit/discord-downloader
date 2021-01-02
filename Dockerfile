ARG IMAGE=foobar

FROM python:3.7.3 AS env_base_bare
COPY requirements.txt /
RUN pip3 install -r /requirements.txt
RUN mkdir /opt/dldr
RUN ln -s /opt/dldr/download.py /usr/bin/download

FROM env_base_bare AS discord_downloader_run
COPY *.py /opt/dldr/
COPY discord_downloader/ /opt/dldr/discord_downloader
ENTRYPOINT download

FROM env_base_bare AS discord_downloader_test
COPY requirements-test.txt /
RUN pip install -r requirements-test.txt
ENV PYTHONPATH=/opt/dldr
COPY *.py /opt/dldr/
COPY discord_downloader/ /opt/dldr/discord_downloader
COPY tests/ /opt/dldr/tests
ENTRYPOINT pytest /opt/dldr/tests

FROM discord_downloader_${IMAGE}