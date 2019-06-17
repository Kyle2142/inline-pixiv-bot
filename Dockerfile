FROM python:3

WORKDIR /usr/src/app

COPY . .

RUN pip3 install --no-cache-dir -r requirements.txt

ENV DOCKER 1

CMD [ "python3", "./inlinepixivbot.py" ]
