# Architecture, Design Decisions, and Improvements

This project is divided into two independent solutions:

1. **Multiprocessing-based model**, where satellites run as local processes and communicate with the groundstation via Python mp.Queue().
2. **Distributed MQTT-based model**, where satellites run as separate Docker containers and communicate with the groundstation through an MQTT Pub/Sub broker.

Both implementations solve the same optimization problem but differ in architecture, scalability, and communication mechanisms.

---

## 1. Multiprocessing Solution (Local Processes + Queues)

### 1.1 Concurrency Model

In this solution, each satellite is executed as a separate process, while communication occurs using two `mp.Queue()` objects:

- `task_queue` for sending tasks from the groundstation to satellites.
- `result_queue` for transmitting results from satellites back to the groundstation.

`mp.Queue()` is the perfect choice here because it is:

- **Thread-safe**, thanks to Python’s internal locking mechanisms.
- Free from race conditions: `put()` and `get()` are atomic.
- FIFO by design, matching the requirements of the task scheduling system.
- Safe to use in concurrent, multi-process environments.

This ensures deterministic message ordering and consistency without needing manual locks or synchronization primitives.

---

### 1.2 Task Assignment and Optimization

Task assignment is centralized: satellites do not compute or choose tasks. Instead, the groundstation determines the optimal task allocation.

A Greedy algorithm was initially considered but discarded due to:

- Significant complexity when adding new constraints.
- Poor scalability beyond ~16 resources (satellites).
- Inability to guarantee optimality or stability in large cases.

Instead, **Google OR-Tools CP-SAT** was selected, providing:

- A clean and expressive way to add optimization constraints.
- Optimal or near-optimal solutions with significantly better scalability.
- Thread-safe behavior suitable for concurrent processing.
- Excellent community support and comprehensive documentation.

---

### 1.3 Running and Cleaning the System

All dependencies are present in the requirements.txt. Docker takes care of environment for clean run:

    cd sat_multiprocessing/

    docker build -t sat .

After building the docker image with the proper dependencies declared in the requirements.txt file we proceed to execution:

    docker run --rm sat --tasks tasks.json --satellites [amount of satellites] --failure-probs [comma separated prob of failure number]

eg:
    
    docker run --rm sat --tasks tasks.json --satellites 2 --failure-probs 0.05,0.03


The number of failure of probes present has to be consistent with the amount of satellites present, otherwise an error will arise. 

A Summary inlcuding information on the payoff allocated; result; general and per satellite is given at the end of the process. 

As we can see the solution is concise and flexible, allowing us to simulate different amounts of satellites each one with a specific failure probability. (A possible improvement here could be having default failure probabilities so we don´t have to pass such a list of arguments)

---

## 2. Distributed Solution (Docker + MQTT)

### 2.1 Why MQTT?

The second solution focuses on scalability and realism. Each satellite runs independently as its own Docker container and communicates through an MQTT broker using Pub/Sub.

MQTT fits this architecture perfectly because:

- It uses minimal overhead—ideal for embedded satellite-like devices.
- Pub/Sub ensures loose coupling between satellites and the groundstation.
- QoS-1 enables reliable message delivery.
- JSON messages are simple to serialize and parse.
- It avoids shared memory entirely, eliminating race conditions.

This mirrors real-world IoT and satellite constellations, where each device communicates with a central hub over lightweight protocols.

---

### 1.2 Load Balancing Improvement

While CP-SAT maximized total payoff effectively, it tended to concentrate tasks in a few satellites, especially when scaling the system beyond 10–20 satellites.

To address this, a load-balancing term was added to the objective:


Where:

- `total_payoff` is the sum of assigned task payoffs.
- `load_imbalance` measures uneven task distribution.
- `λ` (lambda) is a tunable parameter (default = 1).

This modification ensures:

- High payoff is still prioritized.
- Tasks are distributed more evenly across satellites.
- The system behaves more like a realistic distributed fleet.

This improvement is especially impactful in the MQTT-based model where the number of satellites is larger.

---

### 2.3 Automated Deployment

A generation script is included to automatically produce a `docker-compose.generated.yml` with the exact number of satellites desired:

SAT_COUNT=N ./generate-sats.sh

The generated file includes services for:

- MQTT broker (Mosquitto)
- Groundstation
- N satellite containers

This means no manual configuration changes are required when scaling up.

### 2.4 Running and Cleaning the System

Start the entire system using the generated Docker Compose file:

    docker compose -f docker-compose.generated.yml up --build

This command will:

- Build all satellite images
- Build the groundstation image
- Start the MQTT broker
- Launch all services together
- Stream logs for every component (MQTT, satellites, groundstation)

To stop the system:

    docker compose down

Remove any leftover containers or satellites created dynamically:

    docker compose -f docker-compose.generated.yml down --remove-orphans

Finally, clean up unused Docker images to free disk space:

    docker image prune -a

This ensures a clean environment for the next simulation run.
