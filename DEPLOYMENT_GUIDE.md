# Deployment Guide: Coolify + GitHub Pages

This guide will help you deploy the Sign House application with the backend on Coolify and frontend on GitHub Pages.

## 📋 Prerequisites

- GitHub account with this repository
- Coolify instance running and accessible
- GitHub repository pushed to GitHub

## 🔧 Part 1: Backend Deployment to Coolify

### Step 1: Create MongoDB Database in Coolify

1. Log into your Coolify dashboard
2. Click **"+ New Resource"** → **"Database"** → **"MongoDB"**
3. Configure:
   - Name: `signhouse-mongodb`
   - Database Name: `signhouse_prod`
   - Version: Latest stable (7.0+)
4. Click **"Create"**
5. **Important**: Copy the MongoDB connection string - you'll need it for the backend
   - Format: `mongodb://username:password@host:port/signhouse_prod`

### Step 2: Deploy Backend Application

1. In Coolify, click **"+ New Resource"** → **"Application"**
2. Select **"GitHub App"** and connect your repository
3. Configure the application:
   - **Repository**: Select `sign-house-v3`
   - **Branch**: `main` (or your default branch)
   - **Build Pack**: Dockerfile
   - **Dockerfile Location**: Leave as `Dockerfile`
   - **Base Directory**: Set to `/backend` ⚠️ Important!
   - **Port**: `8000`

4. **Configure Environment Variables** (click on "Environment Variables"):
   ```bash
   FLASK_CONFIG=production
   SECRET_KEY=<generate-a-long-random-string>
   JWT_SECRET_KEY=<generate-a-different-long-random-string>
   MONGO_URI=<paste-your-mongodb-connection-string>
   ALLOWED_ORIGINS=https://YOUR-GITHUB-USERNAME.github.io
   PORT=8000
   TESSERACT_CMD=/usr/bin/tesseract
   ```

   **Generate secure keys** using:
   ```bash
   # On Linux/Mac:
   openssl rand -hex 32
   
   # Or use Python:
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

5. **Configure Persistent Storage**:
   - Click on **"Storage"** or **"Volumes"**
   - Add a new volume:
     - **Source**: Create new volume (e.g., `signhouse-uploads`)
     - **Destination**: `/app/uploads`
   - This ensures uploaded files persist across deployments

6. **Configure Domain**:
   - Click on **"Domains"**
   - Add your domain or use the Coolify-provided domain
   - Enable **"Force HTTPS"**

7. Click **"Deploy"** and wait for the build to complete

8. **Important**: After deployment, copy your backend URL (e.g., `https://backend.yourdomain.com`)

### Step 3: Update ALLOWED_ORIGINS

Once you know your GitHub Pages URL:
1. Go back to your backend app in Coolify
2. Update the `ALLOWED_ORIGINS` environment variable:
   ```
   ALLOWED_ORIGINS=https://YOUR-GITHUB-USERNAME.github.io
   ```
3. Redeploy the backend

## 🌐 Part 2: Frontend Deployment to GitHub Pages

### Step 1: Create Environment File

You need to create a `.env.production` file in the `frontend/` directory:

```bash
cd frontend
cat > .env.production << EOF
VITE_API_URL=https://your-backend.coolify.domain
EOF
```

**Replace** `https://your-backend.coolify.domain` with your actual Coolify backend URL.

### Step 2: Configure GitHub Repository Settings

1. Go to your GitHub repository
2. Navigate to **Settings** → **Pages**
3. Under "Build and deployment":
   - **Source**: Select "GitHub Actions"

### Step 3: Add GitHub Secret

1. In your GitHub repository, go to **Settings** → **Secrets and variables** → **Actions**
2. Click **"New repository secret"**
3. Add:
   - **Name**: `VITE_API_URL`
   - **Value**: Your Coolify backend URL (e.g., `https://backend.yourdomain.com`)

### Step 4: Commit and Push

Commit all the deployment configuration files:

```bash
git add .
git commit -m "Configure deployment for Coolify and GitHub Pages"
git push origin main
```

### Step 5: Monitor Deployment

1. Go to the **"Actions"** tab in your GitHub repository
2. Watch the "Deploy Frontend to GitHub Pages" workflow
3. Once complete, your site will be available at:
   - `https://YOUR-GITHUB-USERNAME.github.io/sign-house-v3/`

## ✅ Verification Checklist

After deployment, verify:

### Backend (Coolify)
- [ ] Backend is running and accessible at your Coolify URL
- [ ] MongoDB is connected (check backend logs in Coolify)
- [ ] Health check endpoint works: `https://your-backend-url/api/auth/me` (should return 401)
- [ ] Uploads directory is persistent (check volume is mounted)

### Frontend (GitHub Pages)
- [ ] Site loads at `https://YOUR-USERNAME.github.io/sign-house-v3/`
- [ ] Assets load correctly (no 404s in browser console)
- [ ] Can access login page

### Integration
- [ ] Open browser DevTools → Network tab
- [ ] Try to register/login
- [ ] Check CORS headers in network requests
- [ ] Verify API calls go to your Coolify backend
- [ ] No CORS errors in console

## 🔍 Troubleshooting

### CORS Errors

**Problem**: Browser shows CORS policy errors

**Solution**:
1. Check `ALLOWED_ORIGINS` in Coolify backend environment variables
2. Make sure it matches your GitHub Pages URL exactly
3. Include the protocol (`https://`)
4. Redeploy backend after changing

### 404 on Frontend Routes

**Problem**: Refreshing the page shows 404

**Solution**: GitHub Pages doesn't support client-side routing out of the box.
- Use hash routing in React Router, or
- Add a custom 404.html that redirects to index.html

### Assets Not Loading

**Problem**: CSS/JS files return 404

**Solution**:
1. Verify the `base: '/sign-house-v3/'` in `vite.config.ts`
2. Make sure the repository name matches the base path
3. Rebuild and redeploy frontend

### Backend Container Won't Start

**Problem**: Backend container exits immediately

**Solutions**:
1. Check logs in Coolify
2. Verify all environment variables are set
3. Test MongoDB connection string
4. Ensure base directory is set to `/backend`

### File Uploads Disappearing

**Problem**: Uploaded files vanish after redeployment

**Solution**:
1. Verify persistent volume is configured in Coolify
2. Check volume is mounted to `/app/uploads`
3. Ensure uploads directory permissions are correct

## 🔄 Redeployment

### Backend (Automatic via Coolify)
Coolify watches your GitHub repository:
1. Make changes to backend code
2. Commit and push to your branch
3. Coolify automatically rebuilds and redeploys

### Frontend (Automatic via GitHub Actions)
The workflow triggers automatically:
1. Make changes to frontend code
2. Commit and push to main branch
3. GitHub Actions builds and deploys automatically
4. Changes live in ~2-3 minutes

## 📝 Important Notes

1. **Database Backups**: Set up regular backups for your MongoDB in Coolify
2. **Secrets Management**: Never commit `.env` files to Git
3. **HTTPS Only**: Both backend and frontend should use HTTPS in production
4. **File Size Limits**: The backend is configured for 50MB max file uploads
5. **Monitoring**: Check Coolify logs regularly for any issues

## 🆘 Getting Help

If you encounter issues:

1. Check Coolify backend logs
2. Check GitHub Actions logs
3. Check browser console for frontend errors
4. Verify all environment variables are set correctly
5. Test API endpoints directly with curl/Postman

## 🎉 Success!

Once everything is working:
- Backend API: `https://your-backend.coolify.domain/api`
- Frontend: `https://YOUR-USERNAME.github.io/sign-house-v3/`

Your Sign House application is now live! 🚀

