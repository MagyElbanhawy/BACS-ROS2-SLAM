"""Strict scheduler logging schema."""
SCHEDULER_FIELDS = ("session", "run", "seq", "policy", "robot", "t_gen_ns", "t_selected_ns",
                    "t_tx_ns", "t_rx_ns", "deferral_ns", "channel", "rssi_dbm", "snr_db", "payload_hex")
__all__ = ["SCHEDULER_FIELDS"]
