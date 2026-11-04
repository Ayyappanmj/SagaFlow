# SagaFlow quick start for Windows PowerShell (Docker Desktop must be running).
Copy-Item -Path .env.example -Destination .env -ErrorAction SilentlyContinue
docker compose up --build -d
Write-Host "Waiting for services to become healthy..."
Start-Sleep -Seconds 30
docker compose ps
docker compose exec -T inventory python -m seed
Write-Host "Dashboard: http://localhost:3000  API docs: http://localhost:8000/docs  RabbitMQ: http://localhost:15672  Grafana: http://localhost:3001"
