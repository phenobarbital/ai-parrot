# Build from the repository root:
#   docker build -t parrot-grafana docker/grafana
# Run locally with persistent data:
#   docker run -d --name parrot-grafana -p 127.0.0.1:3000:3000 \
#     -v parrot-grafana-data:/var/lib/grafana parrot-grafana
# Open http://localhost:3000 (initial login: admin / admin).
# The app needs a Prometheus-compatible data source with Claude Code telemetry.

# Override with --build-arg GRAFANA_VERSION=<tag>; requires Grafana >=12.3.0.
ARG GRAFANA_VERSION=latest
FROM grafana/grafana:${GRAFANA_VERSION}

# Keep bundled plugins separate from the persistent Grafana data volume.
ENV GF_PATHS_PLUGINS=/var/lib/grafana-plugins

USER root
RUN mkdir -p "${GF_PATHS_PLUGINS}" \
    && chown grafana:root "${GF_PATHS_PLUGINS}"

USER grafana
RUN grafana cli --pluginsDir "${GF_PATHS_PLUGINS}" plugins install timurdigital-claudestats-app

EXPOSE 3000
