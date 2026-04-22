FROM eclipse-temurin:11-jre-jammy

# Install curl
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Download ROBOT
RUN curl -L https://github.com/ontodev/robot/releases/latest/download/robot.jar -o /opt/robot.jar

# Create a wrapper script so you can call `robot` directly
RUN echo '#!/bin/sh\nexec java -jar /opt/robot.jar "$@"' > /usr/local/bin/robot \
    && chmod +x /usr/local/bin/robot

WORKDIR /data

ENTRYPOINT ["robot"]