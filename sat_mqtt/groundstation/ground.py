import os
import json
import time
import queue
import random
from typing import List, Dict
import threading

import paho.mqtt.client as mqtt
from ortools.sat.python import cp_model

def load_tasks_from_json(path: str) -> List[Dict]:
    with open(path, 'r', encoding='utf-8') as f:
        items = json.load(f)
    tasks = []
    for it in items:
        task = {
            'name': str(it['name']),
            'payoff': float(it['payoff']),
            'resources': list(map(int, it['resources']))
        }
        if 'execution_time' in it:
            task['execution_time'] = int(it['execution_time'])
        tasks.append(task)
    return tasks

# CP-SAT assignment
def cp_solve(tasks, num_sats):
    model = cp_model.CpModel()
    TASK_COUNT = len(tasks)
    ALL_RESOURCES = sorted({r for t in tasks for r in t["resources"]})

    assign = {}
    for i in range(TASK_COUNT):
        for s in range(num_sats):
            assign[(i, s)] = model.NewBoolVar(f"assign_{i}_to_{s}")

    # sat task constraints
    for i in range(TASK_COUNT):
        model.Add(sum(assign[(i, s)] for s in range(num_sats)) <= 1)

    for s in range(num_sats):
        for r in ALL_RESOURCES:
            conflicts = []
            for i in range(TASK_COUNT):
                if r in tasks[i]["resources"]:
                    conflicts.append(assign[(i, s)])
            if conflicts:
                model.Add(sum(conflicts) <= 1)

    # load
    load = [model.NewIntVar(0, TASK_COUNT, f"load_{s}") for s in range(num_sats)]
    for s in range(num_sats):
        model.Add(load[s] == sum(assign[(i, s)] for i in range(TASK_COUNT)))

    avg_load = TASK_COUNT / num_sats

    # load balancing penalty
    # (load[s] - avg_load)^2 cuadratic variance
    imbalance_terms = []
    for s in range(num_sats):
        diff = model.NewIntVar(-TASK_COUNT, TASK_COUNT, f"diff_{s}")
        model.Add(diff == load[s] - int(avg_load))

        sq = model.NewIntVar(0, TASK_COUNT * TASK_COUNT, f"sq_{s}")
        model.AddMultiplicationEquality(sq, [diff, diff])

        imbalance_terms.append(sq)

    # balance weight
    LAMBDA_BALANCE = 1

    payoff_terms = []
    for i in range(TASK_COUNT):
        for s in range(num_sats):
            payoff_terms.append(int(tasks[i]["payoff"] * 100) * assign[(i, s)])

    model.Maximize(
        sum(payoff_terms) - LAMBDA_BALANCE * sum(imbalance_terms)
    )

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 8 #possible improvement, dynamic multicore processors number

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No feasible assignment found")

    assignment = [[] for _ in range(num_sats)]
    for s in range(num_sats):
        for i in range(TASK_COUNT):
            if solver.BooleanValue(assign[(i, s)]):
                assignment[s].append(tasks[i])

    # balance debug
    #print("\n=== LOAD BALANCING REPORT ===")
    #for s in range(num_sats):
    #    print(f"Sat {s+1}: load={solver.Value(load[s])}")

    return assignment

# MQTT GroundStation
BROKER_HOST = os.environ.get("MQTT_HOST", "mqtt")
BROKER_PORT = int(os.environ.get("MQTT_PORT", 1883))

TASKS_FILE = os.environ.get("TASKS_FILE", "/app/tasks.json")
SAT_COUNT = int(os.environ.get("SAT_COUNT", "2"))

results_q = queue.Queue()

def on_connect(client, userdata, flags, rc):
    print(f"[GroundStation] Connected to MQTT broker ({BROKER_HOST}:{BROKER_PORT}) rc={rc}")

    client.subscribe("fleet/results", qos=1)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        print("[GroundStation] Invalid message:", e)
        return
    results_q.put(payload)

def main():
    random.seed(1)
    tasks = load_tasks_from_json(TASKS_FILE)
    print(f"[GroundStation] Loaded {len(tasks)} tasks from {TASKS_FILE}")

    assignment = cp_solve(tasks, SAT_COUNT)
    total_assigned = sum(len(s) for s in assignment)
    total_payoff = sum(sum(t['payoff'] for t in s) for s in assignment)
    print(f"[GroundStation] Assignment computed: {total_assigned} tasks, payoff {total_payoff}")

    # setup
    client = mqtt.Client(client_id="groundstation")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    # publish sat assignements
    for idx, sat_tasks in enumerate(assignment):
        sat_id = idx + 1
        topic = f"fleet/tasks/sat/{sat_id}"
        payload = json.dumps(sat_tasks)
        print(f"[GroundStation] Publishing {len(sat_tasks)} tasks to {topic}")
        client.publish(topic, payload, qos=1)

    # wait for results
    expected = total_assigned
    collected = []
    timeout_seconds = 30
    start = time.time()
    while len(collected) < expected and (time.time() - start) < timeout_seconds:
        try:
            item = results_q.get(timeout=1.0)
            collected.append(item)
            print(f"[GroundStation] Received result: {item}")
        except queue.Empty:
            continue

    client.loop_stop()
    client.disconnect()

    if len(collected) < expected:
        print(f"[GroundStation] WARNING: expected {expected} results but got {len(collected)}")

    # summarize
    summary = {}
    for r in collected:
        tn = r.get('task_name')
        summary[tn] = {'satellite': r.get('sat_id'), 'success': r.get('success'), 'task': r.get('task')}

    success_payoff = sum(summary[t]['task']['payoff'] for t in summary if summary[t]['success'])
    failed_payoff = sum(summary[t]['task']['payoff'] for t in summary if not summary[t]['success'])

    print("\n=== FINAL SUMMARY ===")
    print(f"Assigned: {expected}, Theoretical payoff: {total_payoff}")
    print(f"Achieved payoff: {success_payoff}, Lost payoff: {failed_payoff}")
    for t, info in summary.items():
        print(f" - {t}: sat {info['satellite']} → {'SUCCESS' if info['success'] else 'FAIL'}")

if __name__ == "__main__":
    main()

