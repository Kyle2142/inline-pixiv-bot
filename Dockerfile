FROM python:3

WORKDIR /usr/src/app


COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

ENV DOCKER 1

CMD [ "python3", "./inlinepixivbot.py" ]
