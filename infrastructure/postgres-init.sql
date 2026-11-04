-- One database per service (service-owned data). Runs once on first container start.
CREATE DATABASE orchestrator;
CREATE DATABASE inventory;
CREATE DATABASE payment;
CREATE DATABASE shipping;
