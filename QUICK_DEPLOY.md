# Quick Deploy Checklist

Use this as a quick reference during deployment.

## 🔴 Coolify Backend Setup

### 1. MongoDB Database
```
Resource Type: Database → MongoDB
Name: signhouse-mongodb
Database: signhouse_prod
→ Copy connection string
```

### 2. Backend Application
```
Resource Type: Application → GitHub
Repository: sign-house-v3
Branch: main
Base Directory: /backend
Port: 8000
```

### 3. Environment Variables
```bash
FLASK_CONFIG=production
SECRET_KEY=<generate-random-32-chars>
JWT_SECRET_KEY=<generate-random-32-chars>
MONGO_URI=<mongodb-connection-string>
ALLOWED_ORIGINS=https://YOUR-USERNAME.github.io
PORT=8000
TESSERACT_CMD=/usr/bin/tesseract
```

### 4. Persistent Volume
```
Source: signhouse-uploads (new volume)
Destination: /app/uploads
```

### 5. Domain
```
- Add domain or use Coolify domain
- Enable Force HTTPS
→ Copy backend URL
```

---

## 🔵 GitHub Pages Frontend Setup

### 1. Create .env.production
```bash
cd frontend
echo "VITE_API_URL=https://your-backend-url" > .env.production
```

### 2. GitHub Repository Settings
```
Settings → Pages
Source: GitHub Actions
```

### 3. GitHub Secret
```
Settings → Secrets → Actions → New secret
Name: VITE_API_URL
Value: https://your-backend-url
```

### 4. Deploy
```bash
git add .
git commit -m "Configure deployment"
git push origin main
```

---

## ✅ Verification

- [ ] Backend URL works: `https://your-backend-url/api/auth/me`
- [ ] Frontend loads: `https://YOUR-USERNAME.github.io/sign-house-v3/`
- [ ] Can register/login
- [ ] No CORS errors in console
- [ ] Files can be uploaded

---

## 🚨 Common Issues

**CORS Error?**
→ Check ALLOWED_ORIGINS matches GitHub Pages URL exactly

**Assets 404?**
→ Verify `base: '/sign-house-v3/'` in vite.config.ts

**Backend won't start?**
→ Check Coolify logs & verify MONGO_URI

**Uploads disappear?**
→ Add persistent volume for /app/uploads

