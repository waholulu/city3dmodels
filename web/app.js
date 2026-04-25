const map = L.map('map').setView([40.7128, -74.006], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OSM' }).addTo(map);
const drawnItems = new L.FeatureGroup(); map.addLayer(drawnItems);
const clipLayer = new L.FeatureGroup(); map.addLayer(clipLayer);
new L.Control.Draw({ edit: { featureGroup: drawnItems }, draw: { polygon:false, polyline:false, circle:false, marker:false, circlemarker:false, rectangle:true } }).addTo(map);

// show/hide the custom scale input
const scaleCustomInput = document.getElementById('scaleCustom');
document.getElementById('scale').addEventListener('change', function() {
  scaleCustomInput.style.display = this.value === 'custom' ? 'block' : 'none';
});
scaleCustomInput.style.display = 'none';  // hidden unless custom is selected

let currentBbox = null;

function getScale(){
  const scaleSel = document.getElementById('scale').value;
  if (scaleSel === 'custom') return Number(scaleCustomInput.value || 50000);
  scaleCustomInput.value = scaleSel;
  return Number(scaleSel);
}

function bboxMeters(b){
  const southWest = L.latLng(b[0], b[1]);
  const southEast = L.latLng(b[0], b[3]);
  const northWest = L.latLng(b[2], b[1]);
  return [southWest.distanceTo(southEast), southWest.distanceTo(northWest)];
}

function refreshInfo(){
  if (!currentBbox) return;
  const scale = getScale();
  const [w,h] = bboxMeters(currentBbox);
  const pw = w*100/scale, ph = h*100/scale;
  document.getElementById('info').innerText =
    `bbox: s=${currentBbox[0].toFixed(5)} w=${currentBbox[1].toFixed(5)} n=${currentBbox[2].toFixed(5)} e=${currentBbox[3].toFixed(5)}\n`+
    `Selected area: ${w.toFixed(1)} m × ${h.toFixed(1)} m\n`+
    `At 1:${scale}: ${pw.toFixed(2)} cm × ${ph.toFixed(2)} cm`;
}

function mToLatDeg(m){ return m / 111320; }
function mToLonDeg(m, lat){ return m / (111320 * Math.cos(lat * Math.PI / 180)); }

const MAX_TILE_CELLS = 200;

function updateClipBoundary(){
  clipLayer.clearLayers();
  if (!currentBbox) return;
  const mode = document.getElementById('mode').value;
  if (mode === 'none' || mode === 'filter') return;

  const scale = getScale();
  const centerLat = (currentBbox[0] + currentBbox[2]) / 2;
  const centerLon = (currentBbox[1] + currentBbox[3]) / 2;
  const dashStyle = { color: '#e63946', weight: 2, dashArray: '10 6', fill: true, fillColor: '#e63946', fillOpacity: 0.06, interactive: false };

  if (mode === 'clip') {
    const cropW = Number(document.getElementById('cropW').value);
    const cropH = Number(document.getElementById('cropH').value);
    let s, n, w, e;
    if (cropW > 0 && cropH > 0) {
      const halfW = cropW * scale / 200;
      const halfH = cropH * scale / 200;
      s = centerLat - mToLatDeg(halfH);
      n = centerLat + mToLatDeg(halfH);
      w = centerLon - mToLonDeg(halfW, centerLat);
      e = centerLon + mToLonDeg(halfW, centerLat);
    } else {
      [s, w, n, e] = [currentBbox[0], currentBbox[1], currentBbox[2], currentBbox[3]];
    }
    L.rectangle([[s, w], [n, e]], dashStyle)
      .bindTooltip('Clip boundary', { permanent: false })
      .addTo(clipLayer);
  } else if (mode === 'tile') {
    const tileW = Number(document.getElementById('tileW').value) || 10;
    const tileH = Number(document.getElementById('tileH').value) || 15;
    const latStep = mToLatDeg(tileH * scale / 100);
    const lonStep = mToLonDeg(tileW * scale / 100, centerLat);
    const totalLat = currentBbox[2] - currentBbox[0];
    const totalLon = currentBbox[3] - currentBbox[1];
    const nRows = Math.ceil(totalLat / latStep);
    const nCols = Math.ceil(totalLon / lonStep);

    if (nRows * nCols > MAX_TILE_CELLS) {
      // too many tiles to draw individually — just show the outer boundary
      L.rectangle([[currentBbox[0], currentBbox[1]], [currentBbox[2], currentBbox[3]]], dashStyle)
        .bindTooltip(`Tile boundary (${nRows}×${nCols} tiles — zoom in to see grid)`, { permanent: false })
        .addTo(clipLayer);
      return;
    }

    const tileStyle = { ...dashStyle, fillOpacity: 0 };
    for (let r = 0; r < nRows; r++) {
      for (let c = 0; c < nCols; c++) {
        const s = currentBbox[0] + r * latStep;
        const w = currentBbox[1] + c * lonStep;
        L.rectangle([[s, w], [s + latStep, w + lonStep]], tileStyle)
          .bindTooltip(`Tile ${r + 1}-${c + 1} (${tileW}×${tileH} cm)`, { permanent: false })
          .addTo(clipLayer);
      }
    }
  }
}

function bboxFromLayer(layer){
  const b = layer.getBounds();
  return [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()];
}

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  currentBbox = bboxFromLayer(e.layer);
  refreshInfo();
  updateClipBoundary();
});

