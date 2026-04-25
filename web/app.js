const map = L.map('map').setView([40.7128, -74.006], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OSM' }).addTo(map);
const drawnItems = new L.FeatureGroup(); map.addLayer(drawnItems);
new L.Control.Draw({ edit: { featureGroup: drawnItems }, draw: { polygon:false, polyline:false, circle:false, marker:false, circlemarker:false, rectangle:true } }).addTo(map);

let currentBbox = null;
function getScale(){
  const scaleSel = document.getElementById('scale').value;
  if (scaleSel === 'custom') return Number(document.getElementById('scaleCustom').value || 50000);
  document.getElementById('scaleCustom').value = scaleSel;
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

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers(); drawnItems.addLayer(e.layer);
  const b = e.layer.getBounds();
  currentBbox = [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()];
  refreshInfo();
});
document.getElementById('scale').addEventListener('change', refreshInfo);
document.getElementById('scaleCustom').addEventListener('input', refreshInfo);

document.getElementById('locate').onclick = async () => {
  const city = document.getElementById('city').value;
  const resp = await fetch(`/api/geocode?city=${encodeURIComponent(city)}`);
  const data = await resp.json();
  map.setView([data.lat, data.lon], 13);
};

let pollTimer = null;
document.getElementById('generate').onclick = async () => {
  if (!currentBbox) { alert('Please draw a rectangle first.'); return; }
  const body = {
    city: document.getElementById('city').value || null,
    bbox: currentBbox,
    scale: getScale(),
    mode: document.getElementById('mode').value,
    crop_cm: (document.getElementById('cropW').value && document.getElementById('cropH').value) ? [Number(document.getElementById('cropW').value), Number(document.getElementById('cropH').value)] : null,
    tile_cm: (document.getElementById('tileW').value && document.getElementById('tileH').value) ? [Number(document.getElementById('tileW').value), Number(document.getElementById('tileH').value)] : null,
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
      const dl = document.getElementById('download');
      dl.href = `/api/jobs/${job_id}/download`;
      dl.style.display = 'inline-block';
    }
    if (j.status === 'error') clearInterval(pollTimer);
  }, 1000);
};
