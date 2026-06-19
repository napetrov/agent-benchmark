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
COPY branch_mispredict_bad.cpp /app/branch_mispredict_bad.cpp
COPY perf_stat.txt /app/perf_stat.txt
RUN g++ -O3 -std=c++17 /app/branch_mispredict_bad.cpp -o /app/branch_mispredict_bad
