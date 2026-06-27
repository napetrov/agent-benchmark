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
COPY sp_bad.cpp /app/sp_bad.cpp
COPY perf_c2c.txt /app/perf_c2c.txt
RUN useradd -m -u 1000 bench && chown -R bench:bench /app
USER bench
RUN g++ -O3 -std=c++17 -pthread /app/sp_bad.cpp -o /app/sp_bad
