#!/usr/bin/env sh
# Usage: scripts/run_tests.sh [unit|db|messaging|e2e|api|all]
set -e
cd "$(dirname "$0")/../backend"
case "${1:-all}" in
  unit) python -m unittest tests.test_unit -v ;;
  db) python -m unittest tests.test_db_integration -v ;;
  messaging) python -m unittest tests.test_messaging -v ;;
  e2e) python -m unittest tests.test_e2e -v ;;
  api) python -m unittest tests.test_api -v ;;
  all) python -m unittest discover -s tests -t . ;;
esac
