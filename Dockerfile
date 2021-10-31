ARG IMAGE=foobar

FROM python:3.7.3 AS env_base_bare
RUN apt update && apt full-upgrade -y && apt install -y mono-complete
RUN apt install -y xvfb
COPY requirements.txt /
RUN pip3 install -r /requirements.txt
RUN mkdir /opt/dldr
RUN ln -s /opt/dldr/download.py /usr/bin/download

FROM env_base_bare AS discord_downloader_run
COPY *.py alembic.ini DemoCleaner3.* /opt/dldr/
COPY alembic/ /opt/dldr/alembic
COPY stubs/ /opt/dldr/stubs
RUN chmod +x /opt/dldr/DemoCleaner3.sh
COPY discord_downloader/ /opt/dldr/discord_downloader
ENV DISPLAY=:5
ENTRYPOINT bash -c 'rm /tmp/.X5-lock; (Xvfb :5&); download'

FROM env_base_bare AS discord_downloader_test
COPY requirements-test.txt /
RUN pip install -r requirements-test.txt
ENV PYTHONPATH=/opt/dldr
COPY *.py /opt/dldr/
COPY discord_downloader/ /opt/dldr/discord_downloader
COPY tests/ /opt/dldr/tests
ENTRYPOINT pytest /opt/dldr/tests

FROM discord_downloader_${IMAGE}