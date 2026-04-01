#!/usr/bin/env bash

# CMiner Web Studio Dev Launcher 🚀
# Spins up the FastAPI backend and the Vite frontend simultaneously.

echo "Starting CMiner Web Studio Components..."

# 1. Activate Virtual Environment and Start FastAPI Backend
echo "Starting Backend API (Port 8000)..."
source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

# 2. Wait a moment for API to bind
sleep 2

# 3. Start Vite Frontend Server
echo "Starting Vite Frontend (Port 5173)..."
cd web-studio
npm run dev &
FRONTEND_PID=$!

echo "=================================="
echo "✨ Web Studio is LIVE!"
echo "📡 API: http://localhost:8000"
echo "🖥️  UI:  http://localhost:5173"
echo "Press [CTRL+C] to gracefully stop both servers."
echo "=================================="

# Wait for interrupts
trap "echo 'Shutting down services...'; kill $API_PID $FRONTEND_PID; exit" SIGINT SIGTERM
wait
