FROM python:3.11-slim

# Metadados
LABEL maintainer="admin@empresa.com"
LABEL description="EdgeGate - Backend API"

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    ca-certificates \
    gnupg \
    lsb-release \
    netcat-openbsd \
    iputils-ping \
    iproute2 \
    iptables \
    nftables \
    openvpn \
    easy-rsa \
    procps \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Cria diretório de trabalho
WORKDIR /app

# Copia requirements e instala dependências Python
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copia aplicação
COPY . .

# Cria usuário não-root e adiciona ao grupo docker
RUN useradd -m -u 1000 vpnuser && \
    groupadd -f docker && \
    usermod -aG docker vpnuser && \
    chown -R vpnuser:vpnuser /app

# Cria diretórios necessários
RUN mkdir -p /var/log/edgegate /app/data /certs/manual && \
    chown -R vpnuser:vpnuser /var/log/edgegate /app/data /certs/manual

# Torna script de inicialização executável
RUN chmod +x /app/scripts/start.sh

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expõe porta
EXPOSE 8000

# Muda para usuário não-root
USER vpnuser

# Comando padrão - executa script de inicialização
CMD ["/app/scripts/start.sh"]
