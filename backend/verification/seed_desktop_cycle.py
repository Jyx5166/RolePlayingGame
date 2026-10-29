"""Create disposable Echo-only layout fixtures in an explicitly selected data directory."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
target = args.data_dir.resolve()
os.environ["AI_MURDER_MYSTERY_DATA_DIR"] = str(target)
os.environ["LLM_PROVIDER"] = "echo"
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "backend" / "app"))
from backend.verification.accounts import verification_session
from main import create_app
app = create_app()
store, catalog_service = app.state.store, app.state.game_service
from script_catalog import ScriptCatalog
catalog = ScriptCatalog(store, catalog_service)
session = verification_session(store, target, prefix="preview_cycle")
user_id = session["user"]["id"]
script = json.loads((root / "backend/resources/scripts/fog_harbor_clocktower.json").read_text(encoding="utf-8"))
existing = {item["title"] for item in catalog.list(user_id)}
for title, tags in (("恐怖夜宴（布局测试副本）", ["悬疑"]), ("雾山夜宴（标签测试副本）", ["中式恐怖"])):
    if title not in existing:
        catalog.publish(user_id, script, title, tags)
print(json.dumps({"provider": "echo", "database": str(store.database_path), "fixture_scripts": len(catalog.list(user_id)), "paid_requests": 0}, ensure_ascii=False))
