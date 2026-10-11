"""Read-only source-save freeze and pinned DAT1 comparison; writes this run only."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import stat
import sys

sys.dont_write_bytecode = True
ROOT = Path(r"C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod")
RUN = Path(__file__).resolve().parent
SOURCE = Path(r"C:\Users\xinsui\Documents\Marvel's Spider-Man Remastered\76561199191371037")
SNAPSHOT = RUN / "save_snapshot"
DIAG = ROOT / "序章修复调查"
sys.path.insert(0, str(DIAG))
import diff_native_progress_153117 as parser


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def inventory(folder):
    files = {}
    dirs = []
    for path in sorted(folder.rglob("*")):
        details = path.lstat()
        assert not path.is_symlink() and not (details.st_file_attributes & 0x400), "Reparse point"
        relative = path.relative_to(folder).as_posix()
        if path.is_dir():
            dirs.append(relative)
            continue
        assert stat.S_ISREG(details.st_mode), "Non-file entry"
        raw = path.read_bytes()
        after = path.stat()
        assert (details.st_size, details.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "File changed while reading"
        assert len(raw) == details.st_size
        files[relative] = {
            "size": len(raw), "mtime_ns": details.st_mtime_ns,
            "mtime_utc": datetime.datetime.fromtimestamp(details.st_mtime, datetime.timezone.utc).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {"files": files, "directories": dirs}


def write_json(name, value):
    with (RUN / name).open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)


def copy_stable():
    began = utc()
    before = inventory(SOURCE)
    SNAPSHOT.mkdir()
    for relative in before["directories"]:
        (SNAPSHOT / relative).mkdir(parents=True, exist_ok=True)
    for relative, expected in before["files"].items():
        path = SOURCE / relative
        details = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        assert (details.st_size, details.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        assert len(raw) == expected["size"] and hashlib.sha256(raw).hexdigest() == expected["sha256"]
        assert after.st_mtime_ns == expected["mtime_ns"]
        destination = SNAPSHOT / relative
        with destination.open("xb") as output:
            output.write(raw)
        os.utime(destination, ns=(details.st_atime_ns, details.st_mtime_ns))
    source_after = inventory(SOURCE)
    copied = inventory(SNAPSHOT)
    assert before == source_after == copied, "Source changed during whole-directory freeze"
    payload = {"started_utc": began, "finished_utc": utc(), "source": str(SOURCE),
               "snapshot": str(SNAPSHOT), "source_before": before, "source_after": source_after,
               "snapshot_manifest": copied, "all_file_bytes_sizes_mtimes_equal": True,
               "file_count": len(copied["files"]), "directory_count": len(copied["directories"]),
               "game_operations": False, "save_restore_or_source_writes": False}
    write_json("manifest.json", payload)
    return payload


def selected_fields(value, prefix=""):
    selected = {}
    if isinstance(value, dict):
        for name, child in value.items():
            path = prefix + name
            if any(term in name.lower() for term in ("level", "checkpoint", "experience", "exp", "reward", "newgame", "token", "skill", "progress", "resource", "mission", "segment", "position", "perch")) and not isinstance(child, (dict, list)):
                selected[path] = child
            elif isinstance(child, (dict, list)):
                selected.update(selected_fields(child, path + "."))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            selected.update(selected_fields(child, prefix + str(index) + "."))
    return selected


def main():
    manifest = copy_stable()
    old_session = DIAG / "原版对照_账户76561199191371037" / "同档对照_20261007_110827_188252fd"
    state = json.loads((old_session / "state.json").read_text(encoding="utf-8"))
    paths = {
        "auto69": DIAG / "原版对照_账户76561199191371037" / "同档对照_20261007_100115_cb21d9cf" / "机房检查点_首次退出_20261007_102802_0fec3a97" / "slot3-s.save",
        "full201_bad": Path(state["paths"]["freeze"]) / "slot3-s.save",
        "current_native": SNAPSHOT / "slot3-s.save",
    }
    pins = {paths["auto69"]: "69d891dd71de75a97028d59de930656960f3b8268159921e7b490d8ee79b9747",
            paths["full201_bad"]: "20196723940a8d1d4e392e2acbd1ef520bdf2be8e4bd4fb69b5b6a31c7884e7a",
            paths["current_native"]: manifest["snapshot_manifest"]["files"]["slot3-s.save"]["sha256"]}
    parser.decoder.EXPECTED = pins
    labels = parser.runtime_labels()
    items = {}
    for label, path in paths.items():
        decoded, data = parser.decoder.decode(path)
        mission = parser.MSFX(decoded, data, labels)
        mission.pop("raw_hex")
        tables = [table for table in mission["objective_tables"] if table["runtime_name"] == "GP_A1_FISK"]
        fields = {}
        for tag, section in decoded["sections"].items():
            for index, obj in enumerate(section["objects"]):
                fields.update(selected_fields(obj["object"], tag + "." + str(index) + "."))
        items[label] = {"decoded": decoded, "metadata": parser.metadata(decoded), "mission": mission,
                        "reflected_scalar_fields": fields, "fisk_tables": tables,
                        "fisk_tables_consistent": len(tables) == 2 and
                        [row["words_raw"][:5] for row in tables[0]["rows"]] == [row["words_raw"][:5] for row in tables[1]["rows"]]}
    comparisons = {}
    for old in ("auto69", "full201_bad"):
        first, current = items[old], items["current_native"]
        comparisons[old] = {"metadata": parser.decoder.diff(first["metadata"], current["metadata"]),
                            "reflected_scalar_fields": parser.decoder.diff(first["reflected_scalar_fields"], current["reflected_scalar_fields"]),
                            "fisk_tables": parser.decoder.diff(first["fisk_tables"], current["fisk_tables"]),
                            "global_missions": parser.decoder.diff(first["mission"]["global_mission_states"], current["mission"]["global_mission_states"]),
                            "sections": parser.comparison(first["decoded"], current["decoded"])}
    payload = {"captured_utc": utc(), "manifest": str(RUN / "manifest.json"),
               "source_label_evidence": str(parser.RUNTIME_LOG), "items": items, "comparisons": comparisons,
               "user_report": "Native game: countdown completed, unskippable cinematic ended naturally, Battle Focus displayed, machine-room exit traversed to outside.",
               "limits": ["Reported door passage is human observation, not door/collision entity readback.",
                          "No reload of the current snapshot has been tested.",
                          "Raw mission-table and reflected checkpoint changes do not prove closed-door save repaired.",
                          "NG+ and resource values in these files do not establish ordinary level-1 new-game/co-op support.",
                          "Historical runtime objective names label raw stored tables; no field enum is inferred beyond previous observational evidence."]}
    write_json("audit.json", payload)
    print("RUN", RUN)
    print("FREEZE", manifest["file_count"], "files", manifest["directory_count"], "dirs", manifest["all_file_bytes_sizes_mtimes_equal"])
    for label, item in items.items():
        print(label, item["decoded"]["size"], item["decoded"]["sha256"], "consistent", item["fisk_tables_consistent"])
        print("METADATA", json.dumps(item["metadata"], ensure_ascii=False))
        print("SCALARS", json.dumps(item["reflected_scalar_fields"], ensure_ascii=False))
        for table in item["fisk_tables"]:
            print("FISK", table["stride"], [(row["runtime_name"], row["words_raw"][1:3]) for row in table["rows"]])
    for label, comparison in comparisons.items():
        print("DIFF", label, "METADATA", json.dumps(comparison["metadata"], ensure_ascii=False))
        print("DIFF", label, "FISK", json.dumps(comparison["fisk_tables"], ensure_ascii=False))


if __name__ == "__main__":
    main()
