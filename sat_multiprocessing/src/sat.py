#!/usr/bin/env python3
import argparse
import json
import multiprocessing as mp
import random
import time
from typing import List, Dict, Tuple, Set, Optional
from ortools.linear_solver import pywraplp
from ortools.sat.python import cp_model

# Types
Task = Dict  # expecting keys: name (str), payoff (float), resources (list[int]), optional execution_time (int)

# Utility 
def load_tasks_from_json(path: str) -> List[Task]:
    with open(path, 'r', encoding='utf-8') as f:
        items = json.load(f)
    # basic validation
    tasks = []
    for it in items:
        assert 'name' in it and 'payoff' in it and 'resources' in it
        task = {
            'name': str(it['name']),
            'payoff': float(it['payoff']),
            'resources': list(map(int, it['resources']))
        }
        if 'execution_time' in it:
            task['execution_time'] = int(it['execution_time'])
        tasks.append(task)
    return tasks

# CP Assign 
def cp_solve(tasks, num_sats):
    model = cp_model.CpModel()

    TASK_COUNT = len(tasks)
    ALL_RESOURCES = sorted({r for t in tasks for r in t["resources"]})

    # Decision vars
    assign = {}
    for i in range(TASK_COUNT):
        for s in range(num_sats):
            assign[(i, s)] = model.NewBoolVar(f"assign_{i}_to_{s}")

    # Each task assigned to <= 1 satellite
    for i in range(TASK_COUNT):
        model.Add(sum(assign[(i, s)] for s in range(num_sats)) <= 1)

    # exclusivity
    for s in range(num_sats):
        for r in ALL_RESOURCES:
            conflicting = []
            for i in range(TASK_COUNT):
                if r in tasks[i]["resources"]:
                    conflicting.append(assign[(i, s)])
            if conflicting:
                model.Add(sum(conflicting) <= 1)

    # Objective: maximize payoff
    objective_terms = []
    for i in range(TASK_COUNT):
        for s in range(num_sats):
            objective_terms.append(tasks[i]["payoff"] * assign[(i, s)])
    model.Maximize(sum(objective_terms))

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 8  # faster

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No optimal or feasible solution.")
        return None

    # --- Build result ---
    assignment = [[] for _ in range(num_sats)]
    for i in range(TASK_COUNT):
        for s in range(num_sats):
            if solver.BooleanValue(assign[(i, s)]):
                assignment[s].append(tasks[i])

    return assignment

# Satellite
#Result format: {'sat_id': int, 'task_name': str, 'success': bool}
def satellite_process(sat_id: int, task_queue: mp.Queue, result_queue: mp.Queue, failure_prob: float = 0.1):

    proc_name = mp.current_process().name
    print(f"[{proc_name}] Satellite {sat_id} starting with failure_prob={failure_prob}")
    while True:
        item = task_queue.get()
        if item is None:
            print(f"[{proc_name}] Satellite {sat_id} received shutdown sentinel.")
            break
        # item expected to be a list of tasks assigned to this satellite
        if not isinstance(item, list):
            continue
        for task in item:
            tname = task['name']
            # simulate execution time ~ small sleep
            time.sleep(0.1)  # pretend it takes some time
            success = random.random() >= failure_prob
            result_queue.put({'sat_id': sat_id, 'task_name': tname, 'success': success, 'task': task})
            print(f"[{proc_name}] Satellite {sat_id} executed task {tname}: {'OK' if success else 'FAIL'}")
    print(f"[{proc_name}] Satellite {sat_id} terminating.")

# GroundStation
def run_groundstation(tasks: List[Task], k_sats: int, failure_probs: List[float]):
    # prepare queues
    task_queues = [mp.Queue() for _ in range(k_sats)]
    result_queue = mp.Queue()

    # start satellite processes
    satellites = []
    for i in range(k_sats):
        p = mp.Process(target=satellite_process, args=(i+1, task_queues[i], result_queue, failure_probs[i]), daemon=False)
        p.start()
        satellites.append(p)

    # compute assignment
    #assignment = compute_assignment(tasks, k_sats)
    #assignment = ilp_assign(tasks, k_sats)
    assignment = cp_solve(tasks, k_sats)

    total_assigned = sum(len(s) for s in assignment)
    total_payoff = sum(sum(t['payoff'] for t in s) for s in assignment)
    print(f"[GroundStation] Assigning {total_assigned} tasks (total payoff {total_payoff}) across {k_sats} satellites.")

    # send assignment to each satellite
    for i in range(k_sats):
        task_queues[i].put(assignment[i])

    # sentinel
    for q in task_queues:
        q.put(None)

    # collect results: expect one result for each assigned task
    expected = total_assigned
    collected = 0
    results = []
    while collected < expected:
        res = result_queue.get()
        results.append(res)
        collected += 1

    # wait for satellites to finish
    for p in satellites:
        p.join(timeout=1.0)

    # Summarize
    summary = {}
    for r in results:
        tname = r['task_name']
        satid = r['sat_id']
        ok = r['success']
        summary[tname] = {'satellite': satid, 'success': ok, 'task': r.get('task')}
    # compute totals
    total_success_payoff = sum((summary[t]['task']['payoff'] if summary[t]['success'] else 0.0) for t in summary)
    total_fail_payoff = sum((summary[t]['task']['payoff'] if not summary[t]['success'] else 0.0) for t in summary)
    print("\n=== FINAL SUMMARY ===")
    print(f"Assigned tasks: {total_assigned}; Total theoretical payoff assigned: {total_payoff}")
    print(f"Payoff achieved (successful tasks): {total_success_payoff}")
    print(f"Payoff lost (failed tasks): {total_fail_payoff}")
    print("Per-task results:")
    for t, info in summary.items():
        print(f" - {t}: satellite={info['satellite']}, {'SUCCESS' if info['success'] else 'FAIL'} (payoff={info['task']['payoff']})")


def main():
    parser = argparse.ArgumentParser(description="Satellite Fleet Tasking Prototype")
    parser.add_argument('--tasks', required=True, help='Path to tasks JSON file')
    parser.add_argument('--satellites', type=int, default=2, help='Number of satellite processes (default 2)')
    parser.add_argument('--failure-probs', type=str, default=None,
                        help='Comma-separated failure probabilities per satellite, e.g. "0.05,0.15"')
    args = parser.parse_args()

    tasks = load_tasks_from_json(args.tasks)
    k = args.satellites
    if args.failure_probs:
        parts = args.failure_probs.split(',')
        probs = [float(p) for p in parts]
        if len(probs) == 1:
            probs = probs * k
        elif len(probs) != k:
            raise SystemExit("failure-probs length must match number of satellites or be a single value")
    else:
        probs = [0.1]*k

    random.seed(1)  # deterministic-ish for demo
    run_groundstation(tasks, k, probs)

if __name__ == '__main__':
    main()
