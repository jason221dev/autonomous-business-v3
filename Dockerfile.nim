# Multi-role Hermes container — NIM roles
# Installs hermes-agent + NIM-specific tools
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

# Install runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent + requests for NIM API
RUN pip install hermes-agent requests

# Create hermes dirs
RUN mkdir -p /root/.hermes/skills /var/hermes/sessions /app/logs /etc/hermes/workers

WORKDIR /app

# Copy role runner
COPY role-runner.sh /usr/local/bin/role-runner
RUN chmod +x /usr/local/bin/role-runner

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:3100/api/health')" || exit 1

CMD ["/usr/local/bin/role-runner"]
