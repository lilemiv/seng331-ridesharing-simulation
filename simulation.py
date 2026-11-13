"""Core engine: FIFO assignment, patience, uniform pickup, lognormal trips."""

from collections import Counter
from collections.abc import Generator
from dataclasses import dataclass
from math import isclose, isfinite
import random
from typing import Literal

import simpy

from config import SimulationConfig


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
        self.driver_pool = simpy.Resource(self.env, capacity=config.fleet_size)
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

                request.service_start_time = self.env.now
                request.status = "in_service"
                self._record_event("driver_assignment", request)

                # Patience no longer applies. Hold the slot through both stages.
                yield self.env.process(self.provide_service(request))
                request.completion_time = self.env.now
                request.status = "completed"
                self._record_event("trip_completion", request)
            # Context exit releases the driver for the next waiting customer.
        finally:
            del self._resource_requests[driver_request]

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

    def run(self) -> None:
        """Advance to the configured horizon; events at that time are excluded."""
        self.env.run(until=self.config.duration_minutes)
        self._record_event("simulation_end")
        self.validate_invariants()
