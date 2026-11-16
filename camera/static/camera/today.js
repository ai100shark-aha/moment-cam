/* '오늘' 화면: 한 장씩 올리기/지우기, 여러 장 묶어 올리기, 블로그 초안 복사 */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  let toastTimer;
  function toast(text) {
    const el = $('toast');
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
  }
  async function post(path, body) {
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      return { ok: res.ok, data: await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, data: { error: '신호가 없어요. 잠시 뒤 다시 시도해 주세요.' } };
    }
  }

  document.querySelectorAll('.photo').forEach((li) => {
    const id = li.dataset.id;
    const pub = li.querySelector('.act-publish');
    const del = li.querySelector('.act-cancel');
    if (pub) pub.addEventListener('click', async () => {
      pub.disabled = true;
      pub.textContent = '올리는 중…';
      const res = await post(`/api/photos/${id}/publish/`);
      if (!res.ok) toast(res.data.error || '올리지 못했어요');
      location.reload();
    });
    if (del) del.addEventListener('click', async () => {
      del.disabled = true;
      const res = await post(`/api/photos/${id}/cancel/`);
      if (res.ok) li.remove(); else { toast(res.data.error || '지우지 못했어요'); del.disabled = false; }
    });
  });

  const bundleBtn = $('bundleBtn');
  const picked = () => [...document.querySelectorAll('.pick-box:checked')].map((b) => b.value);
  function paintBundle() {
    if (!bundleBtn) return;
    const n = picked().length;
    bundleBtn.disabled = n === 0 || n > 10;
    bundleBtn.textContent = n === 0 ? '사진을 골라 주세요'
      : n > 10 ? '10장까지만 묶을 수 있어요'
        : `고른 사진 ${n}장 피드에 묶어 올리기`;
  }
  document.querySelectorAll('.pick-box').forEach((b) => b.addEventListener('change', paintBundle));
  if (bundleBtn) bundleBtn.addEventListener('click', async () => {
    bundleBtn.disabled = true;
    bundleBtn.textContent = '올리는 중…';
    const res = await post('/api/bundle/', { ids: picked(), caption: $('bundleCaption').value });
    if (res.ok) { toast('피드에 올렸어요'); setTimeout(() => { location.href = location.pathname + location.search.replace(/[?&]finish=1/, ''); }, 900); }
    else { toast(res.data.error || '올리지 못했어요'); paintBundle(); }
  });

  const copyBtn = $('copyBtn');
  if (copyBtn) copyBtn.addEventListener('click', async () => {
    const text = `${$('blogTitle').value}\n\n${$('blogBody').value}`;
    try {
      await navigator.clipboard.writeText(text);
      toast('복사했어요. 블로그에 붙여 넣어 주세요');
    } catch {
      $('blogBody').select();
      toast('본문을 길게 눌러 복사해 주세요');
    }
  });
})();
