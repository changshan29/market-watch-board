// background.js — Service Worker
// content_script 直接用 fetch 推送，background 只保留图片下载能力备用

// 把图片 URL 下载转成 base64
async function urlToBase64(imgUrl) {
  try {
    const r = await fetch(imgUrl);
    if (!r.ok) return null;
    const blob = await r.blob();
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    return `data:${blob.type || 'image/jpeg'};base64,${btoa(binary)}`;
  } catch { return null; }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'FETCH_IMAGE_BASE64') {
    urlToBase64(msg.url)
      .then(b64 => sendResponse({ ok: !!b64, b64 }))
      .catch(() => sendResponse({ ok: false, b64: null }));
    return true;
  }
});
