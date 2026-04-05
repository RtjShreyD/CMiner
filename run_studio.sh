#!/usr/bin/env bash

# CMiner Web Studio Dev Launcher 🚀
# Spins up the FastAPI backend and the Vite frontend simultaneously.

echo "Starting CMiner Web Studio Components..."

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/studio-backend.log"
FRONTEND_LOG="$LOG_DIR/studio-frontend.log"

echo "Log files:"
echo "- Backend:  $BACKEND_LOG"
echo "- Frontend: $FRONTEND_LOG"

# 1. Start FastAPI Backend using conda py_lts environment
echo "Starting Backend API (Port 8000)..."
conda run --no-capture-output -n py_lts \
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload \
	> >(tee -a "$BACKEND_LOG") 2>&1 &
API_PID=$!

# 2. Wait a moment for API to bind
sleep 2

# 3. Start Vite Frontend Server
echo "Starting Vite Frontend (Port 5173)..."
cd web-studio
npm run dev > >(tee -a "../$FRONTEND_LOG") 2>&1 &
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
