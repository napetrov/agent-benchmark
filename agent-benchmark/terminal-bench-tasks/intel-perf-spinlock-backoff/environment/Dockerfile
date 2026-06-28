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
COPY spin_bad.cpp /app/spin_bad.cpp
COPY perf_annotate.txt /app/perf_annotate.txt
RUN useradd -m -u 1000 bench && chown -R bench:bench /app
USER bench
RUN g++ -O3 -std=c++17 -pthread /app/spin_bad.cpp -o /app/spin_bad