map.on(L.Draw.Event.EDITED, (e) => {
  e.layers.eachLayer(layer => { currentBbox = bboxFromLayer(layer); });
  refreshInfo();
  updateClipBoundary();
});

map.on(L.Draw.Event.DELETED, () => {
  currentBbox = null;
  clipLayer.clearLayers();
  document.getElementById('info').innerText = '';
});

['scale', 'mode', 'cropW', 'cropH', 'tileW', 'tileH'].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener('change', () => { refreshInfo(); updateClipBoundary(); });
  el.addEventListener('input',  () => { refreshInfo(); updateClipBoundary(); });
});
scaleCustomInput.addEventListener('input', () => { refreshInfo(); updateClipBoundary(); });

document.getElementById('locate').onclick = async () => {
  const city = document.getElementById('city').value;
  const resp = await fetch(`/api/geocode?city=${encodeURIComponent(city)}`);
  const data = await resp.json();
  map.setView([data.lat, data.lon], 13);
};

let pollTimer = null;
document.getElementById('generate').onclick = async () => {
  if (!currentBbox) { alert('Please draw a rectangle first.'); return; }

  const dl = document.getElementById('download');
  dl.style.display = 'none';
  dl.href = '#';

  const body = {
    city: document.getElementById('city').value || null,
    bbox: currentBbox,
    scale: getScale(),
    mode: document.getElementById('mode').value,
    crop_cm: (document.getElementById('cropW').value && document.getElementById('cropH').value)
      ? [Number(document.getElementById('cropW').value), Number(document.getElementById('cropH').value)]
      : null,
    tile_cm: (document.getElementById('tileW').value && document.getElementById('tileH').value)
      ? [Number(document.getElementById('tileW').value), Number(document.getElementById('tileH').value)]
      : null,
    base_mm: Number(document.getElementById('baseMm').value || 1),
    output_name: document.getElementById('outputName').value || null,
    verbose: true,
  };

  document.getElementById('logs').textContent = 'Submitting job...\n';
  const resp = await fetch('/api/generate', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const { job_id } = await resp.json();

  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const r = await fetch(`/api/jobs/${job_id}`);
    const j = await r.json();
    document.getElementById('logs').textContent = j.logs.join('\n') + (j.error ? `\nERROR: ${j.error}` : '');
    if (j.status === 'done') {
      clearInterval(pollTimer);
      dl.href = `/api/jobs/${job_id}/download`;
      dl.style.display = 'inline-block';
    }
    if (j.status === 'error') clearInterval(pollTimer);
  }, 1000);
};
