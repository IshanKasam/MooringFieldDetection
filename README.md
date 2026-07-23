# ⚓ Mooring Field Detection & Coastal Prospecting

> **Automated end-to-end detection, spatial clustering, dock/marina rejection, and contact enrichment for coastal mooring fields from high-resolution satellite imagery.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61dafb.svg)](https://react.dev/)

---

## 🌊 Overview

**Mooring Field Detection** is a production-grade spatial intelligence engine designed to discover, catalog, and analyze mooring fields along marine coastlines. 

It combines **YOLO-OBB (Oriented Bounding Box)** computer vision, **DBSCAN spatial clustering**, **OpenStreetMap Overpass spatial filtering**, and **Google Places / Gemini LLM research grounding** to transform raw satellite imagery into actionable mooring location data.

![Architecture Diagram](https://raw.githubusercontent.com/IshanKasam/MooringFieldDetection/main/docs/architecture.png)

### Key Features
- 🛰️ **Satellite Imagery Pipeline**: Fetches grid tiles automatically via Google Static Maps API for NOAA navigation anchorages and OpenStreetMap coastal regions.
- 🎯 **YOLO-OBB Boat Detection**: Detects oriented boat bounding boxes to handle tight vessel spacing and arbitrary alignments.
- 📍 **DBSCAN Field Clustering**: Spatial clustering of vessel centroids to identify cohesive mooring field boundaries.
- 🛑 **OSM Dock & Marina Filter**: Rejects false-positive piers, floating quays, and marinas using multi-stage spatial heuristics (aspect ratio, nearest-neighbor spacing regularities, convex hull density, pier alignment).
- 🔍 **Harbor Contact Enrichment**: Automated lookup of harbor management contacts, harbormaster details, and operator information via Google Places API and Google Gemini Grounded Search.
- 🗺️ **Interactive Web Dashboard**: Built with React, Vite, and MapLibre GL for real-time map exploration, state coastline scanning, table filtering, and Excel export.

---

## ⚡ Quick Start

### 1. Local Setup

```bash
# Clone the repository
git clone https://github.com/IshanKasam/MooringFieldDetection.git
cd MooringFieldDetection

# Create a virtual environment & install dependencies
python -m venv .venv
.venv\Scripts\activate  # On Linux/macOS: source .venv/bin/activate
pip install -e ".[web,dev]"
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

```ini
GOOGLE_MAPS_API_KEY=your_google_maps_key
GEMINI_API_KEY=your_gemini_key
```

### 3. Launch Web Application

Run the FastAPI backend server (which serves the compiled React Web UI):

```bash
mooring-web
```
Open **`http://localhost:8000`** in your browser!

---

## 🐳 Docker Deployment

The application is fully containerized with a multi-stage Docker build combining the React static frontend and FastAPI backend:

```bash
# Build Docker image
docker build -t mooring-fields:latest .

# Run Docker container with persistent data volume
docker run -d -p 8000:8000 \
  -e GOOGLE_MAPS_API_KEY="your_api_key" \
  -v mooring_data:/data \
  --name mooring-app mooring-fields:latest
```

Open **`http://localhost:8000`**!

---

## 💻 CLI Commands

The package exposes powerful CLI utilities for pipeline execution, data parsing, and model training:

| Command | Description |
|---|---|
| `mooring-web` | Starts the production FastAPI server & UI dashboard |
| `mooring-scan --state CA` | Executes an end-to-end scan pipeline for a coastal state |
| `mooring-refilter-all` | Re-evaluates all database fields against OpenStreetMap dock/marina filters |
| `mooring-generate-candidates` | Generates KML scan tiles from NOAA navigational datasets |
| `mooring-parse-kml` | Parses site KML files into structured tile split configurations |
| `mooring-fetch` | Downloads satellite imagery tiles for pre-planned sites |
| `mooring-train` | Fine-tunes YOLO-OBB boat detection models on custom imagery |
| `mooring-evaluate` | Evaluates detection accuracy metrics on validation split |

Run `mooring-scan --help` for full argument details.

---

## 🧪 Running Tests

Run the test suite using `pytest`:

```bash
pytest tests/
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
