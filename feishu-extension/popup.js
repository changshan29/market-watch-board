const DEFAULT_URL = 'https://market-watch-board-production.up.railway.app';

const serverUrlEl = document.getElementById('serverUrl');
const groupNameEl = document.getElementById('groupName');
const saveBtn = document.getElementById('saveBtn');
const clearBtn = document.getElementById('clearBtn');
const lastSentEl = document.getElementById('lastSent');
const totalSentEl = document.getElementById('totalSent');

// 加载已保存配置
chrome.storage.local.get(['serverUrl', 'groupName'], items => {
  serverUrlEl.value = items.serverUrl || DEFAULT_URL;
  groupNameEl.value = items.groupName || '飞书群';
});

// 读取 content_script 存在 sessionStorage 的统计（通过注入脚本）
chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
  const tab = tabs[0];
  if (!tab || !tab.url || !tab.url.includes('feishu.cn')) {
    lastSentEl.textContent = '请打开飞书网页版';
    totalSentEl.textContent = '-';
    return;
  }
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      try {
        return JSON.parse(sessionStorage.getItem('_feishu_stats') || '{}');
      } catch {
        return {};
      }
    },
  }, results => {
    if (chrome.runtime.lastError || !results || !results[0]) return;
    const stats = results[0].result || {};
    lastSentEl.textContent = stats.lastSent
      ? new Date(stats.lastSent).toLocaleTimeString('zh-CN')
      : '尚未采集';
    totalSentEl.textContent = stats.total != null ? stats.total + ' 条' : '-';
  });
});

saveBtn.addEventListener('click', () => {
  const url = serverUrlEl.value.trim().replace(/\/$/, '');
  const group = groupNameEl.value.trim() || '飞书群';
  chrome.storage.local.set({ serverUrl: url, groupName: group }, () => {
    saveBtn.textContent = '已保存 ✓';
    saveBtn.style.background = '#52c41a';
    setTimeout(() => {
      saveBtn.textContent = '保存';
      saveBtn.style.background = '#1677ff';
    }, 1500);
  });
});

clearBtn.addEventListener('click', () => {
  chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    const tab = tabs[0];
    if (!tab || !tab.url || !tab.url.includes('feishu.cn')) {
      alert('请先打开飞书网页版');
      return;
    }
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        sessionStorage.removeItem('_feishu_sent');
        sessionStorage.removeItem('_feishu_stats');
      },
    }, () => {
      clearBtn.textContent = '已清除 ✓';
      setTimeout(() => { clearBtn.textContent = '清除已发记录'; }, 1500);
      lastSentEl.textContent = '-';
      totalSentEl.textContent = '-';
    });
  });
});
