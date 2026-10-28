# Open Access Academic Resource Repository

## Project

This project aims to make academic resources easier to discover. It provides a platform to organize and explore databases, journals, and other research sources, with intelligent guidance to help researchers find resources relevant to their needs.

## Architecture

### Frontend

A Next.js application that provides the user interface and connects researchers with the catalog and its discovery features.

### Backend

A Django REST API that manages the catalog, research resources, and harvesting operations.

### Worker

A Celery worker that processes resource harvesting tasks outside the API request cycle.

### Message broker

RabbitMQ delivers tasks from the API to the worker. Its data is kept in a persistent Docker volume.

### Scheduler

A dedicated cron service periodically calls the backend to start harvesting tasks that are due.

## Design decisions

The frontend and backend run as separate services so each can evolve and scale independently. Harvesting runs asynchronously through Celery and RabbitMQ to keep long running work from delaying user requests. The scheduler calls the backend API instead of duplicating its business logic. The database is configured through environment variables and can run outside the Docker Compose stack, allowing the application and database to be managed independently.
