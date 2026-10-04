import json
import sys
from urllib.parse import parse_qs, urlsplit


def connection(data: dict) -> tuple[str, str]:
    parsed = urlsplit(data.get("endpoint", ""))
    database = parse_qs(parsed.query).get("database", [data.get("database_path", "")])[0]
    if parsed.scheme != "grpcs" or not parsed.netloc or not database.startswith("/"):
        raise ValueError("YDB не вернула корректный endpoint с путём database")
    return f"{parsed.scheme}://{parsed.netloc}", database


if __name__ == "__main__":
    try:
        endpoint, database = connection(json.load(sys.stdin))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SystemExit(str(exc))
    print(endpoint)
    print(database)
