import urllib.request
import re
from typing import Optional
from core.vendors.base import BaseVendorPlugin
from core.vendors.base import ProgressCallback
from core.models import AssetRecord, VendorType

class DellVendorPlugin(BaseVendorPlugin):
    @property
    def vendor_type(self) -> VendorType:
        return VendorType.DELL

    def fetch_warranty(
        self, serial_number: str, progress_callback: Optional[ProgressCallback] = None
    ) -> AssetRecord:
        clean_tag = serial_number.upper()

        model = "Unknown"
        try:
            url = f"https://www.dell.com/support/home/en-us/product-support/servicetag/{clean_tag}/overview"
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                model_match = re.search(r'"productName"\s*:\s*"([^"]+)"', html)
                if model_match:
                    model = model_match.group(1).strip()
        except Exception as exc:
            return self.lookup_failed(
                clean_tag,
                f"{type(exc).__name__}: {exc}",
                model_name=model,
            )

        return self.lookup_failed(
            clean_tag,
            "Dell product identification succeeded, but verified warranty "
            "dates were not available.",
            model_name=model,
        )
