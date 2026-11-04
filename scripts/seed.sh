#!/usr/bin/env sh
# Development seed (inventory stock) inside the running stack.
docker compose exec -T inventory python -m seed
