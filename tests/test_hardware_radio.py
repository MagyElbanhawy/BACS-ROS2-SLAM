import csv
import io
import queue
import time
from pathlib import Path

import pytest

from analysis.physical.pipeline import validate_scheduler
from analysis.physical.radio_join import join_run
from ros2_ws.src.bacs_scheduler.bacs_scheduler.receiver_core import RECEIVED_FIELDS, received_row
from ros2_ws.src.bacs_scheduler.bacs_scheduler.rylr998 import (
    ON_AIR_BYTES, ConstraintPayload, Rylr998Link, TraceWriter, parse_rcv, send_command)
from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import DutyCycleBudget, Scheduler
from ros2_ws.src.bacs_scheduler.bacs_scheduler.sender_core import (
    DROPPED_AGE, RADIO_ERROR, RADIO_TIMEOUT, REJECTED_TRUST, SENT, SenderCore)

ROBOTS = ["limo01", "limo02"]


def payload(seq: int = 7) -> ConstraintPayload:
    return ConstraintPayload(seq, 0, 1, 1.5, -0.25, 0.1, 0.01, 0.02, 0.003, 0.75, 0.5, 40, 12, 123456)


def test_payload_is_52_bytes_on_air_and_round_trips() -> None:
    text = payload().encode()
    assert len(text) == ON_AIR_BYTES and "," not in text and "=" not in text
    decoded = ConstraintPayload.decode(text)
    assert decoded.seq == 7 and decoded.robot_j == 1 and decoded.dx == pytest.approx(1.5)
    assert decoded.predicted_trust == pytest.approx(0.75, abs=1e-3)
    assert (decoded.kf_i, decoded.kf_j) == (40, 12) and decoded.var_theta == pytest.approx(0.003, rel=1e-3)


def test_parse_rcv_uses_declared_length() -> None:
    packet = parse_rcv("+RCV=1,5,ab,cd,-67,9")
    assert (packet.address, packet.data, packet.rssi_dbm, packet.snr_db) == (1, "ab,cd", -67, 9)
    assert parse_rcv("+OK") is None
    with pytest.raises(ValueError):
        send_command(100, "bad\r\n")


class FakeModule:
    """Answers AT+SEND with +OK and can inject a +RCV line."""

    def __init__(self) -> None:
        self.lines: "queue.Queue[bytes]" = queue.Queue()
        self.written: list[str] = []

    def write(self, data: bytes) -> int:
        line = data.decode().strip()
        self.written.append(line)
        self.lines.put(b"+OK\r\n")
        return len(data)

    def readline(self) -> bytes:
        try:
            return self.lines.get(timeout=0.05)
        except queue.Empty:
            return b""


def test_link_timestamps_responses_and_routes_receptions() -> None:
    module, trace, received = FakeModule(), io.StringIO(), []
    link = Rylr998Link(module, TraceWriter(trace), on_receive=lambda t, p: received.append((t, p)))
    t_cmd, t_ok, response = link.command(send_command(100, payload().encode()))
    assert response == "+OK" and t_ok >= t_cmd
    module.lines.put(f"+RCV=1,52,{payload().encode()},-80,7\r\n".encode())
    deadline = time.time() + 2
    while not received and time.time() < deadline:
        time.sleep(0.01)
    link.close()
    assert received and received[0][1].rssi_dbm == -80
    assert [row.split(",")[1] for row in trace.getvalue().splitlines()[1:]] == ["tx", "rx", "rx"]


class FakeRadio:
    def __init__(self, clock, responses=None) -> None:
        self.clock, self.responses, self.sent = clock, list(responses or []), []

    def command(self, line: str, timeout_s: float = 2.0):
        self.sent.append(line)
        response = self.responses.pop(0) if self.responses else "+OK"
        t = self.clock()
        return t, (None if response == "TIMEOUT" else t + 1_000_000), response


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000_000_000

    def __call__(self) -> int:
        return self.t


def candidate(seq: int, t_gen: int, trust: float = 0.9, info: float = 0.5) -> dict:
    return {"seq": seq, "robot_i": "limo01", "robot_j": "limo02", "t_gen_ns": t_gen, "predicted_trust": trust,
            "information_score": info, "pair_constraints": 0, "kf_i": seq, "kf_j": seq + 1, "dx": 1, "dy": 0, "dtheta": 0,
            "var_x": 0.01, "var_y": 0.01, "var_theta": 0.001}


def make_core(policy: str, clock: Clock, radio: FakeRadio, log: io.StringIO) -> SenderCore:
    return SenderCore(session="HWS-101-" + policy, run=1, policy=policy, robot="limo01", robots=ROBOTS, radio=radio,
                      destination=100, log=log, clock_ns=clock, scheduler=Scheduler(policy, DutyCycleBudget()))


def rows(log: io.StringIO) -> list[dict]:
    return list(csv.DictReader(io.StringIO(log.getvalue())))


def test_fifo_order_budget_and_trust_gate() -> None:
    clock, log = Clock(), io.StringIO()
    radio = FakeRadio(clock)
    core = make_core("FIFO", clock, radio, log)
    for seq in range(10):
        core.enqueue(candidate(seq, clock.t - (10 - seq) * 1_000_000_000, info=seq / 10))
    core.enqueue(candidate(99, clock.t, trust=0.1))
    statuses = []
    for _ in range(10):
        statuses.append(core.tick()); clock.t += 1_000_000_000
    # 1 % of 60 s = 0.6 s budget, 102.7 ms per packet -> 5 packets, oldest first
    assert statuses.count(SENT) == 5 and statuses[5:] == [None] * 5
    sent = [r for r in rows(log) if r["status"] == SENT]
    assert [int(r["seq"]) for r in sent] == [0, 1, 2, 3, 4]
    assert all(int(r["t_selected_ns"]) - int(r["t_gen_ns"]) > 0 for r in sent)
    assert next(r for r in rows(log) if r["seq"] == "99")["status"] == REJECTED_TRUST


