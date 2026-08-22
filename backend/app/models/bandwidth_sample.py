"""
Bandwidth Sample Model - Time-series snapshots of server-wide VPN throughput
"""
from sqlalchemy import Column, Integer, DateTime, BigInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class BandwidthSample(Base):
    """Periodic snapshot of cumulative server-wide OpenVPN byte counters.

    A background sampler inserts one row every few minutes with the summed
    live cumulative byte counters across all connected clients. Throughput for
    an interval is the delta between two consecutive snapshots. This table backs
    the dashboard "Throughput · últimas 24h" chart.
    """

    __tablename__ = "bandwidth_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # When the snapshot was taken
    recorded_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    # Server-wide cumulative counters at sample time (bytes).
    #   cum_bytes_sent     = server -> clients (download / "saída")
    #   cum_bytes_received = clients -> server (upload / "entrada")
    cum_bytes_sent = Column(BigInteger, default=0)
    cum_bytes_received = Column(BigInteger, default=0)

    # Number of connected clients / tunnels at sample time
    active_clients = Column(Integer, default=0)

    # Which technology this snapshot measures: "openvpn" or "ipsec".
    source = Column(String(16), default="openvpn", server_default="openvpn", nullable=False, index=True)

    def __repr__(self):
        return f"<BandwidthSample {self.recorded_at} clients={self.active_clients}>"
