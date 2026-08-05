from datetime import date
from typing import List, Optional

from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType


def parse_portal_text(clean_sn: str, text: str) -> AssetRecord | None:
    """Parse and validate the first (primary) HP coverage section."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if "Coverage details" not in lines or f"Serial: {clean_sn}" not in lines:
        return None

    coverage_starts = [
        index for index, value in enumerate(lines) if value == "Coverage type"
    ]
    if not coverage_starts:
        return None
    start = coverage_starts[0]
    end = coverage_starts[1] if len(coverage_starts) > 1 else len(lines)
    section = lines[start:end]

    def value_after(label: str) -> Optional[str]:
        try:
            index = section.index(label)
            return section[index + 1]
        except (ValueError, IndexError):
            return None

    model_name = next(
        (
            line for line in lines[:start]
            if line.startswith("HP ") and not line.startswith("HP has checked")
        ),
        None,
    )
    service_type = value_after("Service type")
    status = value_after("Status")
    start_date = value_after("Start date")
    end_date = value_after("End date")
    if not all((model_name, service_type, status, start_date, end_date)):
        return None

    assert model_name is not None
    assert service_type is not None
    assert status is not None
    assert start_date is not None
    assert end_date is not None

    entitlement_names: List[str] = [service_type]
    if "Defective Media Retention" in section:
        entitlement_names.append("Defective Media Retention")
    if "Deliverables" in section:
        deliverables_index = section.index("Deliverables") + 1
        allowed_deliverables = {
            "Material",
            "Onsite Support",
            "HW Problem Diagnosis",
            "Parts and Material provided",
            "Hardware Problem Diagnosis",
            "Initial Setup Assistance",
        }
        entitlement_names.extend(
            value
            for value in section[deliverables_index:]
            if value in allowed_deliverables
        )

    unique_entitlements = list(dict.fromkeys(entitlement_names))
    return AssetRecord(
        serial_number=clean_sn,
        vendor=VendorType.HP,
        model_name=model_name,
        warranty_status=status,
        ship_date=start_date,
        expiration_date=end_date,
        entitlements=[
            Entitlement(
                service_name=name,
                status=status,
                start_date=start_date,
                end_date=end_date,
            )
            for name in unique_entitlements
        ],
        source_confidence=SourceConfidence.VERIFIED_LIVE,
        raw_source="Live HP Warranty Portal",
        source_verified_at=date.today().isoformat(),
    )
