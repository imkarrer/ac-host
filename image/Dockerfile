FROM debian:bookworm-slim

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        lib32gcc-s1 \
        lib32stdc++6 \
        libc6:i386 \
        libstdc++6:i386 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 1000 --create-home ac \
    && mkdir -p /opt/steamcmd /opt/ac /instance \
    && chown -R ac:ac /opt/steamcmd /opt/ac /instance

USER ac
WORKDIR /opt/steamcmd

RUN curl -fsSL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" \
    | tar -xz

ENV STEAMCMD_LOGIN=anonymous \
    AC_INSTALL=/opt/ac \
    AC_INSTANCE=/instance

USER root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
USER ac

EXPOSE 9600/tcp 9600/udp 8081/tcp
ENTRYPOINT ["/entrypoint.sh"]
