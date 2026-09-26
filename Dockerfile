FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       novnc \
       python3-venv \
       websockify \
       x11-utils \
       x11vnc \
       xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Le librerie dell'applicazione restano separate dai pacchetti di Ubuntu.
RUN python3 -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt \
    && python -m pip check

COPY libero_mail_bot.py /app/libero_mail_bot.py
COPY start.sh /app/start.sh

RUN chmod 0755 /app/start.sh \
    && mkdir -p /data

CMD ["/app/start.sh"]
