FROM alpine:3.19

LABEL maintainer="EdgeGate"
LABEL description="OpenVPN Server with EasyRSA"

# Install packages
RUN apk add --no-cache \
    openvpn \
    easy-rsa \
    bash \
    curl \
    iptables \
    ip6tables \
    conntrack-tools \
    openssl \
    jq \
    netcat-openbsd

# Create directories
RUN mkdir -p /etc/openvpn/{ccd,logs,pki} /opt/openvpn-scripts

# Copy scripts to a location that won't be overwritten by volume
COPY scripts/ /opt/openvpn-scripts/
RUN chmod +x /opt/openvpn-scripts/*.sh

# Create tun device
RUN mkdir -p /dev/net && \
    mknod /dev/net/tun c 10 200 || true

EXPOSE 1194/udp

WORKDIR /etc/openvpn

# Use entrypoint script to setup and run
CMD ["/opt/openvpn-scripts/start.sh"]
