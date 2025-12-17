# Sign House - Floor Plan Analysis Application

A web application for extracting text data from floor plans using computer vision and OCR. Upload PDF floor plans, automatically detect shapes (circles/rectangles), extract text using OCR, and export the data to Excel or CSV.

## Features

- **User Authentication**: Secure login and registration system
- **Project Management**: Organize floor plans into projects
- **PDF Processing**: Upload multi-page PDF floor plans
- **Shape Detection**: Automatic detection of circles and rectangles using OpenCV
- **OCR Text Extraction**: Extract text from detected shapes using Tesseract
- **Manual Selection**: Draw custom regions to extract specific text
- **Interactive Canvas**: Pan, zoom, and select shapes on floor plans
- **Excel Templates**: Import custom Excel templates for export formatting
- **Multiple Export Formats**: Export to Excel (.xlsx) or CSV

## Tech Stack

### Backend

- **Flask** - Python web framework
- **Flask-PyMongo** - MongoDB integration
- **MongoDB** - NoSQL Database
- **OpenCV** - Computer vision for shape detection
- **Tesseract/pytesseract** - OCR engine
- **PyMuPDF** - PDF processing
- **openpyxl** - Excel file handling
- **JWT** - Authentication

### Frontend

- **React 18** - UI library
- **TypeScript** - Type safety
- **Vite** - Build tool
- **Tailwind CSS** - Styling
- **Zustand** - State management
- **Framer Motion** - Animations
- **Lucide React** - Icons

## Prerequisites

- Python 3.10+
- Node.js 18+
- MongoDB 6.0+
- Tesseract OCR

### Installing Tesseract

**macOS:**

```bash
brew install tesseract
```

**Ubuntu/Debian:**

```bash
sudo apt-get install tesseract-ocr
```

**Windows:**
Download from: https://github.com/UB-Mannheim/tesseract/wiki

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd sign-house-v3
```

### 2. Set up the backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your MongoDB connection string
```

### 3. Set up the frontend

```bash
cd frontend

# Install dependencies
npm install
```

### 4. Set up MongoDB

```bash
# Start MongoDB (if not running as a service)
mongod --dbpath /path/to/data/db

# Or using Docker
docker run -d -p 27017:27017 --name mongodb mongo:7.0
```

## Running the Application

### Development Mode

**Terminal 1 - Backend:**

```bash
cd backend
source venv/bin/activate
python run.py
```

Backend runs on: http://localhost:5000

**Terminal 2 - Frontend:**

```bash
cd frontend
npm run dev
```

Frontend runs on: http://localhost:3000

### Production Build

**Backend:**

```bash
cd backend
gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app('production')"
```

**Frontend:**

```bash
cd frontend
npm run build
# Serve the dist folder with your preferred static server
```

## Usage Guide

### 1. Create Account / Login

Register a new account or login with existing credentials.

### 2. Create a Project

Click "New Project" and give it a name and optional description.

### 3. Upload Files

- **Excel Template** (optional): Upload an Excel file with your desired column headers
- **Floor Plan PDF**: Upload your floor plan PDF (can have multiple pages)

### 4. Process Floor Plans

For each floor:

1. Click "Process" to open the editor
2. Click "Detect Shapes" to automatically find circles or rectangles
3. Click "Run OCR" to extract text from all detected shapes
4. Optionally draw manual regions to extract specific text
5. Edit extracted text if needed
6. Click "Mark Complete" to proceed to the next floor

### 5. Export Data

Once all floors are processed:

1. Go to the Export page
2. Choose Excel or CSV format
3. Download your data

## Project Structure

```
sign-house-v3/
├── backend/
│   ├── app/
│   │   ├── api/           # API endpoints
│   │   ├── models/        # Database models
│   │   └── services/      # Business logic
│   ├── uploads/           # Uploaded files
│   ├── config.py          # Configuration
│   ├── requirements.txt   # Python dependencies
│   └── run.py             # Entry point
│
├── frontend/
│   ├── public/            # Static assets
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── pages/         # Page components
│   │   ├── store/         # Zustand stores
│   │   └── lib/           # Utilities
│   ├── package.json       # Node dependencies
│   └── vite.config.ts     # Vite configuration
│
└── README.md
```

## API Endpoints

### Authentication

- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login
- `GET /api/auth/me` - Get current user

### Projects

- `GET /api/projects` - List projects
- `POST /api/projects` - Create project
- `GET /api/projects/:id` - Get project details
- `PUT /api/projects/:id` - Update project
- `DELETE /api/projects/:id` - Delete project
- `POST /api/projects/:id/template` - Upload template
- `POST /api/projects/:id/floorplan` - Upload floor plan

### Processing

- `POST /api/processing/detect/:floorplan_id` - Detect shapes
- `POST /api/processing/ocr/:floorplan_id` - Run OCR
- `POST /api/processing/ocr-region/:floorplan_id` - OCR manual region
- `GET /api/processing/image/:floorplan_id` - Get floor plan image

### Export

- `GET /api/export/preview/:project_id` - Preview export data
- `POST /api/export/excel/:project_id` - Export to Excel
- `POST /api/export/csv/:project_id` - Export to CSV

## Configuration

### Environment Variables

| Variable         | Description            | Default                                   |
| ---------------- | ---------------------- | ----------------------------------------- |
| `FLASK_CONFIG`   | Config environment     | `development`                             |
| `SECRET_KEY`     | Flask secret key       | -                                         |
| `JWT_SECRET_KEY` | JWT signing key        | -                                         |
| `MONGO_URI`      | MongoDB connection URI | `mongodb://localhost:27017/signhouse_dev` |
| `TESSERACT_CMD`  | Tesseract path         | `/usr/local/bin/tesseract`                |

## Shape Detection Tips

- **Clean CAD exports** work best for shape detection
- Use "Auto" detection to let the system choose between circles and rectangles
- Adjust detection if needed by selecting specific shape type
- Manual drawing is available for difficult areas

## Troubleshooting

### Tesseract not found

Ensure Tesseract is installed and in your PATH, or set the `TESSERACT_CMD` environment variable.

### Database connection error

Verify MongoDB is running and the `MONGO_URI` is correct.

### PDF processing fails

Install poppler for pdf2image:

- macOS: `brew install poppler`
- Ubuntu: `apt-get install poppler-utils`

## License

MIT License
