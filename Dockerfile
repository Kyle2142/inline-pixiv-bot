FROM python:3-alpine

WORKDIR /usr/src/app

ENV DOCKER 1

COPY requirements.txt ./
RUN apk add --no-cache --virtual .build-deps build-base libffi-dev && \
    pip3 install --no-cache-dir -r requirements.txt && \
    apk del .build-deps

COPY . .

CMD [ "python3", "./inlinepixivbot.py" ]
