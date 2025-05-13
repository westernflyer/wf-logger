#
# Copyright (c) 2025-present Tom Keffer <tkeffer@gmail.com>
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
#
"""Log key NMEA 0183 data to a sqlite file."""
from __future__ import annotations

import errno
import logging
import socket
import sqlite3
import sys
import time
from logging.handlers import SysLogHandler

import parse_nmea
from config import *

# Set up logging using the system logger
if sys.platform == "darwin":
    address = '/var/run/syslog'
else:
    address = '/dev/log'
log = logging.getLogger("wf-logger")
log.setLevel(logging.DEBUG if DEBUG else logging.INFO)
handler = SysLogHandler(address=address)
formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)


def main():
    log.info("Starting up wf-logger.  ")
    log.info("Debug level: %s", DEBUG)

    while True:
        try:
            db_loop()
        except KeyboardInterrupt:
            sys.exit("Keyboard interrupt. Exiting.")
        except ConnectionResetError as e:
            warn_print_sleep(f"Connection reset: {e}")
        except ConnectionRefusedError as e:
            warn_print_sleep(f"Connection refused: {e}")
        except TimeoutError as e:
            warn_print_sleep(f"Socket timeout: {e}")
        except socket.gaierror as e:
            warn_print_sleep(f"GAI error: {e}")
        except OSError as e:
            # Retry if it's a network unreachable error. Otherwise, reraise the exception.
            if e.errno == errno.ENETUNREACH or e.errno == errno.EHOSTUNREACH:
                warn_print_sleep(f"Network unreachable: {e}")
            else:
                raise


def db_loop():
    with sqlite3.connect(SQLITE_FILE) as conn:
        # Try to initialize the table. Be prepared to catch an exception if it has already been initialized
        try:
            conn.execute(SQLITE_SCHEMA)
        except sqlite3.OperationalError:
            pass
        nmea_loop(conn)


def nmea_loop(connection: sqlite3.Connection):
    """Read sentences from a socket, parse, write to the database

    This is the heart of the program.
    """
    # Timestamp of the last database write
    last_write = 0
    # Last value for the cumulative log
    last_distance = None
    # Last value for the depth
    last_depth = None
    # Last value for wind
    last_wind = None

    # Open the socket connection and start reading lines
    for line in gen_nmea(NMEA_HOST, NMEA_PORT):
        try:
            # Parse the line. Be prepared to catch any exceptions.
            parsed_nmea = parse_nmea.parse(line)
        except parse_nmea.UnknownNMEASentence as e:
            # We need GLL. Fail hard if we don't know how to parse it. Otherwise, press on...
            if e.sentence_type == 'GLL':
                raise
            else:
                continue
        except (parse_nmea.NMEAParsingError, parse_nmea.NMEAStatusError) as e:
            log.warning("NMEA error: %s", e)
            print(f"NMEA error: {e}", file=sys.stderr)
            continue
        else:
            # Parsing went ok.
            # Convert time to seconds (instead of milliseconds):
            parsed_nmea["timestamp"] /= 1000.0
            sentence_type = parsed_nmea["sentence_type"]
            if sentence_type == "DPT":
                # Save the depth
                last_depth = parsed_nmea
            elif sentence_type == "VLW":
                # Save the distance
                last_distance = parsed_nmea
            elif sentence_type == "MDA":
                last_wind = parsed_nmea
            elif sentence_type == 'GLL':
                # GLL sentences trigger a write. Make sure enough time has elapsed since the last write.
                delta = parsed_nmea["timestamp"] - last_write
                if delta >= WRITE_INTERVAL:
                    # It's been long enough. Do a write.
                    # Check for stale values and substitute None for them
                    depth = check_stale(last_depth, "water_depth_meters")
                    distance = check_stale(last_distance, "water_total_nm")
                    wind_speed = check_stale(last_wind, "tws_knots")
                    wind_direction = check_stale(last_wind, "twd_true")
                    write_record(connection,
                                 parsed_nmea["timestamp"],
                                 parsed_nmea["latitude"],
                                 parsed_nmea["longitude"],
                                 depth,
                                 distance,
                                 wind_speed,
                                 wind_direction)
                    last_write = parsed_nmea["timestamp"]


def gen_nmea(host: str, port: int):
    """Listen for NMEA data on a TCP socket."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(NMEA_TIMEOUT)
        s.connect((host, port))
        log.info(f"Connected to NMEA socket at {host}:{port}; timeout: {NMEA_TIMEOUT} seconds.")
        with s.makefile('r') as nmea_stream:
            for line in nmea_stream:
                yield line.strip()


def check_stale(parsed_nmea, name):
    if parsed_nmea and time.time() - parsed_nmea["timestamp"] <= STALE:
        return parsed_nmea.get(name)
    else:
        return None


def write_record(connection: sqlite3.Connection,
                 timestamp: int,
                 latitude: str, longitude: str,
                 depth: str | None,
                 distance: str | None,
                 wind_speed: str | None,
                 wind_direction: str | None) -> None:
    """Write an entry in the database."""
    # Round timestamp to the nearest integer
    t = int(timestamp + 0.5)
    with connection:
        connection.execute("INSERT INTO archive VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (t, latitude, longitude, depth, distance, wind_speed, wind_direction))


def warn_print_sleep(msg: str):
    """Print and log a warning message, then sleep for NMEA_RETRY_WAIT seconds."""
    print(msg, file=sys.stderr)
    print(f"*** Waiting {NMEA_RETRY_WAIT} seconds before retrying.", file=sys.stderr)
    log.warning(msg)
    log.warning(f"*** Waiting {NMEA_RETRY_WAIT} seconds before retrying.")
    time.sleep(NMEA_RETRY_WAIT)
    print("*** Retrying...", file=sys.stderr)
    log.warning("*** Retrying...")


if __name__ == "__main__":
    main()
