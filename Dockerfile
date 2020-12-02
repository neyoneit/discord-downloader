FROM python:3.7.3
COPY requirements.txt /
RUN pip3 install -r /requirements.txt
RUN mkdir /opt/dldr
COPY *.py /opt/dldr/
RUN ln -s /opt/dldr/download.py /usr/bin/download

ENTRYPOINT download