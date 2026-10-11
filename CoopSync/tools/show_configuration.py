"""Show file-only local discovery. Does not launch or attach to the game."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from runtime_config import game_executable, objdump_executable


def main():
    try:
        game, objdump = game_executable(), objdump_executable()
        print(json.dumps({"game_executable": str(game), "game_file_exists": game.is_file(),
            "objdump": str(objdump), "objdump_exists": objdump.is_file(),
            "game_operations": False, "hint": "Set COOPSYNC_GAME_EXE/COOPSYNC_OBJDUMP when discovery is unavailable."},
            ensure_ascii=False))
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
