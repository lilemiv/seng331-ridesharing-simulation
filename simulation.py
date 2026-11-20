"""Core engine: FIFO assignment, patience, uniform pickup, lognormal trips."""

from collections import Counter
from collections.abc import Generator
from dataclasses import dataclass, replace
from math import isclose, isfinite
import random
from typing import Literal

import simpy

from config import SimulationConfig
from dispatch import Driver, select_nearest_driver, select_random_driver


EventType = Literal[
    "simulation_start", "arrival", "driver_assignment", "abandonment",
    "pickup_completion", "trip_completion", "simulation_end",
]


@dataclass(frozen=True)
class SimulationEvent:
    """Logical state immediately after a lifecycle event, in sequence order.

    Same-time rows have zero elapsed time between them. For the state after
    all events at a time, use its last row. Counts describe customer states,
    not transient internal SimPy grants waiting for process callbacks.
    """

    sequence: int
    time: float
    event_type: EventType
    request_id: int | None
    request_status: str | None
    service_stage: str | None
    arrivals: int
    waiting: int
    in_system: int
    busy_drivers: int
    completed: int
    abandoned: int


@dataclass(frozen=True)
class DriverEvent:
    """Named assignment/release snapshot, separate from customer event history."""

    sequence: int
    time: float
    event_type: Literal["driver_assignment", "driver_release"]
    driver_id: int
    request_id: int
    x: float
    y: float


@dataclass
class RideRequest:
    """Arrival ledger entry. Times use minutes; None means not yet reached.

    Status stays in_service through pickup and trip. Sampled durations become
    available when their stage starts; they are not completion timestamps.
    """

    request_id: int
    arrival_time: float  # Minutes since the simulation started.
    patience_time: float  # Sampled once at arrival, in minutes.
    service_start_time: float | None = None
    completion_time: float | None = None
    abandonment_time: float | None = None
    status: Literal["waiting", "in_service", "completed", "abandoned"] = "waiting"
    pickup_start_time: float | None = None
    pickup_completion_time: float | None = None
    trip_start_time: float | None = None
    pickup_duration: float | None = None
    trip_duration: float | None = None
    assigned_driver_id: int | None = None
    pickup_x: float | None = None
    pickup_y: float | None = None
    destination_x: float | None = None
    destination_y: float | None = None

    @property
    def driver_assignment_time(self) -> float | None:
        """Alias preserving the existing service_start_time field."""
        return self.service_start_time

    @property
    def trip_completion_time(self) -> float | None:
        """Alias: overall completion is exactly the end of the trip."""
        return self.completion_time

    @property
    def service_stage(self) -> Literal["pickup", "trip"] | None:
        """Current active stage; None for waiting, completed, or abandoned."""
        if self.status != "in_service":
            return None
        return "pickup" if self.trip_start_time is None else "trip"


