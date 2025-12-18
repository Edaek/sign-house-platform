# Environment Variable Templates

Since `.env` files are gitignored, use these templates to create your environment files.

## Backend Environment Variables

Create `backend/.env.example`:

```bash
# Flask Configuration
FLASK_CONFIG=production

# Security Keys (CHANGE THESE IN PRODUCTION!)
SECRET_KEY=your-secret-key-here-change-in-production
JWT_SECRET_KEY=your-jwt-secret-key-here-change-in-production

# MongoDB Configuration
# For Coolify: Use the MongoDB connection string provided by Coolify
# Format: mongodb://username:password@host:port/database
MONGO_URI=mongodb://localhost:27017/signhouse_prod

# Server Configuration
HOST=0.0.0.0
PORT=8000

# CORS Configuration
# For GitHub Pages: https://YOUR-USERNAME.github.io
# For custom domain: https://yourdomain.com
# Multiple origins separated by comma: https://domain1.com,https://domain2.com
ALLOWED_ORIGINS=https://YOUR-USERNAME.github.io

# Tesseract Configuration
# Default path for Docker/Linux: /usr/bin/tesseract
# macOS: /usr/local/bin/tesseract
TESSERACT_CMD=/usr/bin/tesseract
```

## Frontend Environment Variables

Create `frontend/.env.production`:

```bash
# Backend API URL for production (Coolify)
# Replace with your actual Coolify backend URL
VITE_API_URL=https://your-backend.coolify.domain
```

Create `frontend/.env.example`:

```bash
# Backend API URL
# For production (GitHub Pages): Set this to your Coolify backend URL
# For development: Leave empty to use proxy
VITE_API_URL=
```

## Quick Commands

### Generate Secure Keys

**Using OpenSSL:**
```bash
openssl rand -hex 32
```

**Using Python:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Create Frontend .env.production File

```bash
cd frontend
cat > .env.production << 'EOF'
VITE_API_URL=https://your-backend.coolify.domain
EOF
```

Replace `https://your-backend.coolify.domain` with your actual backend URL.

## For Local Development

Create `backend/.env` for local development:

```bash
FLASK_CONFIG=development
SECRET_KEY=dev-secret-key
JWT_SECRET_KEY=dev-jwt-secret-key
MONGO_URI=mongodb://localhost:27017/signhouse_dev
HOST=0.0.0.0
PORT=5001
ALLOWED_ORIGINS=http://localhost:3000
TESSERACT_CMD=/usr/local/bin/tesseract
```

Create `frontend/.env` for local development:

```bash
# Leave empty to use Vite proxy
VITE_API_URL=
```

