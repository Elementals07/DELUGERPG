// ==UserScript==
// @name         DelugeRPG Session Recorder (passive observer)
// @namespace    OrangeMonkey Scripts
// @version      1.0.4
// @description  One-button recorder of page changes while YOU play. Robust walkgrid sniffer (DOM+unsafeWindow), PokeDex, and team/box inventory capture. Zero network interference.
// @match        https://www.delugerpg.com/*
// @match        https://m.delugerpg.com/*
// @include      https://www.delugerpg.com/*
// @include      https://m.delugerpg.com/*
// @run-at       document-end
// @grant        none
// ==/UserScript==

/*
 * DELUGERPG PASSIVE SESSION RECORDER v1.0.3
 * 
 * FIXES IN v1.0.3:
 *  1. ZERO SPECULATIVE FETCHES: Uses W3C <template> elements (inert DocumentFragment)
 *     and strips/disables 'src' attributes to guarantee the browser NEVER initiates
 *     background image downloads or triggers 429 (Too Many Requests).
 *  2. FIXED URL REDACTION: Fixed relative URL bug that caused 'i.dstatic.com' to be
 *     appended to current page paths (/catch/retro+vanillite/i.dstatic.com/...).
 *  3. BUTTON & FORM PASS-THROUGH: Zero interference with form submissions or Cloudflare
 *     Turnstile. Pure passive listening without stopping event propagation.
 *  4. STORAGE SOFT CAP: Compresses chunks with deflate-raw into localStorage.
 */
