## wf-logger

Read NMEA 0183 data from a socket, then store selected data to a SQLite file.

### Installation

1. Clone the repository to a convenient place

2. Copy the file `config_sample.py` to `config.py`. Edit the latter. In
   particular, set `NMEA_HOST` and `NMEA_PORT` to the source of socket data. Set
   `SQLITE_FILE` to a location where the process will have write permissions.

3. Copy the file `systemd/wf-logger.service` to `/etc/systemd/system`. Edit as
   necessary.

4. Start and enable the daemon:
    ```
   sudo systemctl daemon-reload
   sudo systemctl start wf-logger
   sudo systemctl enable wf-logger
   ```
