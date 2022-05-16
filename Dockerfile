FROM python:3.10-alpine3.15 AS build-image

RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    g++ \
    libpq-dev

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --upgrade pip && pip3 install -r requirements.txt

COPY . .
RUN python3 setup.py install


FROM python:3.10-alpine3.15

COPY --from=build-image /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

RUN apk add --no-cache binutils openssl-dev

RUN mkdir -p /skill/config \
    && mkdir -p /skill/data

ENTRYPOINT ["jellyfin_alexa_skill"]
CMD ["/skill/config/skill.conf"]

LABEL org.opencontainers.image.source="https://github.com/infinityofspace/jellyfin_alexa_skill"
LABEL org.opencontainers.image.licenses="GPL-3.0"