def test_bacs_plus_prefers_informative_and_drops_old() -> None:
    clock, log = Clock(), io.StringIO()
    core = make_core("BACS+", clock, FakeRadio(clock), log)
    core.enqueue(candidate(1, clock.t, info=0.1))
    core.enqueue(candidate(2, clock.t, info=0.9))
    core.enqueue(candidate(3, clock.t - 700_000_000_000, info=1.0))  # older than 600 s
    assert core.tick() == SENT
    by_seq = {r["seq"]: r["status"] for r in rows(log)}
    assert by_seq == {"3": DROPPED_AGE, "2": SENT}
    core.close()
    assert {r["seq"]: r["status"] for r in rows(log)}["1"] == "PENDING_AT_END"


def test_timeout_is_charged_to_budget_but_error_is_not() -> None:
    clock, log = Clock(), io.StringIO()
    core = make_core("FIFO", clock, FakeRadio(clock, ["+ERR=4", "TIMEOUT"]), log)
    for seq in range(2):
        core.enqueue(candidate(seq, clock.t - 1))
    assert [core.tick(), core.tick()] == [RADIO_ERROR, RADIO_TIMEOUT]
    assert core.scheduler.budget.used_s(clock.t / 1e9) == pytest.approx(core.airtime_s)


def test_join_keeps_lost_packets_blank_and_passes_validation(tmp_path: Path) -> None:
    clock = Clock()
    run_dir = tmp_path / "HWS-101-FIFO" / "run_01"; run_dir.mkdir(parents=True)
    with (run_dir / "candidates_limo01.csv").open("w", newline="") as log:
        core = make_core("FIFO", clock, FakeRadio(clock), log)
        for seq in range(3):
            core.enqueue(candidate(seq, clock.t - 5_000_000_000))
        for _ in range(3):
            core.tick(); clock.t += 1_000_000_000
        core.close()
    with (run_dir / "received_server.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECEIVED_FIELDS); writer.writeheader()
        for seq in (0, 2):  # packet 1 is lost on air
            text = ConstraintPayload(seq, 0, 1, 1, 0, 0, .01, .01, .001, .9, .5, 3, 4, 0).encode()
            writer.writerow(received_row("HWS-101-FIFO", 1, clock.t + seq, parse_rcv(f"+RCV=1,52,{text},-90,5"),
                                         {1: "limo01"}, ROBOTS))
    joined, report = join_run(run_dir)
    assert report == {"candidates": 3, "sent": 3, "received": 2, "received_unmatched": 0,
                      "received_duplicates": 0, "received_undecodable": 0}
    lost = next(r for r in joined if r["seq"] == "1")
    assert lost["t_rx_ns"] == 0 and lost["rssi_dbm"] == "" and lost["sent"] == 1
    out = tmp_path / "log.csv"
    from analysis.physical.radio_join import JOINED_FIELDS
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOINED_FIELDS); writer.writeheader(); writer.writerows(joined)
    assert validate_scheduler(out)["status"] == "VALID"


def test_readback_rejects_wrong_bandwidth_code() -> None:
    from ros2_ws.src.bacs_scheduler.bacs_scheduler.rylr998 import (
        configuration_commands, expected_readback, readback_mismatches)
    settings = dict(address=1, network_id=18)
    good = {"AT+ADDRESS?": "+ADDRESS=1", "AT+NETWORKID?": "+NETWORKID=18", "AT+BAND?": "+BAND=868000000",
            "AT+PARAMETER?": "+PARAMETER=7,7,1,8", "AT+CRFOP?": "+CRFOP=14"}
    replies = [(c, good.get(c, "+OK")) for c in configuration_commands(**settings)]
    assert "AT+PARAMETER=7,7,1,8" in dict(replies)
    assert readback_mismatches(replies, expected_readback(**settings)) == []
    old = [(c, "+PARAMETER=7,0,1,7" if c == "AT+PARAMETER?" else r) for c, r in replies]
    assert readback_mismatches(old, expected_readback(**settings)) == [
        "AT+PARAMETER? -> +PARAMETER=7,0,1,7 (expected +PARAMETER=7,7,1,8)"]
    assert readback_mismatches([(c, "+ERR=4" if c == "AT+BAND=868000000" else r) for c, r in replies],
                               expected_readback(**settings)) == ["AT+BAND=868000000 -> +ERR=4"]


@pytest.mark.parametrize("ok_ms, verdict", [(104.0, "OK_AFTER_TRANSMISSION"), (7.0, "OK_ON_ACCEPT"),
                                            (50.0, "AMBIGUOUS")])
def test_calibration_verdict(ok_ms: float, verdict: str) -> None:
    from ros2_ws.src.bacs_scheduler.bacs_scheduler.calibration import summarise, uart_time_s
    rows = [{"i": i, "t_cmd_ns": 0, "t_ok_ns": int((ok_ms + i % 3) * 1e6), "response": "+OK",
             "t_rcv_ns": int(112e6) if i != 5 else "", "rssi_dbm": -40, "snr_db": 10} for i in range(20)]
    summary = summarise(rows, airtime_s=0.1027, command_chars=69)
    assert summary["verdict"] == verdict and summary["received"] == 19 and summary["ok"] == 20
    assert summary["uart_command_s"] == pytest.approx(uart_time_s(69)) == pytest.approx(0.00616, abs=1e-5)
