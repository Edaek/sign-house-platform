# Health Checks and API Documentation

This document describes the health check endpoints and API documentation added to Sign House.

## Health Check Endpoints

### 1. `/health` - Complete Health Check
**Purpose:** Comprehensive health check including database connectivity

**Response (200 - Healthy):**
```json
{
  "status": "healthy",
  "database": "healthy"
}
```

**Response (503 - Unhealthy):**
```json
{
  "status": "unhealthy",
  "database": "unhealthy",
  "error": "Error message"
}
```

**Use Case:** Load balancers, monitoring tools (Datadog, New Relic, etc.)

### 2. `/ready` - Readiness Probe
**Purpose:** Check if the application is ready to receive traffic

**Response (200):**
```json
{
  "ready": true
}
```

**Use Case:** Kubernetes readiness probes, Coolify deployment checks

### 3. `/live` - Liveness Probe
**Purpose:** Check if the application is alive

**Response (200):**
```json
{
  "alive": true
}
```

**Use Case:** Kubernetes liveness probes, container orchestration

## API Documentation (Swagger)

### Access Swagger UI
**Local:** http://localhost:5001/api-docs/
**Production:** https://your-domain.com/api-docs/

### OpenAPI Specification
**JSON:** http://localhost:5001/apispec.json

### Features
- Interactive API documentation
- Try out endpoints directly from the browser
- JWT authentication support
- Complete request/response schemas

## Testing the Endpoints

### Health Check
```bash
# Local
curl http://localhost:5001/health

# Production
curl https://your-domain.com/health
```

### Readiness
```bash
curl http://localhost:5001/ready
```

### Liveness
```bash
curl http://localhost:5001/live
```

### API Documentation
```bash
# Visit in browser
open http://localhost:5001/api-docs/
```

## Monitoring Integration

### Coolify Health Check Configuration
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5001/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

### Kubernetes Probes
```yaml
livenessProbe:
  httpGet:
    path: /live
    port: 5001
  initialDelaySeconds: 10
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 5001
  initialDelaySeconds: 5
  periodSeconds: 5
```

### Docker Compose
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5001/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

## Adding Documentation to Your Endpoints

To document your API endpoints, add docstrings with YAML format:

```python
@your_bp.route('/your-endpoint', methods=['POST'])
def your_function():
    """
    Brief description
    ---
    tags:
      - YourCategory
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            field_name:
              type: string
              example: value
    responses:
      200:
        description: Success response
        schema:
          type: object
          properties:
            result:
              type: string
    """
    # Your code here
```

## Files Modified

1. **backend/app/api/health.py** (NEW)
   - Health check endpoints

2. **backend/app/__init__.py**
   - Added Swagger configuration
   - Registered health blueprint

3. **backend/app/api/auth.py**
   - Added example Swagger documentation to login endpoint

4. **backend/requirements.txt**
   - Added flasgger==0.9.7.1

## Production Considerations

1. **Security:** The Swagger UI is accessible to anyone. Consider adding authentication in production.
2. **Rate Limiting:** Add rate limiting to health check endpoints to prevent abuse.
3. **Caching:** Consider caching health check responses for high-traffic scenarios.
4. **Metrics:** Integrate with monitoring tools to track health check failures.

## Next Steps

- Document all remaining API endpoints with Swagger
- Add authentication to `/api-docs/` in production
- Set up monitoring alerts based on health check failures
- Configure your deployment platform to use these endpoints