class RideSharingSimulation:
    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.env = simpy.Environment()
        # Python normalizes negative integer seeds using abs(). Normalize the
        # base before offsets so negative seeds cannot collapse two streams.
        stream_seed = abs(config.random_seed)
        self.rng = random.Random(stream_seed)
        # A separate stream preserves the arrival sequence from earlier steps.
        self.patience_rng = random.Random(stream_seed + 1)
        self.pickup_rng = random.Random(stream_seed + 2)
        self.trip_rng = random.Random(stream_seed + 3)
        self.driver_location_rng = random.Random(stream_seed + 4)
        self.pickup_location_rng = random.Random(stream_seed + 5)
        self.destination_rng = random.Random(stream_seed + 6)
        self.dispatch_rng = random.Random(stream_seed + 7)
        self.driver_pool = simpy.Resource(self.env, capacity=config.fleet_size)
        self._drivers = {
            driver_id: Driver(driver_id, *self._sample_position(self.driver_location_rng))
            for driver_id in range(1, config.fleet_size + 1)
        }
        self._driver_history: list[DriverEvent] = []
        self._initial_drivers = self.drivers
        # Complete arrival history; the active FIFO queue is driver_pool.queue.
        self.requests: list[RideRequest] = []
        # Map pending/held Resource events to their customer records.
        self._resource_requests: dict[simpy.resources.resource.Request, RideRequest] = {}
        self._counts: Counter[str] = Counter()
        self.event_history: list[SimulationEvent] = []
        self._record_event("simulation_start")

        # Register the generator as a process; it starts when env.run() runs.
        self.env.process(self.generate_requests())

    def generate_requests(self) -> Generator[simpy.events.Timeout, None, None]:
        """Record each arrival and start its independent customer process."""
        while True:
            # expovariate takes a rate (arrivals/minute), not a mean time.
            delay = self.rng.expovariate(
                1.0 / self.config.mean_interarrival_minutes
            )
            # Yielding a timeout suspends this process until that event occurs.
            # SimPy advances its clock; this does not wait in real time.
            yield self.env.timeout(delay)

            request = RideRequest(
                request_id=len(self.requests) + 1,
                arrival_time=self.env.now,
                patience_time=self.patience_rng.expovariate(
                    1.0 / self.config.mean_patience_minutes
                ),
            )
            request.pickup_x, request.pickup_y = self._sample_position(self.pickup_location_rng)
            request.destination_x, request.destination_y = self._sample_position(self.destination_rng)
            self.requests.append(request)
            self._record_event("arrival", request)
            # Starting service in another process lets arrivals continue while
            # customers wait for drivers or receive service.
            self.env.process(self.customer_process(request))

    def customer_process(
        self, request: RideRequest
    ) -> Generator[simpy.events.Event, None, None]:
        """Wait until assignment or patience expiry, then serve or abandon."""
        deadline = request.arrival_time + request.patience_time
        driver_request = self.driver_pool.request()
        self._resource_requests[driver_request] = request
        try:
            with driver_request:
                # This event succeeds now if capacity is free. Otherwise,
                # SimPy queues it in FIFO order until a driver is released.
                patience_expired = self.env.timeout(request.patience_time)
                result = yield driver_request | patience_expired

                # Ties belong to expiry, including grants at the deadline.
                if driver_request not in result or self.env.now >= deadline:
                    request.abandonment_time = self.env.now
                    request.status = "abandoned"
                    self._record_event("abandonment", request)
                    # Context exit cancels a pending request, or releases a
                    # slot granted during a same-time event race.
                    return

                self._assign_driver(request)
                request.service_start_time = self.env.now
                request.status = "in_service"
                self._record_event("driver_assignment", request)

                # Patience no longer applies. Hold the slot through both stages.
                yield self.env.process(self.provide_service(request))
                request.completion_time = self.env.now
                request.status = "completed"
                self._record_event("trip_completion", request)
                self._release_driver(request)
            # Context exit releases the driver for the next waiting customer.
        finally:
            # A failed service must not leak the named reservation. Do not
            # fabricate a normal release event for an invalid, discarded run.
            if request.assigned_driver_id is not None:
                driver = self._drivers[request.assigned_driver_id]
                if driver.assigned_request_id == request.request_id:
                    self._release_driver(request, record=False)
            del self._resource_requests[driver_request]

    @property
    def drivers(self) -> tuple[Driver, ...]:
        """ID-ordered immutable snapshots; refresh this view after later events."""
        return tuple(self._drivers.values())

    @property
    def initial_drivers(self) -> tuple[Driver, ...]:
        return self._initial_drivers

    def _sample_position(self, rng: random.Random) -> tuple[float, float]:
        return (rng.uniform(0.0, self.config.city_width),
                rng.uniform(0.0, self.config.city_height))

    @property
    def available_drivers(self) -> tuple[Driver, ...]:
        return tuple(driver for driver in self.drivers if driver.is_available)

    @property
    def busy_drivers(self) -> tuple[Driver, ...]:
        return tuple(driver for driver in self.drivers if not driver.is_available)

    @property
    def driver_history(self) -> tuple[DriverEvent, ...]:
        return tuple(self._driver_history)

    def _assign_driver(self, request: RideRequest) -> None:
        # Called only after a valid FIFO capacity grant; no yield until reserved.
        if self.config.dispatch_policy == "nearest":
            driver = select_nearest_driver(self.drivers, request.pickup_x, request.pickup_y)
        else:
            driver = select_random_driver(self.drivers, self.dispatch_rng)
        self._drivers[driver.driver_id] = replace(
            driver, assigned_request_id=request.request_id
        )
        request.assigned_driver_id = driver.driver_id
        self._record_driver_event("driver_assignment", driver.driver_id, request)

    def _release_driver(self, request: RideRequest, *, record: bool = True) -> None:
        driver = self._drivers[request.assigned_driver_id]
        self._drivers[driver.driver_id] = replace(
            driver, assigned_request_id=None,
            x=request.destination_x if record else driver.x,
            y=request.destination_y if record else driver.y,
        )
        if record:
            self._record_driver_event("driver_release", driver.driver_id, request)

    def _record_driver_event(self, kind: str, driver_id: int, request: RideRequest) -> None:
        driver = self._drivers[driver_id]
        self._driver_history.append(DriverEvent(
            len(self._driver_history), self.env.now, kind,
            driver_id, request.request_id, driver.x, driver.y,
        ))

    def provide_service(
        self, request: RideRequest
    ) -> Generator[simpy.events.Timeout, None, None]:
        """Run pickup then trip while the customer process holds its driver."""
        request.pickup_start_time = self.env.now
        request.pickup_duration = self.pickup_rng.uniform(
            self.config.pickup_min_minutes, self.config.pickup_max_minutes
        )
        yield self.env.timeout(request.pickup_duration)
        request.pickup_completion_time = self.env.now

        request.trip_start_time = self.env.now
        self._record_event("pickup_completion", request)
        try:
            request.trip_duration = self.trip_rng.lognormvariate(
                self.config.trip_mu, self.config.trip_sigma
            )
        except OverflowError as error:
            raise ValueError("Trip sample overflowed; check trip parameters.") from error
        # Extreme log-scale parameters can underflow or overflow in floating
        # point. Fail clearly rather than schedule a zero or infinite trip.
        if not isfinite(request.trip_duration) or request.trip_duration <= 0:
            raise ValueError("Sampled trip duration must be finite and positive.")
        yield self.env.timeout(request.trip_duration)
        # The parent records completion and releases the driver at this time.

    @property
    def waiting_requests(self) -> tuple[RideRequest, ...]:
        """Current customers in actual Resource FIFO order; read-only view."""
        return tuple(self._resource_requests[event] for event in self.driver_pool.queue)

    @property
    def busy_driver_count(self) -> int:
        """Occupied Resource slots; inspect at settled simulation times."""
        return self.driver_pool.count

    def _record_event(
        self, event_type: EventType, request: RideRequest | None = None
    ) -> None:
        """Maintain logical counts and append raw state, without computing metrics."""
        if event_type == "arrival":
            self._counts["waiting"] += 1
        elif event_type == "driver_assignment":
            self._counts["waiting"] -= 1
            self._counts["in_service"] += 1
        elif event_type == "abandonment":
            self._counts["waiting"] -= 1
            self._counts["abandoned"] += 1
        elif event_type == "trip_completion":
            self._counts["in_service"] -= 1
            self._counts["completed"] += 1
        waiting = self._counts["waiting"]
        busy = self._counts["in_service"]
        self.event_history.append(SimulationEvent(
            sequence=len(self.event_history), time=self.env.now,
            event_type=event_type,
            request_id=None if request is None else request.request_id,
            request_status=None if request is None else request.status,
            service_stage=None if request is None else request.service_stage,
            arrivals=len(self.requests), waiting=waiting, in_system=waiting + busy,
            busy_drivers=busy, completed=self._counts["completed"],
            abandoned=self._counts["abandoned"],
        ))

    def validate_invariants(self) -> None:
        """Raise RuntimeError for inconsistent results at a settled run boundary."""
        def require(condition: bool, message: str) -> None:
            if not condition:
                raise RuntimeError(f"Simulation invariant failed: {message}")

        counts = Counter(request.status for request in self.requests)
        require(set(counts) <= {"waiting", "in_service", "completed", "abandoned"},
                "unknown request status")
        require(sum(counts.values()) == len(self.requests), "request conservation")
        require(counts == self._counts, "history counts disagree with request states")
        require([r.request_id for r in self.requests] == list(range(1, len(self.requests) + 1)),
                "duplicate, missing, or reordered request IDs")
        queued = list(self.driver_pool.queue)
        held = list(self.driver_pool.users)
        require(set(self._resource_requests) == set(queued + held),
                "orphaned resource request or leaked driver slot")
        require(list(self.waiting_requests) == [r for r in self.requests if r.status == "waiting"],
                "FIFO queue membership disagrees with waiting states")
        require({self._resource_requests[event].request_id for event in held}
                == {r.request_id for r in self.requests if r.status == "in_service"},
                "driver holders disagree with active requests")
        require(len(held) == counts["in_service"] <= self.config.fleet_size,
                "busy driver count or capacity")

        for request in self.requests:
            label = f"request {request.request_id}"
            require(isfinite(request.arrival_time) and 0 <= request.arrival_time < self.env.now,
                    f"{label}: invalid arrival")
            require(isfinite(request.patience_time) and request.patience_time >= 0,
                    f"{label}: invalid patience")
            deadline = request.arrival_time + request.patience_time
            if request.status in {"waiting", "abandoned"}:
                require(all(value is None for value in (
                    request.service_start_time, request.completion_time,
                    request.pickup_start_time, request.pickup_completion_time,
                    request.trip_start_time, request.pickup_duration, request.trip_duration,
                )), f"{label}: unassigned customer entered service")
                if request.status == "waiting":
                    require(request.abandonment_time is None and deadline >= self.env.now,
                            f"{label}: expired waiting customer")
                else:
                    require(request.abandonment_time is not None
                            and isclose(request.abandonment_time, deadline)
                            and request.abandonment_time < self.env.now,
                            f"{label}: invalid abandonment")
                continue

            start = request.service_start_time
            require(start is not None and request.arrival_time <= start < deadline
                    and start < self.env.now and request.abandonment_time is None,
                    f"{label}: invalid assignment")
            require(request.pickup_start_time == start
                    and request.pickup_duration is not None
                    and self.config.pickup_min_minutes <= request.pickup_duration
                    <= self.config.pickup_max_minutes,
                    f"{label}: invalid pickup start or duration")
            pickup_end = request.pickup_completion_time
            if pickup_end is None:
                require(request.status == "in_service" and request.completion_time is None
                        and request.trip_start_time is None and request.trip_duration is None
                        and start + request.pickup_duration >= self.env.now,
                        f"{label}: invalid unfinished pickup")
                continue
            require(start < pickup_end == request.trip_start_time < self.env.now
                    and isclose(pickup_end - start, request.pickup_duration)
                    and request.trip_duration is not None
                    and isfinite(request.trip_duration) and request.trip_duration > 0,
                    f"{label}: invalid pickup completion or trip start")
            end = request.completion_time
            if request.status == "in_service":
                require(end is None and pickup_end + request.trip_duration >= self.env.now,
                        f"{label}: invalid unfinished trip")
            else:
                require(end is not None and pickup_end < end < self.env.now
                        and isclose(end - pickup_end, request.trip_duration),
                        f"{label}: invalid trip completion")

        previous_time = 0.0
        for sequence, event in enumerate(self.event_history):
            require(event.sequence == sequence and previous_time <= event.time <= self.env.now,
                    "history order or time")
            require(min(event.waiting, event.busy_drivers, event.completed, event.abandoned) >= 0
                    and event.busy_drivers <= self.config.fleet_size
                    and event.in_system == event.waiting + event.busy_drivers
                    and event.arrivals == event.in_system + event.completed + event.abandoned,
                    "history conservation or capacity")
            previous_time = event.time
        final = self.event_history[-1]
        require(final.arrivals == len(self.requests), "final history arrival count")
        require((final.waiting, final.busy_drivers, final.completed, final.abandoned)
                == (counts["waiting"], counts["in_service"], counts["completed"], counts["abandoned"]),
                "final history snapshot disagrees with results")
        self._validate_dispatch_invariants()

    def _validate_dispatch_invariants(self) -> None:
        """Reconcile named ownership, locations, and the assignment/release log."""
        def require(condition: bool, message: str) -> None:
            if not condition:
                raise RuntimeError(f"Simulation invariant failed: {message}")

        def valid_position(x: float, y: float) -> bool:
            return all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       and isfinite(value) and 0 <= value <= limit
                       for value, limit in ((x, self.config.city_width),
                                            (y, self.config.city_height)))

        ids = set(range(1, self.config.fleet_size + 1))
        require(set(self._drivers) == ids
                and all(key == driver.driver_id for key, driver in self._drivers.items()),
                "driver identities or fleet size")
        require([driver.driver_id for driver in self.initial_drivers] == sorted(ids)
                and all(driver.is_available for driver in self.initial_drivers),
                "initial driver identities or assignments")
        require(all(valid_position(driver.x, driver.y)
                    for driver in (*self.initial_drivers, *self.drivers)), "driver coordinates")

        records = {request.request_id: request for request in self.requests}
        expected_busy = {}
        for request in self.requests:
            require(valid_position(request.pickup_x, request.pickup_y)
                    and valid_position(request.destination_x, request.destination_y),
                    f"request {request.request_id}: coordinates")
            if request.status in {"waiting", "abandoned"}:
                require(request.assigned_driver_id is None, "unassigned request has driver identity")
            else:
                require(request.assigned_driver_id in ids, "assigned request has invalid driver identity")
                if request.status == "in_service":
                    require(request.assigned_driver_id not in expected_busy,
                            "driver serves multiple requests")
                    expected_busy[request.assigned_driver_id] = request.request_id
        actual_busy = {driver.driver_id: driver.assigned_request_id
                       for driver in self.drivers if not driver.is_available}
        require(actual_busy == expected_busy and len(actual_busy) == self.driver_pool.count,
                "named drivers disagree with active requests or Resource")

        # Reconstruct positions and ownership without trusting final driver state
        # or maintaining a second mutable availability pool.
        positions = {driver.driver_id: (driver.x, driver.y) for driver in self.initial_drivers}
        active = {}
        assigned = set()
        released = set()
        previous = 0.0
        for sequence, event in enumerate(self._driver_history):
            require(event.sequence == sequence and isfinite(event.time)
                    and previous <= event.time < self.env.now, "driver history chronology")
            require(event.driver_id in ids and event.request_id in records,
                    "driver history identity")
            require(valid_position(event.x, event.y), "driver history coordinates")
            request = records[event.request_id]
            require(request.assigned_driver_id == event.driver_id, "driver history assignment mismatch")
            if event.event_type == "driver_assignment":
                require(event.driver_id not in active and event.request_id not in assigned
                        and event.time == request.driver_assignment_time,
                        "duplicate driver assignment or invalid assignment time")
                require((event.x, event.y) == positions[event.driver_id],
                        "assignment position differs from last known driver position")
                active[event.driver_id] = event.request_id
                assigned.add(event.request_id)
            else:
                require(event.event_type == "driver_release"
                        and active.get(event.driver_id) == event.request_id
                        and event.request_id not in released
                        and event.time == request.completion_time,
                        "driver release without matching completion/assignment")
                require((event.x, event.y) == (request.destination_x, request.destination_y),
                        "driver release is not at destination")
                positions[event.driver_id] = (event.x, event.y)
                del active[event.driver_id]
                released.add(event.request_id)
            previous = event.time
        require(assigned == {r.request_id for r in self.requests if r.assigned_driver_id is not None}
                and released == {r.request_id for r in self.requests if r.status == "completed"},
                "missing driver assignment or release history")
        require(active == actual_busy and positions == {d.driver_id: (d.x, d.y) for d in self.drivers},
                "driver history disagrees with final ownership or position")

    def run(self) -> None:
        """Advance to the configured horizon; events at that time are excluded."""
        self.env.run(until=self.config.duration_minutes)
        self._record_event("simulation_end")
        self.validate_invariants()
