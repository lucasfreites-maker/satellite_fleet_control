import os
import json
import time
import random
import threading
from typing import List, Dict

import paho.mqtt.client as mqtt

BROKER_HOST = os.environ.get("MQTT_HOST", "mqtt")
BROKER_PORT = int(os.environ.get("MQTT_PORT", 1883))
SAT_ID = int(os.environ.get("SAT_ID", "1"))
FAILURE_PROB = float(os.environ.get("FAILURE_PROB", "0.1"))

TASK_TOPIC = f"fleet/tasks/sat/{SAT_ID}"
RESULTS_TOPIC = "fleet/results"

client = mqtt.Client(client_id=f"satellite_{SAT_ID}")

def on_connect(client, userdata, flags, rc):
    print(f"[Satellite {SAT_ID}] Connected to MQTT broker (rc={rc}). Subscribing to {TASK_TOPIC}")
    client.subscribe(TASK_TOPIC, qos=1)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"[Satellite {SAT_ID}] Invalid payload: {e}")
        return

    # payload expected: list of tasks
    if not isinstance(payload, list):
        print(f"[Satellite {SAT_ID}] Unexpected payload format")
        return

    for task in payload:
        tname = task.get('name', '<unnamed>')
        # simulate execution cost
        time.sleep(0.1)
        success = random.random() >= FAILURE_PROB
        result = {
            'sat_id': SAT_ID,
            'task_name': tname,
            'success': success,
            'task': task
        }
        print(f"[Satellite {SAT_ID}] Executed {tname}: {'OK' if success else 'FAIL'}")
        client.publish(RESULTS_TOPIC, json.dumps(result), qos=1)

def main():
    random.seed()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_forever()

if __name__ == "__main__":
    main()

