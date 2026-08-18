import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType
from core.vendors.http import open_allowed_https


class LenovoProductResolver:
    """Isolates Lenovo's public product-resolution API endpoint.

    Endpoint: GET https://pcsupport.lenovo.com/us/en/api/v4/mse/getproducts?productId={SERIAL}
    """

    ENDPOINT_URL = "https://pcsupport.lenovo.com/us/en/api/v4/mse/getproducts?productId={serial}"
    WARRANTY_URL = "https://pcsupport.lenovo.com/us/en/products/{product_id}/warranty"

    @classmethod
    def resolve_product(
        cls, serial_number: str, timeout: int = 15
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Resolves a Lenovo serial number to its official Product Id and Product Name.

        Returns:
            (product_id, product_name, error_message)
        """
        clean_sn = serial_number.strip().upper()
        if not re.fullmatch(r"[A-Z0-9-]{1,64}", clean_sn):
            return None, None, "Serial number has invalid characters"

        query = urllib.parse.urlencode({"productId": clean_sn})
        url = f"https://pcsupport.lenovo.com/us/en/api/v4/mse/getproducts?{query}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        try:
            with open_allowed_https(
                req,
                allowed_host="pcsupport.lenovo.com",
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return (
                        None,
                        None,
                        f"Lenovo product endpoint returned HTTP {resp.status}",
                    )
                raw_body = resp.read().decode("utf-8")
        except Exception as exc:
            return None, None, f"Lenovo product resolution failed: {type(exc).__name__}: {exc}"

        try:
            data = json.loads(raw_body)
        except Exception:
            return None, None, "Lenovo product endpoint returned invalid JSON"

        if not isinstance(data, list) or len(data) == 0:
            return None, None, f"No Lenovo product found for serial {clean_sn}"

        matches = [
            item for item in data
            if isinstance(item, dict)
            and item.get("Serial", "").strip().upper() == clean_sn
        ]
        if not matches:
            return None, None, f"Lenovo response serial did not match requested serial {clean_sn}"

        if len(matches) > 1:
            return None, None, f"Ambiguous product resolution for serial {clean_sn}"

        item = matches[0]
        product_id = item.get("Id", "").strip()
        product_name = item.get("Name", "").strip()

        if not product_id:
            return None, None, "Lenovo product resolution returned empty product ID"
        if not product_name:
            return None, None, "Lenovo product resolution returned empty official product name"

        return product_id, product_name, None

    @classmethod
    def fetch_warranty_payload(
        cls, product_id: str, timeout: int = 20
    ) -> Tuple[Optional[str], Optional[str]]:
        """Fetch Lenovo's public warranty document containing ``ds_warranties``.

        This is an ordinary request to the same public product URL; it does not
        proxy browser navigation, intercept routes, or attempt to defeat a
        challenge. The caller still verifies the structured payload strictly.
        """
        if not product_id:
            return None, "Lenovo warranty lookup received an empty product ID"
        segments = product_id.split("/")
        if any(
            not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", segment)
            or segment in {".", ".."}
            for segment in segments
        ):
            return None, "Lenovo product ID contains invalid path components"
        encoded_product_id = "/".join(
            urllib.parse.quote(segment, safe="") for segment in segments
        )
        url = cls.WARRANTY_URL.format(product_id=encoded_product_id)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with open_allowed_https(
                request,
                allowed_host="pcsupport.lenovo.com",
                timeout=timeout,
            ) as response:
                if response.status != 200:
                    return None, f"Lenovo warranty endpoint returned HTTP {response.status}"
                return response.read().decode("utf-8"), None
        except Exception as exc:
            return None, f"Lenovo warranty retrieval failed: {type(exc).__name__}: {exc}"


def parse_lenovo_warranty(
    requested_serial: str,
    payload: Any,
    product_name_hint: Optional[str] = None,
) -> Optional[AssetRecord]:
    """Pure parser that converts Lenovo warranty payload into a verified AssetRecord.

    Accepts:
        - dict: window.ds_warranties object
        - str: JSON string or HTML containing the structured ``ds_warranties`` payload
    """
    clean_sn = requested_serial.strip().upper()
    if not clean_sn:
        return None

    data: Optional[Dict[str, Any]] = None

    if isinstance(payload, dict):
        data = payload
    elif isinstance(payload, str):
        raw_str = payload.strip()
        # Try direct JSON parse
        if raw_str.startswith("{") and raw_str.endswith("}"):
            try:
                data = json.loads(raw_str)
            except Exception:
                data = None

        # Try regex extraction of window.ds_warranties
        if data is None and "ds_warranties" in raw_str:
            match = re.search(
                r'var\s+ds_warranties\s*=\s*window\.ds_warranties\s*\|\|\s*(\{.*?\});\s*(?:var|</script>|\n)',
                raw_str,
                re.DOTALL,
            )
            if match:
                try:
                    data = json.loads(match.group(1))
                except Exception:
                    data = None

    if data is not None:
        return _parse_ds_warranties_dict(clean_sn, data, product_name_hint)

    return None


def _parse_ds_warranties_dict(
    clean_sn: str,
    data: Dict[str, Any],
    product_name_hint: Optional[str] = None,
) -> Optional[AssetRecord]:
    # Validate exact serial match
    returned_sn = (
        data.get("Serial")
        or data.get("BaseProductId")
        or ""
    ).strip().upper()

    if returned_sn != clean_sn:
        return None

    # Model name
    model_name = (data.get("ProductName") or product_name_hint or "").strip()
    if not model_name or model_name.lower() in {"lenovo device", "unknown lenovo device"}:
        return None

    mtm = (data.get("MTM") or data.get("Mode") or "").strip()
    if mtm and mtm not in model_name:
        # Keep full model name intact, append model code if helpful
        model_name = f"{model_name}"

    # Dates & Entitlements
    base_warranties = data.get("BaseWarranties") or []
    upma_warranties = data.get("UpmaWarranties") or []
    all_warranties = base_warranties + upma_warranties

    if not all_warranties:
        return None

    # Ship date / Start date
    ship_date = data.get("Shiped") or data.get("ManufactureDate") or "Unknown"

    # Determine latest expiration date and active status
    latest_expiration: Optional[str] = None
    latest_exp_date: Optional[date] = None
    statuses: List[str] = []

    entitlement_list: List[Entitlement] = []
    seen_services = set()

    for item in all_warranties:
        if not isinstance(item, dict):
            continue
        raw_status = item.get("StatusV2")
        if not isinstance(raw_status, str) or not raw_status.strip():
            continue
        item_status = raw_status.strip()
        normalized_status = item_status.lower()
        if normalized_status in ("no coverage", "no_coverage", "invalid"):
            continue
        if normalized_status not in {"active", "in warranty", "coverage expiring", "expired"}:
            continue

        end_str = item.get("End") or item.get("EndDate") or ""
        start_str = item.get("Start") or ship_date
        parsed_d = _parse_date_string(end_str) if isinstance(end_str, str) else None
        name = (item.get("Name") or item.get("Description") or "").strip()
        if not name or parsed_d is None:
            continue

        expected_active = parsed_d >= date.today()
        if normalized_status in {"active", "in warranty", "coverage expiring"} and not expected_active:
            return None
        if normalized_status == "expired" and expected_active:
            return None

        statuses.append(normalized_status)
        if latest_exp_date is None or parsed_d > latest_exp_date:
            latest_exp_date = parsed_d
            latest_expiration = end_str
        delivery_type = item.get("DeliveryType") or ""

        # Build normalized entitlements
        service_name = name
        if delivery_type == "on_site" or "on-site" in name.lower() or "onsite" in name.lower():
            if "Onsite Support" not in seen_services:
                entitlement_list.append(
                    Entitlement(
                        service_name="Onsite Support",
                        status=item_status,
                        start_date=start_str if start_str != "Unknown" else None,
                        end_date=end_str if end_str else None,
                    )
                )
                seen_services.add("Onsite Support")

        if service_name not in seen_services and service_name != "Onsite Support":
            entitlement_list.append(
                Entitlement(
                    service_name=service_name,
                    status=item_status,
                    start_date=start_str if start_str != "Unknown" else None,
                    end_date=end_str if end_str else None,
                )
            )
            seen_services.add(service_name)

    if not latest_expiration or latest_exp_date is None or not entitlement_list:
        return None

    # Normalize overall warranty status
    today = date.today()
    days_remaining = (latest_exp_date - today).days
    expected_status = (
        "Expired" if days_remaining < 0
        else "Coverage Expiring" if days_remaining <= 30
        else "Active"
    )
    has_active_status = any(
        status in {"active", "in warranty", "coverage expiring"} for status in statuses
    )
    if expected_status == "Expired" and has_active_status:
        return None
    if expected_status != "Expired" and not has_active_status:
        return None
    warranty_status = expected_status

    return AssetRecord(
        serial_number=clean_sn,
        vendor=VendorType.LENOVO,
        model_name=model_name,
        warranty_status=warranty_status,
        ship_date=ship_date,
        expiration_date=latest_expiration,
        entitlements=entitlement_list,
        source_confidence=SourceConfidence.VERIFIED_LIVE,
        raw_source="Live Lenovo Warranty Portal",
        source_verified_at=date.today().isoformat(),
    )


def _parse_date_string(d_str: str) -> Optional[date]:
    d_str = d_str.strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    return None
