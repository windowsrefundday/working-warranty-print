# Developer Guide: How to Add a New Vendor Warranty Plugin

This modular warranty engine allows you to easily add new hardware manufacturers (e.g., Asus, Acer, Cisco, Microsoft Surface) without modifying core application code.

---

## Step 1: Create a New Plugin File

Create a new Python file in `core/vendors/` (e.g., `asus.py`).

```python
from core.vendors.base import BaseVendorPlugin
from core.models import AssetRecord, Entitlement, VendorType

class AsusVendorPlugin(BaseVendorPlugin):
    @property
    def vendor_type(self) -> VendorType:
        # Return VendorType or string identifier
        return VendorType.GENERIC

    def fetch_warranty(self, serial_number: str) -> AssetRecord:
        clean_sn = serial_number.upper()

        # 1. Place custom lookup / scraping / API code here
        # 2. Return an AssetRecord instance
        return AssetRecord(
            serial_number=clean_sn,
            vendor=VendorType.GENERIC,
            model_name=f"Asus TEST MODEL ({clean_sn})",
            warranty_status="Active",
            ship_date="2099-01-01",
            expiration_date="2100-01-01",
            entitlements=[
                Entitlement(service_name="TEST-PREMIUM-SUPPORT", status="Active")
            ],
            raw_source="Asus Warranty Portal"
        )
```

---

## Step 2: Register Plugin in `core/engine.py`

Import your class in `core/engine.py` and add it to `self.plugins`:

```python
from core.vendors.asus import AsusVendorPlugin

# Inside WarrantyEngine.__init__:
self.plugins[VendorType.ASUS] = AsusVendorPlugin()
```

---

## Step 3: Add Serial Pattern Rule in `core/scanner.py`

In `core/scanner.py`, add regex pattern logic to auto-detect your new vendor by serial format:

```python
if len(cleaned) == 15 and cleaned.startswith('NS'):
    return VendorType.ASUS
```
