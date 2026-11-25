# Zehitomo scrape image: Python 3.12 + Google Chrome + Xvfb
# Build for amd64 (Chrome .deb is amd64-only). Set in compose: platform: linux/amd64
FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99

# System libs for Chrome + virtual display
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      fonts-liberation \
      gnupg \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcups2 \
      libdbus-1-3 \
      libdrm2 \
      libgbm1 \
      libgtk-3-0 \
      libnspr4 \
      libnss3 \
      libvulkan1 \
      libxcomposite1 \
      libxdamage1 \
      libxfixes3 \
      libxkbcommon0 \
      libxrandr2 \
      unzip \
      x11vnc \
      xauth \
      xdg-utils \
      xvfb \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome (HTTPS direct .deb — more reliable than apt http://dl.google.com)
RUN curl -fL --retry 5 --retry-all-errors --retry-delay 5 \
      -o /tmp/chrome.deb \
      https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/* \
    && google-chrome --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (overridden at runtime when compose mounts .:/app)
COPY app ./app
COPY login_profile.py .
COPY scripts ./scripts
COPY combination_creation ./combination_creation
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/profiles /app/credentials /app/data

# /entrypoint.sh lives outside /app so host bind-mount .:/app does not hide it
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.main", "--help"]
