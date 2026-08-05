import os
import sys
import subprocess
import shutil
from typing import Dict, List
from core.app_paths import get_app_paths

# Community GitHub Warranty Repositories
COMMUNITY_REPOS = {
    "dell_warranty_stanford": {
        "name": "Stanford Dell Warranty CLI & REST Engine",
        "url": "https://github.com/stanford-rc/dell_warranty.git",
        "package": "dell_warranty",
        "install_cmd": [sys.executable, "-m", "pip", "install", "--upgrade", "dell_warranty"]
    },
    "ps_warranty_cyberdrain": {
        "name": "CyberDrain Multi-Vendor Warranty Engine (Dell, HP, Lenovo)",
        "url": "https://github.com/KelvinTegelaar/PowerShellWarrantyReports.git",
        "target_dir": "ps_warranty"
    },
    "hp_warranty_scraper": {
        "name": "HP Warranty Scraper Engine",
        "url": "https://github.com/s0lil0quy/HPWarrantyScraper.git",
        "target_dir": "hp_warranty_scraper"
    },
    "hp_warranty_getter": {
        "name": "HP Warranty Getter Engine (Selenium/Playwright)",
        "url": "https://github.com/Alex33856/hp-warranty-getter.git",
        "target_dir": "hp_warranty_getter"
    }
}

class GitHubEngineDownloader:
    """Automated Downloader & Manager for Open-Source GitHub Warranty Engines."""

    def __init__(self, external_dir: str | None = None):
        self.external_dir = external_dir or str(
            get_app_paths().data_dir / "external-engines"
        )

    def update_all_engines(self) -> Dict[str, bool]:
        """Downloads/updates all community warranty engines from GitHub."""
        os.makedirs(self.external_dir, exist_ok=True)
        results = {}
        print("\n" + "="*60)
        print("  AUTOMATED GITHUB WARRANTY ENGINE DOWNLOADER & UPDATER")
        print("="*60)

        for key, repo_info in COMMUNITY_REPOS.items():
            print(f"\n[*] Processing: {repo_info['name']}...")

            # 1. Try pip installation if package is specified
            if "package" in repo_info:
                try:
                    res = subprocess.run(repo_info["install_cmd"], capture_output=True, text=True, timeout=30)
                    if res.returncode == 0:
                        print(f" -> SUCCESS: Installed/Updated Python package '{repo_info['package']}' via pip.")
                        results[key] = True
                        continue
                    else:
                        print(f" -> PIP WARN: {res.stderr.strip()[:100]}")
                except Exception as e:
                    print(f" -> PIP ERR: {e}")

            # 2. Try git clone/pull into external_dir
            if "url" in repo_info and "target_dir" in repo_info:
                target_path = os.path.join(self.external_dir, repo_info["target_dir"])
                try:
                    if os.path.exists(target_path) and os.path.exists(os.path.join(target_path, ".git")):
                        # Git pull update
                        res = subprocess.run(["git", "-C", target_path, "pull"], capture_output=True, text=True, timeout=20)
                        print(f" -> SUCCESS: Updated git repository in {target_path}")
                        results[key] = True
                    else:
                        # Git clone
                        if os.path.exists(target_path):
                            shutil.rmtree(target_path)
                        res = subprocess.run(["git", "clone", "--depth", "1", repo_info["url"], target_path], capture_output=True, text=True, timeout=30)
                        if res.returncode == 0:
                            print(f" -> SUCCESS: Cloned GitHub repository to {target_path}")
                            results[key] = True
                        else:
                            print(f" -> GIT ERROR: {res.stderr.strip()[:100]}")
                            results[key] = False
                except Exception as e:
                    print(f" -> DOWNLOAD FAILED: {e}")
                    results[key] = False

        print("\n" + "="*60)
        print("  GITHUB ENGINES DOWNLOAD & UPDATE COMPLETE")
        print("="*60 + "\n")
        return results

    def list_installed_external_engines(self) -> List[str]:
        """Lists installed external engines in the external directory."""
        if not os.path.exists(self.external_dir):
            return []
        return [d for d in os.listdir(self.external_dir) if os.path.isdir(os.path.join(self.external_dir, d))]
