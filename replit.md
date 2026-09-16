# Project setup

This repository contains several independent Arduino/C++ and Python projects.

## Current Replit app

The configured Run workflow starts the PyQt5 desktop application in
`Projekte/Python/pyhart` on a private VNC display and serves a browser-based
noVNC preview on port 5000.

The HART modem currently uses `SIMULATION_MODE = True`, so the interface can be
tested without a physical serial device. Sensor records and calibration logs are
stored in a local SQLite database in the app directory.

Run the browser preview manually from the repository root with:

```sh
bash run_pyhart_web.sh
```

To use real hardware later, set `SIMULATION_MODE = False` in `hart_modem.py` and
ensure the configured serial device is available to the runtime.