(function () {
  'use strict';
  if (window.top !== window.self) return;   // ignore ad & challenge iframes

  function main() {

  // ---------- config ----------
  var K_STATE = 'dgr:state';
  var K_CHUNK = 'dgr:c:';
  var K_PEND = 'dgr:pending:';
  var MAX_CHARS = 4200000;      // soft cap on stored characters (~4 MB)
  var FLUSH_MS = 4000;          // flush buffer to a compressed chunk this often
  var FLUSH_EVENTS = 400;       // or when this many events are buffered
  var COALESCE_MS = 300;        // merge rapid attribute/text changes (animations)
  var SNAP_MAX = 400000;        // max chars for a page snapshot
  var HTML_MAX = 80000;         // max chars for one added-node fragment
  var VERSION = '1.0.3';

  var ADSEL = 'ins.adsbygoogle,iframe,[id^="google_ads"],[id^="oa-360"],[id^="aswift"],' +
    '[id^="div-gpt"],#menuad,.adCreator,.adtct,[class*="adsbygoogle"],[data-ad-status],' +
    '#tsb,.cf-turnstile,[id^="cf-"]';
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, LINK: 1, NOSCRIPT: 1, IFRAME: 1, META: 1, INS: 1 };
  var ATTRS = ['class', 'style', 'disabled', 'checked', 'value', 'hidden', 'aria-pressed',
    'aria-hidden', 'aria-valuenow', 'data-deadline', 'data-loca', 'data-avail', 'selected', 'open',
    'width', 'height', 'href', 'src'];

  var enc = new TextEncoder();

  // ---------- tab identity (only one tab records) ----------
  var tabId;
  try {
    tabId = sessionStorage.getItem('dgr:tab');
    if (!tabId) {
      tabId = Math.random().toString(36).slice(2, 10);
      sessionStorage.setItem('dgr:tab', tabId);
    }
  } catch (e) { tabId = 'x' + Math.random().toString(36).slice(2, 8); }

  // ---------- state helpers ----------
  function readState() {
    try { return JSON.parse(localStorage.getItem(K_STATE)) || {}; } catch (e) { return {}; }
  }
  function writeState(s) {
    try { localStorage.setItem(K_STATE, JSON.stringify(s)); return true; } catch (e) { return false; }
  }
  function chunkKeys() {
    var keys = [];
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && k.indexOf(K_CHUNK) === 0) keys.push(k);
    }
    keys.sort();
    return keys;
  }
  function clearData() {
    var rm = [];
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && (k.indexOf(K_CHUNK) === 0 || k.indexOf(K_PEND) === 0)) rm.push(k);
    }
    rm.forEach(function (k) { localStorage.removeItem(k); });
  }

  // ---------- binary helpers ----------
  var crcTable = (function () {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(b) {
    var c = 0xffffffff;
    for (var i = 0; i < b.length; i++) c = crcTable[(c ^ b[i]) & 255] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  function toB64(u8) {
    var s = '';
    for (var i = 0; i < u8.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    }
    return btoa(s);
  }
  function fromB64(b) {
    var s = atob(b);
    var u = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    return u;
  }
  async function deflateRaw(u8) {
    var cs = new CompressionStream('deflate-raw');
    var w = cs.writable.getWriter();
    w.write(u8);
    w.close();
    return new Uint8Array(await new Response(cs.readable).arrayBuffer());
  }

  function makeZip(entries) {
    var parts = [], central = [], off = 0;
    var d = new Date();
    var dt = ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xffff;
    var dd = (((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xffff;
    entries.forEach(function (e) {
      var nb = enc.encode(e.name);
      var lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true);
      lh.setUint16(4, 20, true);
      lh.setUint16(6, 0x0800, true);
      lh.setUint16(8, e.method, true);
      lh.setUint16(10, dt, true);
      lh.setUint16(12, dd, true);
      lh.setUint32(14, e.crc, true);
      lh.setUint32(18, e.data.length, true);
      lh.setUint32(22, e.usize, true);
      lh.setUint16(26, nb.length, true);
      lh.setUint16(28, 0, true);
      parts.push(new Uint8Array(lh.buffer), nb, e.data);

      var ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true);
      ch.setUint16(4, 20, true);
      ch.setUint16(6, 20, true);
      ch.setUint16(8, 0x0800, true);
      ch.setUint16(10, e.method, true);
      ch.setUint16(12, dt, true);
      ch.setUint16(14, dd, true);
      ch.setUint32(16, e.crc, true);
      ch.setUint32(20, e.data.length, true);
      ch.setUint32(24, e.usize, true);
      ch.setUint16(28, nb.length, true);
      ch.setUint16(30, 0, true);
      ch.setUint16(32, 0, true);
      ch.setUint16(34, 0, true);
      ch.setUint16(36, 0, true);
      ch.setUint32(38, 0, true);
      ch.setUint32(42, off, true);
      central.push(new Uint8Array(ch.buffer), nb);
      off += 30 + nb.length + e.data.length;
    });
    var csize = central.reduce(function (s, x) { return s + x.length; }, 0);
    var end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, csize, true);
    end.setUint32(16, off, true);
    return new Blob(parts.concat(central, [new Uint8Array(end.buffer)]), { type: 'application/zip' });
  }

  // ---------- UI: button in closed shadow root ----------
  var host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;';
  var root;
  try { root = host.attachShadow({ mode: 'closed' }); } catch (e) { root = host; }
  var btn = document.createElement('button');
  btn.style.cssText = 'font:600 12px/1 system-ui,sans-serif;padding:8px 12px;border-radius:6px;' +
    'border:1px solid #444;color:#fff;background:#2b6cb0;cursor:pointer;opacity:.92;box-shadow:0 2px 6px rgba(0,0,0,0.3);';
  root.appendChild(btn);
  document.body.appendChild(host);

  // ---------- recorder state ----------
  var rec = false;
  var st0 = 0;
  var buf = [];
  var inflight = [];
  var coal = new Map();
  var coalTimer = null;
  var flushTimer = null;
  var uiTimer = null;
  var queue = Promise.resolve();
  var observer = null;
  var perfObs = null;
  var full = false;
  var lastMap = null;
  var gridSeen = {};
  var maskRe = null;

  try {
    var un = window.n_user;
    if (typeof un === 'string' && un.length > 1) {
      maskRe = new RegExp(un.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
    }
  } catch (e) { /* ignore */ }

  function T() { return Math.floor((Date.now() - st0) / 1000); }
  function mask(s) { return (maskRe && typeof s === 'string') ? s.replace(maskRe, '\u00abme\u00bb') : s; }
  function redactToken(s) {
    if (s == null) return s;
    s = String(s);
    if (/^catch_/.test(s)) return 'catch_*';
    return s.replace(/[A-Za-z0-9]{12,}/g, '_');
  }
  function redactUrl(u) {
    if (!u) return '';
    try {
      var x = new URL(u, location.href);
      var p = x.pathname;
      if (/^\/catch\//.test(p)) p = '/catch/_';
      p = p.replace(/\/tok\/[^/]+/, '/tok/_').replace(/\/profile\/uid\/\d+/, '/profile/uid/_');
      p = p.split('/').map(function (s) { return /^[A-Za-z0-9_-]{16,}$/.test(s) ? '_' : s; }).join('/');
      // Retain protocol or use relative root to prevent browser from interpreting as relative path!
      return (x.host === location.host ? p : x.protocol + '//' + x.host + p);
    } catch (e) { return String(u).slice(0, 80); }
  }

  // ---------- DOM helpers ----------
  function elOf(n) { return n && n.nodeType === 1 ? n : (n && n.parentElement) || null; }
  function ignored(n) {
    var el = elOf(n);
    if (!el) return true;
    if (el === host) return true;
    try { return !!el.closest(ADSEL); } catch (e) { return false; }
  }
  function pathOf(n) {
    var el = elOf(n);
    var parts = [], depth = 0;
    while (el && el.nodeType === 1 && el !== document.documentElement && depth < 8) {
      if (el.id && !/\d{6,}/.test(el.id)) { parts.unshift('#' + el.id); break; }
      var s = el.tagName.toLowerCase();
      var cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(function (x) {
        return x && x.length < 24 && !/\d{4,}/.test(x);
      }).slice(0, 2);
      if (cls.length) s += '.' + cls.join('.');
      var p = el.parentElement;
      if (p) s += ':' + (Array.prototype.indexOf.call(p.children, el) + 1);
      parts.unshift(s);
      el = el.parentElement;
      depth++;
    }
    return parts.join('>');
  }
  function describe(n) {
    if (n.nodeType !== 1) return '#text';
    var s = n.tagName.toLowerCase();
    if (n.id && !/\d{6,}/.test(n.id)) s += '#' + n.id;
    var c = (n.getAttribute('class') || '').trim().split(/\s+/)[0];
    if (c && c.length < 24) s += '.' + c;
    return s;
  }

  // W3C <template> container: completely inert, does NOT trigger image or script network loads!
  var templateElem = document.createElement('template');

  function sanitizeHtmlString(htmlStr, max) {
    if (!htmlStr) return '';
    // Strip scripts, styles, iframes, and ads via fast regex before parsing
    var s = htmlStr.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
                   .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '')
                   .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '');
    templateElem.innerHTML = s;
    var frag = templateElem.content;
    
    // Neutralize any remaining media and sensitive attributes
    var all = frag.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      var n = all[i];
      if (SKIP_TAGS[n.tagName] || (n.matches && n.matches(ADSEL))) {
        n.remove();
        continue;
      }
      if (n.tagName === 'IMG' || n.tagName === 'SOURCE') {
        var src = n.getAttribute('src');
        if (src) {
          n.removeAttribute('src');
          n.setAttribute('data-src', redactUrl(src));
        }
        n.removeAttribute('srcset');
      }
      if (n.hasAttribute('href')) {
        n.setAttribute('href', redactUrl(n.getAttribute('href')));
      }
      if (n.classList && n.classList.contains('mpus')) {
        n.removeAttribute('title');
        n.removeAttribute('data-bs-original-title');
      }
      if (n.matches && n.matches('a.username')) n.textContent = '\u00abuser\u00bb';
      if (n.tagName === 'INPUT' && /^(text|search|password|email|tel|url|number|hidden)$/i.test(n.type || 'text')) {
        n.removeAttribute('value');
      }
    }

    var div = document.createElement('div');
    div.appendChild(frag.cloneNode(true));
    var out = mask(div.innerHTML.replace(/>\s+</g, '><'));
    templateElem.innerHTML = ''; // clean up
    if (out.length > max) out = out.slice(0, max) + '[TRUNC]';
    return out;
  }

  function htmlOf(el, max) {
    if (!el || el.nodeType !== 1) return '';
    return sanitizeHtmlString(el.outerHTML || '', max);
  }

  function snapshotBody() {
    return sanitizeHtmlString(document.body ? document.body.innerHTML : '', SNAP_MAX);
  }

  // ---------- event buffer ----------
  function push(ev) {
    buf.push(ev);
    if (buf.length >= FLUSH_EVENTS) flush();
  }
  function drainCoal() {
    if (coalTimer) { clearTimeout(coalTimer); coalTimer = null; }
    if (!coal.size) return;
    var t = T();
    coal.forEach(function (v) {
      buf.push(v.k === 'a' ? ['a', t, v.path, v.attr, v.val] : ['x', t, v.path, v.val]);
    });
    coal.clear();
  }
  function scheduleCoal() {
    if (!coalTimer) coalTimer = setTimeout(function () { coalTimer = null; drainCoal(); }, COALESCE_MS);
  }

  async function storeChunk(events) {
    var raw = enc.encode(JSON.stringify(events));
    var crc = crc32(raw);
    var def, m = 8;
    try { def = await deflateRaw(raw); } catch (e) { def = raw; m = 0; }
    var st = readState();
    var b64 = toB64(def);
    var rec2 = JSON.stringify({ c: crc, u: raw.length, m: m, d: b64 });
    if ((st.chars || 0) + rec2.length > MAX_CHARS) throw new Error('quota');
    var key = K_CHUNK + String(st.n || 0).padStart(6, '0');
    localStorage.setItem(key, rec2);
    st.n = (st.n || 0) + 1;
    st.chars = (st.chars || 0) + rec2.length;
    st.ev = (st.ev || 0) + events.length;
    writeState(st);
  }
  function onStoreError() {
    full = true;
    endCapture();
    updateUI();
  }
  function flush() {
    drainCoal();
    if (!buf.length) return;
    var ev = buf;
    buf = [];
    inflight.push(ev);
    queue = queue.then(function () { return storeChunk(ev); })
      .catch(onStoreError)
      .then(function () {
        var i = inflight.indexOf(ev);
        if (i >= 0) inflight.splice(i, 1);
      });
  }

  // ---------- mutation handling ----------
  function onMutations(recs) {
    if (!rec) return;
    var mapTouched = false;
    for (var i = 0; i < recs.length; i++) {
      var r = recs[i];
      var tgt = r.target;
      if (ignored(tgt)) continue;
      var te = elOf(tgt);
      if (te && (te.id === 'mapnum' || (te.parentElement && te.parentElement.id === 'mapnum'))) mapTouched = true;

      if (r.type === 'attributes') {
        var nm = r.attributeName;
        var val = tgt.getAttribute(nm);
        if (val === r.oldValue) continue;
        if (tgt.tagName === 'INPUT') {
          var ty = (tgt.type || 'text').toLowerCase();
          if (ty === 'hidden') continue;
          if (nm === 'value' && ['radio', 'checkbox', 'submit', 'button'].indexOf(ty) < 0) continue;
        }
        if (nm === 'href' || nm === 'src') val = redactUrl(val);
        var p = pathOf(tgt);
        coal.set('a|' + p + '|' + nm, { k: 'a', path: p, attr: nm, val: val == null ? null : mask(String(val).slice(0, 400)) });
        scheduleCoal();
      } else if (r.type === 'characterData') {
        var pe = elOf(tgt);
        var txt = tgt.data;
        if (pe && pe.closest && pe.closest('a.username')) txt = '\u00abuser\u00bb';
        var p2 = pathOf(tgt);
        coal.set('x|' + p2, { k: 'x', path: p2, val: mask(String(txt).slice(0, 500)) });
        scheduleCoal();
      } else if (r.type === 'childList') {
        drainCoal();
        var t = T();
        var pp = pathOf(tgt);
        var j, n;
        for (j = 0; j < r.removedNodes.length; j++) {
          n = r.removedNodes[j];
          if (n === host) continue;
          if (n.nodeType === 1 && SKIP_TAGS[n.tagName]) continue;
          if (n.nodeType === 3 && !n.data.trim()) continue;
          buf.push(['-', t, pp, describe(n)]);
        }
        for (j = 0; j < r.addedNodes.length; j++) {
          n = r.addedNodes[j];
          if (n === host || ignored(n)) continue;
          if (n.nodeType === 1) {
            if (SKIP_TAGS[n.tagName]) continue;
            var idx = Array.prototype.indexOf.call(tgt.childNodes, n);
            buf.push(['+', t, pp, idx, htmlOf(n, HTML_MAX)]);
          } else if (n.nodeType === 3 && n.data.trim()) {
            var pe2 = elOf(n);
            var tx = (pe2 && pe2.closest && pe2.closest('a.username')) ? '\u00abuser\u00bb' : n.data;
            buf.push(['T', t, pp, mask(tx.slice(0, 500))]);
          }
        }
        if (buf.length >= FLUSH_EVENTS) flush();
      }
    }
    if (mapTouched) setTimeout(checkMap, 350);
  }

  // ---------- user-action events ----------
  function labelOf(el) {
    if (el.closest && el.closest('a.username')) return '\u00abuser\u00bb';
    var t = (el.innerText || el.value || el.alt || '').replace(/\s+/g, ' ').trim().slice(0, 40);
    return mask(t);
  }
  function valOf(el) {
    var tag = el.tagName;
    if (tag === 'A') return redactUrl(el.getAttribute('href'));
    if (tag === 'INPUT') {
      var ty = (el.type || '').toLowerCase();
      if (['radio', 'checkbox', 'submit', 'button'].indexOf(ty) >= 0) return redactToken(el.value);
    }
    if (tag === 'SELECT') return redactToken(el.value);
    return '';
  }
  function onClick(e) {
    if (!rec) return;
    var t = e.target;
    if (!(t instanceof Element) || t === host) return;
    var el = t.closest('a,button,input,select,label,[role=button],.row,li,td,img') || t;
    push(['c', T(), 'click', pathOf(el), labelOf(el), valOf(el)]);
  }
  function onSubmit(e) {
    if (!rec) return;
    var f = e.target;
    var sm = e.submitter;
    push(['c', T(), 'submit', pathOf(f), redactUrl(f.getAttribute('action') || ''),
      sm ? redactToken(sm.name || '') : '', sm ? redactToken(sm.value || '') : '']);
  }
  function onChange(e) {
    if (!rec) return;
    var t = e.target;
    if (!(t instanceof Element)) return;
    var ty = (t.type || '').toLowerCase();
    if (t.tagName === 'SELECT' || ty === 'radio' || ty === 'checkbox') {
      push(['c', T(), 'change', pathOf(t), redactToken(t.value), t.checked ? 1 : 0]);
    }
  }

  // ---------- map readouts ----------
  function showToast(msg) {
    try {
      var toast = document.createElement('div');
      toast.textContent = msg;
      toast.style.cssText = 'position:fixed;top:15px;right:15px;background:#1b5e20;color:#fff;padding:8px 14px;border-radius:4px;z-index:999999;font-family:sans-serif;font-size:12px;font-weight:bold;box-shadow:0 2px 8px rgba(0,0,0,0.4);transition:opacity 0.5s;';
      document.body.appendChild(toast);
      setTimeout(function () {
        toast.style.opacity = '0';
        setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 500);
      }, 2500);
    } catch (e) { /* ignore */ }
  }

  function checkMap() {
    if (!rec) return;
    var m = document.getElementById('mapnum');
    var file = null, num = null;
    if (m) {
      try {
        var j = window.jQuery;
        if (j) { file = j(m).data('file'); num = j(m).data('num'); }
      } catch (e) { /* ignore */ }
      file = file || m.getAttribute('data-file');
      num = num || m.getAttribute('data-num');
    }
    if (!file && location.pathname.indexOf('/map') >= 0) {
      var mMatch = location.pathname.match(/\/map\/([a-zA-Z0-9]+)/);
      if (mMatch) file = mMatch[1];
    }
    if (file) {
      var key = file + '|' + (num || '');
      if (key !== lastMap) {
        lastMap = key;
        push(['m', T(), String(file), String(num || ''), (m ? m.textContent.trim() : file)]);
      }
    }

    var g = null;
    // 1. Check unsafeWindow (Tampermonkey / OrangeMonkey execution context)
    try {
      var uWin = (typeof unsafeWindow !== 'undefined') ? unsafeWindow : window;
      if (uWin.mapWalkgrid && typeof uWin.mapWalkgrid === 'string') {
        g = uWin.mapWalkgrid;
      } else if (uWin.walkgrid && uWin.walkgrid.length) {
        g = toB64(uWin.walkgrid);
      }
    } catch (e) { /* ignore */ }

    // 2. Check window scope
    if (!g) {
      try {
        if (typeof window.mapWalkgrid === 'string') g = window.mapWalkgrid;
        else if (window.walkgrid && window.walkgrid.length) g = toB64(window.walkgrid);
      } catch (e) { /* ignore */ }
    }

    // 3. Fallback: Parse inline <script> tags from DOM directly
    if (!g) {
      try {
        var scripts = document.querySelectorAll('script');
        for (var s = 0; s < scripts.length; s++) {
          var scText = scripts[s].textContent;
          if (scText && scText.indexOf('mapWalkgrid') >= 0) {
            var match = scText.match(/mapWalkgrid\s*=\s*["']([^"']+)["']/);
            if (match && match[1].length > 100) {
              g = match[1];
              break;
            }
          }
        }
      } catch (e) { /* ignore */ }
    }

    var mapKey = file || (m ? m.textContent.trim() : 'unknown');
    if (g && gridSeen[mapKey] !== g) {
      gridSeen[mapKey] = g;
      push(['g', T(), String(mapKey), g]);
      showToast('\u2714 Map walkgrid recorded: ' + mapKey + ' (' + g.length + ' chars)');
    }
  }

  // ---------- begin / end capture ----------
  var pagehideHandler = function () {
    if (!rec) return;
    drainCoal();
    var all = [];
    inflight.forEach(function (a) { all = all.concat(a); });
    all = all.concat(buf);
    if (all.length) {
      try { localStorage.setItem(K_PEND + tabId, JSON.stringify(all)); } catch (e) { /* ignore */ }
    }
  };

  function begin(st) {
    st0 = st.t0;
    rec = true;
    full = false;

    // recover events saved when the previous page unloaded
    try {
      var pend = localStorage.getItem(K_PEND + tabId);
      if (pend) {
        localStorage.removeItem(K_PEND + tabId);
        var evs = JSON.parse(pend);
        if (evs.length) {
          inflight.push(evs);
          queue = queue.then(function () { return storeChunk(evs); })
            .catch(onStoreError)
            .then(function () { var i = inflight.indexOf(evs); if (i >= 0) inflight.splice(i, 1); });
        }
      }
    } catch (e) { /* ignore */ }

    observer = new MutationObserver(onMutations);
    observer.observe(document.body, {
      subtree: true, childList: true, characterData: true,
      attributes: true, attributeOldValue: true, attributeFilter: ATTRS
    });
    document.addEventListener('click', onClick, { capture: true, passive: true });
    document.addEventListener('submit', onSubmit, true);
    document.addEventListener('change', onChange, true);
    window.addEventListener('pagehide', pagehideHandler);

    try {
      perfObs = new PerformanceObserver(function (list) {
        if (!rec) return;
        list.getEntries().forEach(function (en) {
          if (en.initiatorType !== 'xmlhttprequest' && en.initiatorType !== 'fetch') return;
          try {
            var u = new URL(en.name);
            if (u.host.indexOf('delugerpg.com') < 0) return;
            var p = u.pathname.split('/').slice(0, 4).join('/');
            push(['n', T(), en.initiatorType, p, Math.round(en.duration)]);
          } catch (e) { /* ignore */ }
        });
      });
      perfObs.observe({ type: 'resource', buffered: false });
    } catch (e) { perfObs = null; }

    push(['P', T(), redactUrl(location.href), mask(document.title), snapshotBody()]);
    checkMap();

    flushTimer = setInterval(flush, FLUSH_MS);
    updateUI();
    uiTimer = setInterval(function () {
      updateUI();
      checkMap();
    }, 1500);
  }

  function endCapture() {
    rec = false;
    if (observer) { observer.disconnect(); observer = null; }
    if (perfObs) { perfObs.disconnect(); perfObs = null; }
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('submit', onSubmit, true);
    document.removeEventListener('change', onChange, true);
    window.removeEventListener('pagehide', pagehideHandler);
    if (flushTimer) { clearInterval(flushTimer); flushTimer = null; }
    if (uiTimer) { clearInterval(uiTimer); uiTimer = null; }
  }

  // ---------- start / stop ----------
  function start() {
    var st = readState();
    if ((st.n || 0) > 0 && !st.downloaded) {
      if (!confirm('The previous recording was not downloaded. Discard it and start a new one?')) return;
    }
    clearData();
    var ns = { on: true, owner: tabId, t0: Date.now(), n: 0, chars: 0, ev: 0, downloaded: false };
    writeState(ns);
    begin(ns);
  }

  async function stop() {
    btn.disabled = true;
    btn.textContent = 'Packing...';
    var wasRec = rec;
    if (wasRec) { drainCoal(); }
    endCapture();
    flush();
    await queue;

    var st = readState();
    var keys = chunkKeys();
    var entries = [];
    keys.forEach(function (k) {
      try {
        var o = JSON.parse(localStorage.getItem(k));
        var data = fromB64(o.d);
        entries.push({
          name: 'chunks/' + k.slice(K_CHUNK.length) + '.json',
          data: data, method: o.m, crc: o.c >>> 0, usize: o.u
        });
      } catch (e) { /* skip unreadable chunk */ }
    });

    var meta = enc.encode(JSON.stringify({
      schema: 1, script: VERSION, site: location.host,
      started: new Date(st.t0 || Date.now()).toISOString(),
      stopped: new Date().toISOString(),
      chunks: keys.length, events: st.ev || 0, storage_chars: st.chars || 0,
      storage_full_stop: !!full
    }, null, 1));
    var readme = enc.encode([
      'DelugeRPG session recording (schema 1)',
      'Each chunks/NNNNNN.json is a JSON array of events, in order. t = whole seconds since start.',
      '',
      "['P', t, url, title, bodyHtml] = page baseline snapshot (sanitized).",
      "['+', t, parentPath, childIndex, html] = element added.",
      "['T', t, parentPath, text] = text node added.",
      "['-', t, parentPath, descriptor] = node removed.",
      "['a', t, path, attr, value] = attribute changed (last value within ~300 ms).",
      "['x', t, path, text] = text changed (last value within ~300 ms).",
      "['c', t, kind, path, label, value, ...] = click / submit / change on a control.",
      "['n', t, xhr|fetch, path, ms] = background request fired (path only, no query).",
      "['m', t, mapFile, mapNum, mapName] = map loaded or changed.",
      "['g', t, mapFile, base64] = walkgrid (33x33 tiles x 2 bytes) for that map.",
      '',
      'Not recorded: mouse movement, scrolling, key timing, sub-second timing, hidden inputs,',
      'typed text, tokens in URLs. Your username is masked; other players are masked where detected.',
      'Review the files before sharing.'
    ].join('\n'));
    entries.push({ name: 'meta.json', data: meta, method: 0, crc: crc32(meta), usize: meta.length });
    entries.push({ name: 'README.txt', data: readme, method: 0, crc: crc32(readme), usize: readme.length });

    var blob = makeZip(entries);
    var d = new Date();
    var pad = function (n) { return String(n).padStart(2, '0'); };
    var name = 'deluge_session_' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) +
      '-' + pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds()) + '.zip';
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 60000);

    st.on = false;
    st.downloaded = true;
    writeState(st);
    btn.disabled = false;
    updateUI();
  }

  // ---------- button UI ----------
  function updateUI() {
    var st = readState();
    var kb = Math.round(((st.chars || 0) / 1024) * 10) / 10;
    if (st.on && st.owner === tabId) {
      var pending = buf.length;
      inflight.forEach(function (a) { pending += a.length; });
      btn.style.background = full ? '#b7791f' : '#c53030';
      btn.textContent = full
        ? 'Full - click to download'
        : '\u25a0 Stop & download \u00b7 ' + kb + ' KB \u00b7 ' + ((st.ev || 0) + pending) + ' ev';
    } else if (st.on) {
      btn.style.background = '#718096';
      btn.textContent = 'Recording in another tab';
    } else {
      btn.style.background = '#2b6cb0';
      btn.textContent = '\u25cf Start recording';
    }
  }

  btn.addEventListener('click', function () {
    var st = readState();
    if (st.on && st.owner === tabId) { stop(); }
    else if (st.on) { updateUI(); }
    else { start(); }
  });

  var cur = readState();
  if (cur.on && cur.owner === tabId) begin(cur);
  else updateUI();
  }  // end main

  function boot() {
    try {
      if (!document.body) { setTimeout(boot, 300); return; }
      main();
    } catch (e) {
      try { console.error('[DelugeRecorder] failed to start:', e); } catch (x) { /* ignore */ }
      var b = document.createElement('div');
      b.textContent = 'Recorder error: ' + (e && e.message ? e.message : e);
      b.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;background:#c53030;' +
        'color:#fff;font:12px system-ui,sans-serif;padding:8px 12px;border-radius:6px;';
      (document.body || document.documentElement).appendChild(b);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
