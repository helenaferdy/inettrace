# Inettrace - Traceroute Visualizer / BGP Path Emulator

A FastAPI web application that performs live traceroutes to user-selected global targets, geolocates each network hop, and plots the path on an interactive Leaflet.js world map. Enriches each hop with ISP/ASN data, latency calculations, submarine cable transit labels, and IXP coordinate snapping.

## Features
- Interactive world map visualization of traceroute paths
- ASN and ISP enrichment per hop
- Submarine cable transit labeling
- IXP coordinate snapping
- Latency computation per hop

## Setup
```bash
pip install -r requirements.txt
python main.py
```