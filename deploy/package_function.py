import sys
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package(project: Path, output: Path) -> None:
    config = tomllib.loads((project / "pyproject.toml").read_text())
    requirements = "\n".join(config["project"]["dependencies"]) + "\n"
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("index.py", "from cur_converter_bot.function import handler\n")
        archive.writestr("requirements.txt", requirements)
        for source in sorted((project / "src/cur_converter_bot").glob("*.py")):
            archive.write(source, f"cur_converter_bot/{source.name}")


if __name__ == "__main__":
    package(Path(__file__).resolve().parents[1], Path(sys.argv[1]))
