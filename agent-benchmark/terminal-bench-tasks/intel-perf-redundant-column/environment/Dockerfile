FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    build-essential \
    g++ \
    python3 \
    python3-pytest \
    time \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY q29_serial.cpp /app/q29_serial.cpp
COPY perf_tma.txt /app/perf_tma.txt
RUN useradd -m -u 1000 bench && chown -R bench:bench /app
USER bench
RUN g++ -O3 -std=c++17 /app/q29_serial.cpp -o /app/q29_serial
