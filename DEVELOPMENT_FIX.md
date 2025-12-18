# Development Environment Fix

## Problem: Double API Path (api/api/auth/login)

You're seeing `api/api/auth/login` instead of `/api/auth/login` in development.

## Solution

### Step 1: Check Your Frontend .env File

```bash
cd frontend
cat .env
```

### Step 2: Fix or Remove VITE_API_URL

**Option A: Remove the line** (Recommended for development)
```bash
cd frontend
# Edit .env and remove VITE_API_URL line, or set it to empty:
echo "# Leave empty for development - uses Vite proxy" > .env
echo "VITE_API_URL=" >> .env
```

**Option B: Ensure it's empty**
Your `frontend/.env` should look like this for development:
```bash
# Backend API URL - Leave EMPTY for local development
VITE_API_URL=
```

### Step 3: Restart Vite Dev Server

```bash
# Stop the current dev server (Ctrl+C)
# Then restart:
cd frontend
npm run dev
```

## Understanding the Configuration

### Development (Local)
- `VITE_API_URL` should be **empty** or **not set**
- Vite proxy handles API requests: `/api` → `http://localhost:5001/api`
- Frontend runs on: `http://localhost:3000`
- Backend runs on: `http://localhost:5001`

### Production (GitHub Pages + Coolify)
- `VITE_API_URL=https://your-backend.coolify.domain`
- Direct connection to Coolify backend
- Frontend on: `https://username.github.io/sign-house-v3/`
- Backend on: `https://your-backend.coolify.domain`

## Environment Files Overview

```
frontend/
├── .env                    # For development (VITE_API_URL should be empty)
├── .env.production         # For production build (set to Coolify URL)
└── .env.example           # Template/documentation
```

## Quick Commands

### Check current environment variables (during dev server run):
Open browser console and run:
```javascript
console.log('API URL:', import.meta.env.VITE_API_URL)
console.log('Mode:', import.meta.env.MODE)
```

### Reset to clean development state:
```bash
cd frontend
echo "VITE_API_URL=" > .env
npm run dev
```

## Expected API Calls

### ✅ Correct (Development):
```
GET http://localhost:3000/api/auth/me
→ Proxied to: http://localhost:5001/api/auth/me
```

### ❌ Incorrect (What you're seeing):
```
GET http://localhost:3000/api/api/auth/login
→ Double "api" path
```

## Backend Should Be Running On Port 5001

Make sure your backend is running:
```bash
cd backend
source venv/bin/activate  # or: venv\Scripts\activate on Windows
python run.py
```

Should show:
```
Starting server on http://0.0.0.0:5001
```

## Still Having Issues?

1. **Clear browser cache** - Hard refresh (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows)
2. **Check browser console** for the actual API URL being called
3. **Check Network tab** to see the full request URL
4. **Restart both servers** (backend and frontend)

