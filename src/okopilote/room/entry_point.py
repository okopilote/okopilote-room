#!/usr/bin/env python3
import argparse
import logging

from .__about__ import __version__
from .app import App

default_cf_file = "/etc/okopilote/room.conf"


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-v", "--verbose", help="increase verbosity", action="store_true"
    )
    parser.add_argument(
        "-c",
        "--conf",
        default=default_cf_file,
        help=f"Configuration file. Default: {default_cf_file}",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="[%(levelname)s] %(message)s")

    try:
        App.start(config_file=args.conf)
    except FileNotFoundError as e:
        logging.error(e)
        exit(1)
