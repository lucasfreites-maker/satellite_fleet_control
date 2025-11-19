#!/bin/bash
COUNT=${SAT_COUNT:-5}

echo "services:" > docker-compose.generated.yml

# Add MQTT broker
cat <<EOF >> docker-compose.generated.yml
  mqtt:
    image: eclipse-mosquitto:2
    container_name: mqtt_broker
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf
    restart: unless-stopped
EOF

# Add groundstation
cat <<EOF >> docker-compose.generated.yml
  groundstation:
    build:
      context: .
      dockerfile: groundstation/Dockerfile
    environment:
      - MQTT_HOST=mqtt
      - MQTT_PORT=1883
      - SAT_COUNT=${COUNT}
    volumes:
      - ./tasks.json:/app/tasks.json
    depends_on:
      - mqtt
    restart: "no"
EOF

# Add satellites 1..N
for i in $(seq 1 $COUNT); do
cat <<EOF >> docker-compose.generated.yml
  satellite${i}:
    build:
      context: .
      dockerfile: satellite/Dockerfile
    environment:
      - SAT_ID=${i}
      - MQTT_HOST=mqtt
      - MQTT_PORT=1883
    depends_on:
      - mqtt
    restart: unless-stopped
EOF
done

