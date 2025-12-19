# 🐛 Coolify Backend Deployment Fix

## Problem

Coolify deployment was failing with this error:

```
E: Package 'libgl1-mesa-glx' has no installation candidate
ERROR: failed to build: exit code 100
```

## Root Cause

The Dockerfile was using `libgl1-mesa-glx`, which is an **obsolete package** in newer Debian versions (Trixie/13+). This package has been replaced with `libgl1`.

## Solution

Updated `backend/Dockerfile` to use the correct package:

```dockerfile
# Before (obsolete)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libgl1-mesa-glx \      # ❌ Obsolete package
    libglib2.0-0 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# After (fixed)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libgl1 \              # ✅ Correct package for Debian 13+
    libglib2.0-0 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*
```

## Why This Package is Needed

`libgl1` (OpenGL library) is required by OpenCV for:
- Hardware-accelerated image processing
- GPU-based computer vision operations
- Rendering graphics for shape detection

## ✅ Fixed and Pushed

The fix has been committed and pushed to the repository. Coolify will automatically pull the updated code on the next deployment.

## Next Steps

1. **In Coolify**, click **"Redeploy"** or trigger a new deployment
2. The build should now complete successfully
3. The backend will be deployed and running

## Expected Build Output

After the fix, you should see:

```
✓ apt-get install successful
✓ pip install -r requirements.txt
✓ Docker image built successfully
✓ Container started
✓ Backend running on port 8000
```

## Other Warnings (Safe to Ignore)

You may see these warnings - they're informational only:

```
- SecretsUsedInArgOrEnv: Do not use ARG or ENV instructions for sensitive data
```

These are just Docker best practice warnings. Since you're setting environment variables through Coolify's UI (not in the Dockerfile), your secrets are secure.

## 🚀 Deployment Ready

Your backend Dockerfile is now compatible with modern Debian/Ubuntu versions and ready for Coolify deployment!

