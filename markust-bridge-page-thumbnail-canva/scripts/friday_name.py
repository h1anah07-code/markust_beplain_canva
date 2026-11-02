#!/usr/bin/env python3
"""Derive a Canva title from an explicit local request date, never host today."""

import argparse
from datetime import date, timedelta
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def naming_context(request_date: str, timezone: str) -> dict:
    """Return the Friday in the request date's Monday–Sunday week."""
    local_date = date.fromisoformat(request_date)
    if local_date.isoformat() != request_date:
        raise ValueError('request date must use YYYY-MM-DD')
    ZoneInfo(timezone)
    monday = local_date - timedelta(days=local_date.weekday())
    friday = monday + timedelta(days=4)
    return {
        'requestDate': local_date.isoformat(),
        'timezone': timezone,
        'weekStartDate': monday.isoformat(),
        'fridayDate': friday.isoformat(),
        'canvaTitle': friday.strftime('%m.%d'),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-date', required=True, help='Local user request date, YYYY-MM-DD')
    parser.add_argument('--timezone', required=True, help='User/client IANA timezone, e.g. Asia/Hong_Kong')
    args = parser.parse_args()
    try:
        result = naming_context(args.request_date, args.timezone)
    except (ValueError, ZoneInfoNotFoundError, OverflowError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
