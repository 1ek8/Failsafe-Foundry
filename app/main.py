import json
import sys
from app.schemas import FeatureTicket
from app.pipeline import build_report, save_report


def main():
    input_path = sys.argv[1]
    data = json.load(open(input_path, "r", encoding="utf-8"))
    ticket = FeatureTicket(**data)
    report = build_report(ticket)
    path = save_report(report)
    print(path)


if __name__ == "__main__":
    main()