#!/usr/bin/env bash
# Start Booty (local access-code checker) and open it in the browser.
# Extra options are passed through, e.g.:  ./run_booty.sh --port 9000 --no-browser
cd "$(dirname "$0")" && exec python3 -m booty "$@"
