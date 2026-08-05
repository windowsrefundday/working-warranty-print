import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType


class WarrantyCache:
    """Persistent, concurrency-safe SQLite cache for verified warranty records.

    Records are keyed by (vendor, serial). Only successful, verified live results
    should be stored. Callers are responsible for recalculating warranty status
    from the expiration date when a cached record is read.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS warranty_cache (
                    vendor TEXT NOT NULL,
                    serial TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    warranty_status TEXT NOT NULL,
                    ship_date TEXT NOT NULL,
                    expiration_date TEXT NOT NULL,
                    entitlements TEXT NOT NULL,
                    source_confidence TEXT NOT NULL,
                    raw_source TEXT NOT NULL,
                    source_verified_at TEXT NOT NULL,
                    lookup_error TEXT,
                    PRIMARY KEY (vendor, serial)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        # SQLite serializes access across threads by default. Each public method
        # creates a fresh short-lived connection and explicitly closes it.
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, vendor: str, serial: str) -> Optional[AssetRecord]:
        serial = serial.strip().upper()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT model_name, warranty_status, ship_date, expiration_date,
                       entitlements, source_confidence, raw_source,
                       source_verified_at, lookup_error
                FROM warranty_cache
                WHERE vendor = ? AND serial = ?
                """,
                (vendor, serial),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return self._row_to_record(vendor, serial, row)

    def set(self, record: AssetRecord) -> None:
        if record.source_confidence != SourceConfidence.VERIFIED_LIVE:
            raise ValueError(
                "Only VERIFIED_LIVE records may be cached; got "
                f"{record.source_confidence}"
            )
        row = self._record_to_row(record)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO warranty_cache (
                    vendor, serial, model_name, warranty_status, ship_date,
                    expiration_date, entitlements, source_confidence, raw_source,
                    source_verified_at, lookup_error
                ) VALUES (
                    :vendor, :serial, :model_name, :warranty_status, :ship_date,
                    :expiration_date, :entitlements, :source_confidence,
                    :raw_source, :source_verified_at, :lookup_error
                )
                ON CONFLICT(vendor, serial) DO UPDATE SET
                    model_name = excluded.model_name,
                    warranty_status = excluded.warranty_status,
                    ship_date = excluded.ship_date,
                    expiration_date = excluded.expiration_date,
                    entitlements = excluded.entitlements,
                    source_confidence = excluded.source_confidence,
                    raw_source = excluded.raw_source,
                    source_verified_at = excluded.source_verified_at,
                    lookup_error = excluded.lookup_error
                """,
                row,
            )
            conn.commit()
        finally:
            conn.close()

    def clear(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM warranty_cache")
            conn.commit()
        finally:
            conn.close()

    def _record_to_row(self, record: AssetRecord) -> dict:
        return {
            "vendor": record.vendor.value,
            "serial": record.serial_number.strip().upper(),
            "model_name": record.model_name,
            "warranty_status": record.warranty_status,
            "ship_date": record.ship_date,
            "expiration_date": record.expiration_date,
            "entitlements": json.dumps(
                [
                    {
                        "service_name": e.service_name,
                        "status": e.status,
                        "start_date": e.start_date,
                        "end_date": e.end_date,
                    }
                    for e in record.entitlements
                ]
            ),
            "source_confidence": record.source_confidence.value,
            "raw_source": record.raw_source,
            "source_verified_at": record.source_verified_at
            or datetime.now().strftime("%Y-%m-%d"),
            "lookup_error": record.lookup_error,
        }

    def _row_to_record(
        self, vendor: str, serial: str, row: tuple
    ) -> AssetRecord:
        (
            model_name,
            warranty_status,
            ship_date,
            expiration_date,
            entitlements_json,
            source_confidence,
            raw_source,
            source_verified_at,
            lookup_error,
        ) = row
        entitlements = [
            Entitlement(
                service_name=e["service_name"],
                status=e["status"],
                start_date=e.get("start_date"),
                end_date=e.get("end_date"),
            )
            for e in json.loads(entitlements_json)
        ]
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType(vendor),
            model_name=model_name,
            warranty_status=warranty_status,
            ship_date=ship_date,
            expiration_date=expiration_date,
            entitlements=entitlements,
            source_confidence=SourceConfidence(source_confidence),
            raw_source=raw_source,
            source_verified_at=source_verified_at,
            lookup_error=lookup_error,
        )
