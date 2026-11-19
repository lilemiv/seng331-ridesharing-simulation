# Event Graph — code-aligned model

The diagram distinguishes **recorded lifecycle events** (rounded nodes) from
**internal SimPy decisions/state** (diamonds/rectangles). The labels in parentheses
match `SimulationEvent.event_type`; internal capacity checks, queue entries, and
driver release are **not** separate exported event types.

```mermaid
flowchart TD
    start([Simulation Start])
    arrival([Request Arrival])
    capacity{"FIFO driver request granted<br/>strictly before patience deadline?"}
    waiting["FIFO waiting for resource<br/>Patience: exponential, mean 5 min"]
    outcome{"Assignment granted<br/>before deadline?"}
    assign([Driver Assignment])
    abandon([Customer Abandonment])
    pickupDone([Pickup Completion])
    tripDone([Trip Completion])
    endEvent([Simulation End at exclusive horizon])

    start -->|"Generate first arrival after<br/>exponential interarrival"| arrival
    arrival -->|"Schedule next arrival after<br/>exponential interarrival, mean 0.75 min"| arrival
    arrival --> capacity
    capacity -->|"Yes"| assign
    capacity -->|"No: await grant or patience expiry"| waiting
    waiting --> outcome
    outcome -->|"Granted strictly before deadline"| assign
    outcome -->|"Expiry first or exact tie"| abandon
    assign -->|"Pickup takes uniform 2-8 min;<br/>driver held"| pickupDone
    pickupDone -->|"Trip takes lognormal duration;<br/>arithmetic mean 10 min; driver held"| tripDone
    tripDone -.->|"Driver released by resource context;<br/>next FIFO waiter may be granted"| waiting
```

The `simulation_end` event is recorded once the configured simulation horizon
(default 60 minutes) is reached; it is not a customer transition in the graph.
Events at the exact horizon are excluded. `simulation_start` is recorded at time 0.
Arrivals proceed independently of customers already waiting or in service.

At arrival a customer samples an exponential patience duration. A SimPy Resource
with capacity `fleet_size` processes driver requests in FIFO order. If the driver
request is granted strictly before the customer's patience deadline, the engine
records `driver_assignment` and the customer remains `in_service` through pickup
and trip. Otherwise the engine records `abandonment`; exact deadline ties favor
abandonment. `pickup_completion` marks the beginning of the trip, and
`trip_completion` marks completion and precedes the driver's resource release.
The release is an internal SimPy action, not an additional history event.

There are no driver IDs, street coordinates, routes, or geographic dispatch rules
in the current engine. A visualization consuming `event_history` can accurately
replay **customer statuses and service stages**; any positions on a 2D city
illustration must be labeled schematic rather than actual simulated trajectories.
All durations above are configurable defaults, measured in minutes.

