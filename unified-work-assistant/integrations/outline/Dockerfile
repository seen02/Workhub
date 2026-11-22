FROM workhub-outline-build:1.10.0 AS build
COPY outline-65be53c3eb093a535ce260eb2f2da897bb07a29e/ ./
RUN yarn vite:build && yarn build:server

FROM unified-work-assistant/outline:migration-baseline
USER root
COPY --from=build --chown=nodejs:nodejs /opt/outline/build /opt/outline/build
COPY --from=build --chown=nodejs:nodejs /opt/outline/server /opt/outline/server
USER nodejs
