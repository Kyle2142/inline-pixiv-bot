FROM python:3-alpine

WORKDIR /usr/src/app

ENV DOCKER 1

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python3", "./inlinepixivbot.py" ]
