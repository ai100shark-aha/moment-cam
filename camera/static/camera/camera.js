/* 순간카메라 촬영 화면
 * 흐름: 촬영 → (레이스면 기록을 사진에 새김) → 휴대폰 대기열에 저장 → 서버로 올림
 *       → AI 캡션 도착 → 취소 가능 시간(카운트다운) → 게시
 * 신호가 없으면 대기열에 남아 있다가 신호가 잡히면 자동으로 올라갑니다.
 */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const boot = JSON.parse($('state').textContent);
  let settings = boot.settings;
  let race = boot.race; // {id, name, started_at} 또는 null

  // ---- 작은 도구들 -------------------------------------------------------
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const store = {
    get(key, fallback) {
      try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
    },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장 공간 없음 */ } },
  };
  let toastTimer;
  function toast(text, ms = 3200) {
    const el = $('toast');
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, ms);
  }
  async function api(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  }

  // ---- 휴대폰 안 대기열 (IndexedDB) --------------------------------------
  const queue = (() => {
    let dbp;
    const open = () => dbp || (dbp = new Promise((resolve, reject) => {
      const req = indexedDB.open('momentcam', 1);
      req.onupgradeneeded = () => req.result.createObjectStore('queue', { keyPath: 'client_id' });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }));
    const run = async (mode, fn) => {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('queue', mode);
        const req = fn(tx.objectStore('queue'));
        tx.oncomplete = () => resolve(req && req.result);
        tx.onerror = () => reject(tx.error);
      });
    };
    return {
      add: (item) => run('readwrite', (s) => s.put(item)),
      remove: (id) => run('readwrite', (s) => s.delete(id)),
      all: async () => ((await run('readonly', (s) => s.getAll())) || [])
        .sort((a, b) => a.taken_at.localeCompare(b.taken_at)),
    };
  })();

  // ---- 모드와 화면 표시 --------------------------------------------------
  let mode = store.get('mc.mode', 'daily') === 'race' && race ? 'race' : 'daily';
  const target = () => (mode === 'race' ? 'story' : settings.daily_target);

  function render() {
    document.querySelectorAll('.modes button').forEach((b) => {
      b.setAttribute('aria-pressed', String(b.dataset.mode === mode));
    });
    const isRace = mode === 'race';
    const pill = $('statusPill');
    pill.classList.toggle('live', isRace);
    pill.classList.toggle('off', !isRace && !settings.post_instagram);
    if (isRace) {
      $('statusText').textContent = '레이스 중계 중';
      $('statusSub').textContent = race ? `· ${race.name}` : '';
    } else {
      $('statusText').textContent = settings.post_instagram ? '자동 게시 켜짐' : '자동 게시 꺼짐';
      $('statusSub').textContent = settings.post_instagram ? '· 인스타그램' : '· 사진만 모아요';
    }
    $('racePanel').hidden = !isRace;
    $('chips').hidden = isRace;
    $('chipAi').hidden = !settings.ai_caption;
    $('chipTarget').textContent = !settings.post_instagram ? '모아 두기'
      : settings.daily_batch ? '모아서 한 번에 게시'
        : target() === 'story' ? '스토리로 게시' : '피드로 게시';
    $('shutter').classList.toggle('race', isRace);
    $('flipBtn').hidden = isRace;
    $('finishBtn').hidden = !isRace;
    $('hint').textContent = isRace
      ? '달리는 중엔 스토리로, 완주하면 베스트 사진을 피드에 묶어 올려요'
      : !settings.post_instagram || settings.daily_batch ? "찍은 사진은 '오늘' 화면에 모여요"
        : settings.cancel_seconds ? `찍으면 ${settings.cancel_seconds}초 뒤 자동으로 올라가요`
          : '찍은 뒤 확인하면 올라가요';
    renderRace();
  }

  function setMode(next) {
    mode = next;
    store.set('mc.mode', mode);
    render();
    if (mode === 'race') startTracking(); else stopTracking();
  }

  document.querySelectorAll('.modes button').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.mode === mode) return;
    if (b.dataset.mode === 'race' && !race) { $('raceDialog').showModal(); return; }
    setMode(b.dataset.mode);
  }));

  // ---- 레이스: 시간·거리 재기 --------------------------------------------
  // track = {raceId, meters, last:{lat,lng,t}, section}
  let track = store.get('mc.track', null);
  let watchId = null;
  let lastFix = null;

  function ensureTrack() {
    if (!race) return;
    if (!track || track.raceId !== race.id) {
      track = { raceId: race.id, meters: 0, last: null, section: '' };
      store.set('mc.track', track);
    }
  }
  function haversine(a, b) {
    const R = 6371000, rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
    const h = Math.sin(dLat / 2) ** 2
      + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function onPosition(pos) {
    const fix = { lat: pos.coords.latitude, lng: pos.coords.longitude, t: pos.timestamp };
    lastFix = fix;
    if (!track || pos.coords.accuracy > 40) return;
    if (track.last) {
      const d = haversine(track.last, fix);
      const dt = Math.max(1, (fix.t - track.last.t) / 1000);
      if (d < 8) return; // 제자리 흔들림은 무시
      if (d / dt <= 12) track.meters += d; // 사람이 낼 수 없는 속도는 GPS 튐으로 보고 버림
    }
    track.last = fix;
    store.set('mc.track', track);
    renderRace();
  }
  function startTracking() {
    ensureTrack();
    if (watchId === null && navigator.geolocation) {
      watchId = navigator.geolocation.watchPosition(onPosition, () => {}, {
        enableHighAccuracy: true, maximumAge: 5000, timeout: 20000,
      });
    }
  }
  function stopTracking() {
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  const elapsedSeconds = () => (race ? Math.max(0, Math.round((Date.now() - new Date(race.started_at)) / 1000)) : 0);
  const fmtTime = (sec, withSec) => {
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return `${h}:${String(m).padStart(2, '0')}${withSec ? ':' + String(s).padStart(2, '0') : ''}`;
  };
  function raceNumbers() {
    const km = track ? track.meters / 1000 : 0;
    const sec = elapsedSeconds();
    let pace = '-';
    if (km >= 0.2) {
      const p = sec / km;
      pace = `${Math.floor(p / 60)}'${String(Math.round(p % 60)).padStart(2, '0')}"`;
    }
    return { km, sec, pace, section: (track && track.section) || '' };
  }
  function renderRace() {
    if (mode !== 'race') return;
    const n = raceNumbers();
    $('rDist').textContent = n.km.toFixed(1);
    $('rTime').textContent = fmtTime(n.sec);
    $('rPace').textContent = n.pace;
    $('rSection').textContent = n.section || '구간을 적어 보세요';
  }
  setInterval(renderRace, 15000);

  $('raceDialogCancel').addEventListener('click', () => $('raceDialog').close());
  $('raceForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('raceNameInput').value.trim();
    if (!name) return;
    try {
      const res = await api('/api/race/start/', { name });
      if (!res.ok) throw new Error();
      race = res.data.race;
      track = null;
      $('raceDialog').close();
      setMode('race');
      toast(`${race.name} 시작! 잘 달리고 오세요`);
    } catch {
      toast('신호가 없어 레이스를 시작하지 못했어요');
    }
  });

  $('racePanel').addEventListener('click', () => {
    const n = raceNumbers();
    $('sectionInput').value = n.section;
    $('distInput').value = n.km.toFixed(1);
    $('editDialog').showModal();
  });
  $('editDialogCancel').addEventListener('click', () => $('editDialog').close());
  $('editForm').addEventListener('submit', (e) => {
    e.preventDefault();
    ensureTrack();
    track.section = $('sectionInput').value.trim();
    const km = parseFloat($('distInput').value);
    if (!Number.isNaN(km) && km >= 0 && Math.abs(km - track.meters / 1000) >= 0.05) {
      track.meters = km * 1000;
      track.last = null; // 고친 지점부터 다시 잽니다
    }
    store.set('mc.track', track);
    $('editDialog').close();
    renderRace();
  });

  $('finishBtn').addEventListener('click', () => $('finishDialog').showModal());
  $('finishDialogCancel').addEventListener('click', () => $('finishDialog').close());
  $('finishForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const res = await api('/api/race/finish/');
      if (!res.ok) throw new Error();
      race = null;
      stopTracking();
      store.set('mc.mode', 'daily');
      location.href = '/today/?finish=1';
    } catch {
      $('finishDialog').close();
      toast('신호가 없어요. 신호가 잡히면 다시 눌러 주세요');
    }
  });

  // ---- 카메라 ------------------------------------------------------------
  const video = $('video');
  let facing = store.get('mc.facing', 'environment');
  let stream = null;

  async function startCamera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: facing, width: { ideal: 1920 }, height: { ideal: 1080 } },
      });
      video.srcObject = stream;
      video.classList.toggle('mirror', facing === 'user');
      $('noCamera').hidden = true;
    } catch {
      stream = null;
      $('noCamera').hidden = false;
    }
  }
  $('flipBtn').addEventListener('click', () => {
    facing = facing === 'user' ? 'environment' : 'user';
    store.set('mc.facing', facing);
    startCamera();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      if (!stream || stream.getTracks().some((t) => t.readyState === 'ended')) startCamera();
      refreshState();
      flush();
    }
  });

  // 사진을 게시 비율에 맞춰 잘라 캔버스에 그립니다 (피드 4:5, 스토리 9:16).
  function drawCover(source, sw, sh, mirror) {
    // 스토리는 항상 9:16. 피드는 세로로 찍으면 4:5, 가로로 찍으면 4:3 (인스타그램 피드 허용 범위 안).
    const landscape = sw > sh;
    const ratio = target() === 'story' ? 9 / 16 : landscape ? 4 / 3 : 4 / 5;
    const W = landscape && target() !== 'story' ? 1440 : 1080;
    const H = Math.round(W / ratio);
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    const scale = Math.max(W / sw, H / sh);
    const dw = sw * scale, dh = sh * scale;
    ctx.save();
    if (mirror) { ctx.translate(W, 0); ctx.scale(-1, 1); }
    ctx.drawImage(source, (W - dw) / 2, (H - dh) / 2, dw, dh);
    ctx.restore();
    return canvas;
  }

  // 레이스 기록을 사진 아래쪽에 새깁니다.
  function drawRaceOverlay(canvas, n) {
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    const pad = 48, boxH = n.section ? 330 : 240, x = pad, y = H - boxH - 150, w = W - pad * 2;
    ctx.fillStyle = 'rgba(14,15,17,0.78)';
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, boxH, 44); else ctx.rect(x, y, w, boxH);
    ctx.fill();
    const sans = "'IBM Plex Sans KR', sans-serif";
    const cols = [['거리', `${n.km.toFixed(1)} km`], ['경과 시간', fmtTime(n.sec, true)], ['페이스', n.pace]];
    cols.forEach(([label, value], i) => {
      const cx = x + 44 + (i * (w - 88)) / 3;
      ctx.fillStyle = '#A7ABB2';
      ctx.font = `500 34px ${sans}`;
      ctx.fillText(label, cx, y + 76);
      ctx.fillStyle = '#F4F2EE';
      ctx.font = `700 68px 'Space Grotesk', ${sans}`;
      ctx.fillText(value, cx, y + 164);
    });
    if (n.section) {
      ctx.fillStyle = '#3A3E46';
      ctx.fillRect(x + 44, y + 212, w - 88, 2);
      ctx.fillStyle = '#FF7A3D';
      ctx.beginPath(); ctx.arc(x + 62, y + 268, 12, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#F4F2EE';
      ctx.font = `600 42px ${sans}`;
      ctx.fillText(n.section, x + 96, y + 283);
    }
    if (race) {
      ctx.fillStyle = '#FF7A3D';
      ctx.font = `700 40px ${sans}`;
      ctx.fillText(race.name, x + 8, y - 28);
    }
  }

  // 휴대폰이 얼굴 인식을 지원하면 직접 세어 봅니다 (지원하지 않으면 서버의 AI가 셉니다).
  async function countFaces(canvas) {
    if (!('FaceDetector' in window)) return null;
    try { return (await new window.FaceDetector({ fastMode: true }).detect(canvas)).length; } catch { return null; }
  }

  let liveId = null; // 방금 찍어서 화면에서 바로 확인할 사진
  let busy = false;

  async function shoot(source, sw, sh, mirror) {
    if (busy) return;
    busy = true;
    try {
      const canvas = drawCover(source, sw, sh, mirror);
      const faces = await countFaces(canvas); // 기록을 새기기 전에 셉니다
      const n = raceNumbers();
      if (mode === 'race') drawRaceOverlay(canvas, n);
      const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.9));
      const item = {
        client_id: crypto.randomUUID(),
        blob, mode, faces,
        taken_at: new Date().toISOString(),
        lat: lastFix && lastFix.lat, lng: lastFix && lastFix.lng,
      };
      if (mode === 'race') Object.assign(item, { distance_km: n.km, elapsed_seconds: n.sec, section: n.section });
      await queue.add(item);
      liveId = item.client_id;
      $('thumb').style.backgroundImage = `url(${URL.createObjectURL(blob)})`;
      $('flash').classList.remove('on'); void $('flash').offsetWidth; $('flash').classList.add('on');
      if (navigator.vibrate) navigator.vibrate(30);
      updateBanner();
      flush();
    } finally {
      busy = false;
    }
  }
  $('shutter').addEventListener('click', () => {
    if (!stream || !video.videoWidth) { $('filePick').click(); return; }
    shoot(video, video.videoWidth, video.videoHeight, facing === 'user');
  });
  $('filePick').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    // <img>로 읽어야 아이폰에서 사진 방향(EXIF)이 바르게 적용됩니다.
    // (createImageBitmap은 사파리 계열에서 방향 정보를 무시해 사진이 옆으로 누워요.)
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      await shoot(img, img.naturalWidth, img.naturalHeight, false);
    } catch { toast('사진을 읽지 못했어요'); } finally { URL.revokeObjectURL(url); }
  });

  // ---- 서버로 올리기 -----------------------------------------------------
  let flushing = false;

  async function updateBanner() {
    const items = await queue.all().catch(() => []);
    const n = items.length;
    $('queueBadge').hidden = n === 0;
    $('queueBadge').textContent = n;
    $('banner').hidden = n === 0 || (navigator.onLine && n === 1 && flushing);
    if (!navigator.onLine) {
      $('bannerTitle').textContent = `신호 없음 · 사진 ${n}장 대기 중`;
      $('bannerSub').textContent = '신호가 잡히면 자동으로 올려요';
    } else {
      $('bannerTitle').textContent = `사진 ${n}장 올리는 중`;
      $('bannerSub').textContent = '잠시만 기다려 주세요';
    }
  }

  async function upload(item) {
    const form = new FormData();
    form.append('image', item.blob, 'photo.jpg');
    ['client_id', 'mode', 'taken_at', 'lat', 'lng', 'distance_km', 'elapsed_seconds', 'section'].forEach((k) => {
      if (item[k] !== undefined && item[k] !== null && item[k] !== '') form.append(k, item[k]);
    });
    if (item.faces !== null && item.faces !== undefined) form.append('client_faces', item.faces);
    const res = await fetch('/api/photos/', { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: form });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  }

  async function flush() {
    if (flushing) return;
    flushing = true;
    try {
      await retryPublishes();
      for (const item of await queue.all()) {
        let res;
        try { res = await upload(item); } catch {
          // 신호 없음: 대기열에 두고 다음 기회에 다시 올립니다.
          if (!settings.offline_queue) {
            await queue.remove(item.client_id);
            toast('신호가 없어 올리지 못했어요');
            continue;
          }
          break;
        }
        if (res.status === 401 || res.status === 403) { toast('로그인이 풀렸어요. 다시 로그인해 주세요'); break; }
        if (res.status >= 500) break; // 서버 문제: 나중에 다시
        await queue.remove(item.client_id);
        if (res.ok) await afterUpload(item, res.data); else toast(res.data.error || '사진을 올리지 못했어요');
      }
    } finally {
      flushing = false;
      updateBanner();
    }
  }
  window.addEventListener('online', flush);
  window.addEventListener('offline', updateBanner);
  setInterval(() => { if (navigator.onLine) flush(); }, 30000);

  async function afterUpload(item, photo) {
    const isLive = item.client_id === liveId && Date.now() - new Date(item.taken_at) < 90000 && !sheetOpen();
    if (photo.status === 'posted' || photo.status === 'cancelled') return;
    if (photo.status === 'needs_consent') {
      if (isLive) openConsent(photo, item.blob); else toast("확인이 필요한 단체 사진이 있어요 · '오늘'에서 확인");
      return;
    }
    if (photo.status === 'queued') { toast("'오늘' 화면에 모아 두었어요"); return; }
    if (isLive) openPost(photo, item.blob);
    else await publish(photo.id, {}, true); // 늦게 올라온 사진은 바로 게시
  }

  // 신호가 끊겨 게시 요청이 못 간 사진은 기억해 두었다가 다시 보냅니다.
  async function publish(id, body, quiet) {
    try {
      const res = await api(`/api/photos/${id}/publish/`, body);
      if (res.ok) { if (!quiet) toast(res.data.target === 'story' ? '스토리에 올렸어요' : '피드에 올렸어요'); return true; }
      toast(`올리지 못했어요 · '오늘'에서 다시 시도할 수 있어요`);
      return false;
    } catch {
      const pending = store.get('mc.publish', []);
      pending.push({ id, body });
      store.set('mc.publish', pending);
      toast('신호가 없어요. 잡히면 바로 올릴게요');
      return false;
    }
  }
  async function retryPublishes() {
    const pending = store.get('mc.publish', []);
    if (!pending.length) return;
    const left = [];
    for (const p of pending) {
      try { await api(`/api/photos/${p.id}/publish/`, p.body); } catch { left.push(p); }
    }
    store.set('mc.publish', left);
  }

  // ---- 게시 직전 창 (취소 가능 시간) -------------------------------------
  const RING = 150.8;
  let current = null; // {photo, timer, total, left}
  const sheetOpen = () => !$('postSheet').hidden || !$('consentSheet').hidden;

  function openPost(photo, blob) {
    $('postImg').src = URL.createObjectURL(blob);
    $('postCaption').value = photo.caption || '';
    $('postTags').value = photo.hashtags || '';
    $('captionLabel').textContent = photo.caption ? 'AI가 쓴 캡션' : '캡션';
    const isStory = photo.target === 'story';
    $('captionCard').hidden = isStory; // 스토리는 캡션이 없어요
    $('postSub').textContent = isStory
      ? `인스타그램 스토리${photo.race_line ? ' · ' + photo.race_line : ''}`
      : '인스타그램 피드';
    current = { photo, total: photo.cancel_seconds, left: photo.cancel_seconds, timer: null };
    $('postSheet').hidden = false;
    if (current.total > 0) startCountdown(); else pauseCountdown('확인하고 올려 주세요');
    $('postNow').focus();
  }
  function paintCountdown() {
    $('ringNum').textContent = Math.ceil(current.left);
    $('ringBar').style.strokeDashoffset = RING * (1 - current.left / current.total);
    $('postTitle').textContent = `${Math.ceil(current.left)}초 뒤 자동으로 올라가요`;
  }
  function startCountdown() {
    paintCountdown();
    current.timer = setInterval(() => {
      current.left -= 0.2;
      if (current.left <= 0) { finishPost(true); return; }
      paintCountdown();
    }, 200);
  }
  function pauseCountdown(text) {
    if (!current) return;
    clearInterval(current.timer);
    current.timer = null;
    $('ringNum').textContent = '∥';
    $('ringBar').style.strokeDashoffset = RING;
    $('postTitle').textContent = text;
  }
  function closePost() {
    if (current) clearInterval(current.timer);
    current = null;
    $('postSheet').hidden = true;
  }
  async function finishPost(doPublish) {
    if (!current) return;
    const { photo } = current;
    const body = { caption: $('postCaption').value.trim(), hashtags: $('postTags').value.trim() };
    closePost();
    if (doPublish) await publish(photo.id, body);
    else {
      try { await api(`/api/photos/${photo.id}/cancel/`); toast('올리지 않았어요'); } catch { toast('신호가 없어 취소를 전하지 못했어요'); }
    }
  }
  $('postNow').addEventListener('click', () => finishPost(true));
  $('postCancel').addEventListener('click', () => finishPost(false));
  ['postCaption', 'postTags'].forEach((id) => $(id).addEventListener('focus', () => {
    pauseCountdown("고친 뒤 '지금 올리기'를 눌러 주세요");
  }));

  // ---- 단체 사진 확인 창 -------------------------------------------------
  let consent = null;
  function openConsent(photo, blob) {
    consent = { photo, blob };
    $('consentImg').src = URL.createObjectURL(blob);
    $('consentSheet').hidden = false;
    $('consentNo').focus();
  }
  $('consentNo').addEventListener('click', () => {
    consent = null;
    $('consentSheet').hidden = true;
    toast("올리지 않았어요 · 사진은 '오늘'에 있어요");
  });
  $('consentYes').addEventListener('click', async () => {
    const { photo } = consent;
    consent = null;
    $('consentSheet').hidden = true;
    await publish(photo.id, {});
  });

  // ---- 시작 --------------------------------------------------------------
  async function refreshState() {
    try {
      const res = await fetch('/api/state/');
      if (!res.ok) return;
      const data = await res.json();
      settings = data.settings;
      race = data.race;
      if (mode === 'race' && !race) setMode('daily'); else render();
    } catch { /* 신호 없음: 가지고 있던 설정으로 계속 */ }
  }

  render();
  if (mode === 'race') startTracking();
  startCamera();
  updateBanner();
  flush();
})();
