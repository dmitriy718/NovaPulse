/**
 * AI Trading Bot - Dashboard Client v3
 *
 * Zero console spam: WS-first with graceful degradation.
 * No fetch() calls until server is confirmed reachable.
 */

// ---- State ----
let ws = null;
let wsAttempts = 0;
let isPaused = false;
let priceHistory = {};
let lastThoughtIds = [];
let userScrolledThoughts = false;
let scrollResetTimer = null;
let serverReachable = false;   // gate: no fetches until true
let reconnectTimer = null;
const strategyElements = new Map();
let algoTooltip = null;
let favorites = [];
const favoriteSet = new Set();
let chartResizeTimer = null;
let chartPollTimer = null;
let chartRequestInFlight = false;
const chartState = {
    open: false,
    pair: '',
    exchange: '',
    accountId: '',
    timeframe: '5m',
    candles: [],
    source: ''
};

// ---- WebSocket (sole data channel when healthy) ----

function connectWebSocket() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${window.location.host}/ws/live`;

    // Suppress the console error: only create WS if we believe server is up
    // On first load we try regardless; after that we gate on serverReachable
    if (wsAttempts > 0 && !serverReachable) {
        // Silently probe with a HEAD request first (no console error on fail)
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 3000);
        fetch('/api/v1/health', { signal: ctrl.signal, method: 'HEAD' })
            .then(r => { clearTimeout(t); if (r.ok) { serverReachable = true; doConnect(wsUrl); } else { scheduleReconnect(); } })
            .catch(() => { clearTimeout(t); scheduleReconnect(); });
        return;
    }

    doConnect(wsUrl);
}

function doConnect(wsUrl) {
    try { ws = new WebSocket(wsUrl); } catch { scheduleReconnect(); return; }

    ws.onopen = () => {
        wsAttempts = 0;
        serverReachable = true;
        updateStatus('ONLINE', false);
        loadSettings();
        refreshFavorites();
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'update') renderUpdate(msg.data);
        } catch {}
    };

    ws.onclose = (ev) => {
        ws = null;
        // Auth failures (1008) won't recover until the user logs in.
        if (ev && ev.code === 1008) {
            serverReachable = true;
            updateStatus('AUTH REQUIRED', true);
            try { window.location.href = '/login'; } catch {}
            if (!reconnectTimer) {
                reconnectTimer = setTimeout(() => { reconnectTimer = null; connectWebSocket(); }, 30000);
            }
            return;
        }
        serverReachable = false;
        updateStatus('RECONNECTING...', true);
        scheduleReconnect();
    };

    ws.onerror = () => { /* onclose will fire next */ };
}

function scheduleReconnect() {
    if (reconnectTimer) return; // already scheduled
    wsAttempts++;
    // Exponential backoff: 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(2000 * Math.pow(2, Math.min(wsAttempts - 1, 4)), 30000);
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connectWebSocket(); }, delay);
}

function updateStatus(text, isError) {
    const el = document.getElementById('statusIndicator');
    const st = document.getElementById('statusText');
    if (st) st.textContent = text;
    if (el) el.classList.toggle('error', isError);
}

// ---- Render Orchestrator ----

function renderUpdate(data) {
    if (!data) return;
    if (Array.isArray(data.favorites)) {
        applyFavorites(data.favorites);
    }
    renderStatus(data.status);
    renderPerformance(data.performance, data.risk);
    renderFavorites();
    renderPositions(data.positions);
    renderThoughts(data.thoughts);
    renderScanner(data.scanner);
    renderStockScanner(data.scanner);
    renderRisk(data.risk);
    if (data.strategies) renderStrategies(data.strategies);
    updateFavoriteButtonsState();
}

// ---- Status / HUD ----

function renderStatus(status) {
    if (!status) return;
    setText('tradingMode', (status.mode || '--').toUpperCase());
    setText('uptime', formatUptime(status.uptime || 0));
    if (status.scan_count !== undefined) setText('scanCount', status.scan_count.toLocaleString());

    const label = status.running ? (status.paused ? 'PAUSED' : 'ONLINE') : 'STOPPED';
    updateStatus(label, !status.running || status.paused);

    isPaused = status.paused || false;
    const btn = document.getElementById('pauseBtn');
    if (btn) btn.textContent = isPaused ? '▶ RESUME' : '⏸ PAUSE';
}

// ---- Portfolio / Performance ----

function renderPerformance(perf, risk) {
    if (!perf) return;
    const realized = perf.total_pnl || 0;
    const unrealized = perf.unrealized_pnl || 0;
    const totalPnl = realized + unrealized;
    const totalEquity = perf.total_equity || (risk ? (risk.bankroll || 0) + unrealized : 0);
    const el = document.getElementById('totalPnl');
    if (el) {
        el.textContent = formatMoney(totalPnl);
        el.className = 'pnl-value' + (totalPnl < 0 ? ' negative' : '');
    }
    // Shift ambient background hue: warm gold (42) when positive, red (0) when negative
    document.documentElement.style.setProperty('--ambient-hue', totalPnl >= 0 ? '42' : '0');
    const eqEl = document.getElementById('totalEquity');
    if (eqEl) {
        eqEl.textContent = formatMoneyPlain(totalEquity);
        eqEl.className = 'equity-value' + (totalEquity < 0 ? ' negative' : '');
    }

    const uEl = document.getElementById('unrealizedPnl');
    if (uEl) {
        uEl.textContent = formatMoney(unrealized);
        uEl.style.color = unrealized >= 0 ? 'var(--neon-green)' : 'var(--red)';
    }

    const todayEl = document.getElementById('todayPnl');
    if (todayEl) {
        todayEl.textContent = formatMoney(realized);
        todayEl.style.color = realized >= 0 ? 'var(--neon-green)' : 'var(--red)';
    }

    if (risk) setText('bankroll', formatMoney(risk.bankroll || 0));
    setText('winRate', ((perf.win_rate || 0) * 100).toFixed(1) + '%');
    setText('totalTrades', perf.total_trades || 0);
    setText('openPositions', perf.open_positions || 0);
    if (risk) setText('drawdown', (risk.current_drawdown || 0).toFixed(1) + '%');
}

// ---- Favorites ----

function normalizeSymbol(sym) {
    let s = String(sym || '').trim().toUpperCase();
    if (s.startsWith('O:')) s = s.slice(2);
    return s;
}

function applyFavorites(list) {
    const arr = Array.isArray(list) ? list : [];
    const next = [];
    const seen = new Set();
    for (const item of arr) {
        const sym = normalizeSymbol(item);
        if (!sym || seen.has(sym)) continue;
        seen.add(sym);
        next.push(sym);
    }
    favorites = next;
    favoriteSet.clear();
    for (const sym of next) favoriteSet.add(sym);
}

function isFavorite(sym) {
    return favoriteSet.has(normalizeSymbol(sym));
}

function favoriteButtonHtml(symbol) {
    const sym = normalizeSymbol(symbol);
    const active = isFavorite(sym);
    return `<button class="fav-btn${active ? ' active' : ''}" type="button" data-symbol="${escHtml(sym)}" title="${active ? 'Remove from favorites' : 'Add to favorites'}">${active ? '♥' : '♡'}</button>`;
}

function renderFavorites() {
    const list = document.getElementById('favoritesList');
    if (!list) return;
    if (!favorites.length) {
        list.innerHTML = '<div class="favorite-item empty">No favorites yet</div>';
        return;
    }
    list.innerHTML = favorites.map((sym) => (
        `<div class="favorite-item">
            <span class="favorite-symbol">${escHtml(sym)}</span>
            ${favoriteButtonHtml(sym)}
        </div>`
    )).join('');
}

function updateFavoriteButtonsState() {
    document.querySelectorAll('.fav-btn[data-symbol]').forEach((btn) => {
        const sym = normalizeSymbol(btn.dataset.symbol || '');
        const active = isFavorite(sym);
        btn.classList.toggle('active', active);
        btn.textContent = active ? '♥' : '♡';
        btn.title = active ? 'Remove from favorites' : 'Add to favorites';
    });
    syncChartFavoriteButton();
}

async function refreshFavorites() {
    if (!serverReachable) return;
    try {
        const r = await fetch('/api/v1/favorites');
        if (!r.ok) return;
        const data = await r.json();
        applyFavorites(data.favorites || []);
        renderFavorites();
        updateFavoriteButtonsState();
    } catch {}
}

async function toggleFavoriteSymbol(symbol) {
    if (!serverReachable) return;
    const sym = normalizeSymbol(symbol);
    if (!sym) return;
    const currentlyFav = isFavorite(sym);
    const method = currentlyFav ? 'DELETE' : 'POST';
    const url = currentlyFav
        ? `/api/v1/favorites/${encodeURIComponent(sym)}`
        : '/api/v1/favorites';
    const init = {
        method,
        headers: { ...csrfHeaders() },
    };
    if (method === 'POST') {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify({ symbol: sym });
    }
    try {
        const r = await fetch(url, init);
        if (!r.ok) return;
        const payload = await r.json();
        applyFavorites(payload.favorites || []);
        renderFavorites();
        updateFavoriteButtonsState();
    } catch {}
}

function setupFavorites() {
    document.addEventListener('click', async (ev) => {
        const btn = ev.target.closest('.fav-btn[data-symbol]');
        if (!btn) return;
        ev.preventDefault();
        ev.stopPropagation();
        await toggleFavoriteSymbol(btn.dataset.symbol || '');
    });
}

// ---- Positions Table ----

function renderPositions(positions) {
    const tbody = document.getElementById('positionsBody');
    if (!tbody) return;
    const cleaned = (positions || []).filter(p => Math.abs(Number(p?.quantity) || 0) > 0.00000001);
    if (cleaned.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="8">No open positions</td></tr>';
        return;
    }
    let html = '';
    for (const pos of cleaned) {
        const pairRaw = normalizeSymbol(String(pos?.pair || ''));
        const pair = escHtml(pairRaw);
        const sideRaw = String(pos?.side || '').trim().toLowerCase();
        const sideClass = sideRaw === 'buy' ? 'side-buy' : (sideRaw === 'sell' ? 'side-sell' : '');
        const sideLabel = sideRaw ? escHtml(sideRaw.toUpperCase()) : 'N/A';
        const qty = Number(pos.quantity) || 0;
        const entry = Number(pos.entry_price) || 0;
        const current = Number(pos.current_price) || 0;
        const pnl = Number(pos.unrealized_pnl) || 0;
        const pnlPct = getPnlPct(pos, entry, qty, pnl);
        const sizeUsd = Math.abs((current || entry) * qty);
        const conf = resolveConfidence(pos);
        html += `<tr>
            <td>
                <div class="symbol-with-fav">
                    <span class="symbol-label">${pair}</span>
                    ${favoriteButtonHtml(pairRaw)}
                </div>
            </td>
            <td class="${sideClass}">${sideLabel}</td>
            <td>
                <div class="cell-stack">
                    <span class="cell-main">${formatQty(qty)}</span>
                    <span class="cell-sub">${formatMoneyPlain(sizeUsd)}</span>
                </div>
            </td>
            <td>${formatPrice(entry)}</td>
            <td>${formatPrice(current || entry)}</td>
            <td class="${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">
                <div class="cell-stack">
                    <span class="cell-main">${formatMoney(pnl)}</span>
                    <span class="cell-sub">${(pnlPct * 100).toFixed(2)}%</span>
                </div>
            </td>
            <td>
                ${renderConfidence(conf)}
            </td>
            <td>${formatPrice(pos.stop_loss || 0)}</td>
        </tr>`;
    }
    tbody.innerHTML = html;
}

// ---- AI Thought Feed ----

function renderThoughts(thoughts) {
    const feed = document.getElementById('thoughtFeed');
    const countBadge = document.getElementById('thoughtCount');
    if (!feed || !thoughts) return;
    if (countBadge) countBadge.textContent = thoughts.length;

    const newKeys = thoughts.map(t => t.timestamp + '|' + t.message);
    if (newKeys.length === lastThoughtIds.length && newKeys.every((k, i) => k === lastThoughtIds[i])) return;
    lastThoughtIds = newKeys;

    const existingMap = new Map();
    feed.querySelectorAll('.thought-item[data-key]').forEach(n => existingMap.set(n.getAttribute('data-key'), n));

    const frag = document.createDocumentFragment();
    for (const thought of thoughts) {
        const key = thought.timestamp + '|' + thought.message;
        const existing = existingMap.get(key);
        if (existing) { frag.appendChild(existing); continue; }

        const div = document.createElement('div');
        div.className = 'thought-item thought-new';
        div.setAttribute('data-key', key);
        div.innerHTML =
            `<span class="thought-time">${formatTime(thought.timestamp)}</span>` +
            `<span class="thought-category ${thought.category || 'system'}">${escHtml((thought.category || 'system').toUpperCase())}</span>` +
            `<span class="thought-msg">${escHtml(thought.message || '')}</span>`;
        frag.appendChild(div);
    }

    feed.innerHTML = '';
    feed.appendChild(frag);
    if (!userScrolledThoughts) feed.scrollTop = 0;

    requestAnimationFrame(() => {
        feed.querySelectorAll('.thought-new').forEach(el => {
            el.addEventListener('animationend', () => el.classList.remove('thought-new'), { once: true });
        });
    });
}

function setupThoughtScroll() {
    const feed = document.getElementById('thoughtFeed');
    if (!feed) return;
    feed.addEventListener('scroll', () => {
        userScrolledThoughts = feed.scrollTop > 40;
        clearTimeout(scrollResetTimer);
        if (userScrolledThoughts) {
            scrollResetTimer = setTimeout(() => {
                userScrolledThoughts = false;
                feed.scrollTo({ top: 0, behavior: 'smooth' });
            }, 15000);
        }
    });
}

// ---- Ticker Scanner ----

function renderScanner(scanner) {
    const grid = document.getElementById('scannerGrid');
    if (!grid || !scanner) return;
    const entries = Object.entries(scanner);

    let html = '';
    for (const [pair, data] of entries) {
        const parsed = parseScannerLabel(pair);
        const symbol = normalizeSymbol(parsed.pair || pair);
        const exchange = String(data?.exchange || parsed.exchange || '').trim().toLowerCase();
        const accountId = String(data?.account_id || parsed.accountId || '').trim().toLowerCase();
        const price = Number(data?.price ?? data?.last_price ?? 0) || 0;
        if (!priceHistory[pair]) priceHistory[pair] = [];
        priceHistory[pair].push(price);
        if (priceHistory[pair].length > 20) priceHistory[pair].shift();
        html += `<div class="scanner-item${data.stale ? ' stale' : ''}">
            <div class="scanner-top">
                <span class="scanner-pair">
                    <span class="symbol-with-fav">
                        <span class="symbol-label">${escHtml(symbol)}</span>
                        ${favoriteButtonHtml(symbol)}
                    </span>
                </span>
                <span class="scanner-actions">
                    <button class="scanner-chart-btn" type="button"
                        data-pair="${escHtml(symbol)}"
                        data-exchange="${escHtml(exchange)}"
                        data-account-id="${escHtml(accountId)}"
                        title="Open chart">📈</button>
                </span>
            </div>
            <span class="scanner-price">${formatPrice(price)}</span>
            <div class="sparkline">${generateSparkline(priceHistory[pair])}</div>
            <span class="scanner-bars">${data.bars || 0} bars</span>
        </div>`;
    }
    grid.innerHTML = html || '<div class="scanner-item"><span class="scanner-pair">Waiting...</span></div>';
}

function parseScannerLabel(label) {
    const raw = String(label || '').trim();
    const m = raw.match(/^(.*)\s+\(([^)]+)\)$/);
    if (!m) return { pair: raw, exchange: '', accountId: '' };
    const token = String(m[2] || '').trim();
    let exchange = token;
    let accountId = '';
    const sep = token.indexOf(':');
    if (sep >= 0) {
        exchange = token.slice(0, sep).trim();
        accountId = token.slice(sep + 1).trim();
    }
    return {
        pair: String(m[1] || '').trim(),
        exchange: exchange.toLowerCase(),
        accountId: accountId.toLowerCase(),
    };
}

const nyseHolidayCache = {};

function nyDateParts(now) {
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).formatToParts(now);
    const map = {};
    for (const p of parts) map[p.type] = p.value;
    return {
        year: Number(map.year || 0),
        month: Number(map.month || 0),
        day: Number(map.day || 0),
        weekday: String(map.weekday || ''),
        hour: Number(map.hour || 0),
        minute: Number(map.minute || 0),
    };
}

function dateKey(year, month, day) {
    const m = String(month).padStart(2, '0');
    const d = String(day).padStart(2, '0');
    return `${year}-${m}-${d}`;
}

function observedDate(year, month, day) {
    const utc = new Date(Date.UTC(year, month - 1, day));
    const wd = utc.getUTCDay(); // 0=Sun..6=Sat
    if (wd === 6) utc.setUTCDate(utc.getUTCDate() - 1); // Saturday -> Friday
    if (wd === 0) utc.setUTCDate(utc.getUTCDate() + 1); // Sunday -> Monday
    return dateKey(utc.getUTCFullYear(), utc.getUTCMonth() + 1, utc.getUTCDate());
}

function nthWeekday(year, month, weekday, nth) {
    const first = new Date(Date.UTC(year, month - 1, 1));
    const firstWeekday = first.getUTCDay();
    const delta = (weekday - firstWeekday + 7) % 7;
    const day = 1 + delta + ((nth - 1) * 7);
    return dateKey(year, month, day);
}

function lastWeekday(year, month, weekday) {
    const last = new Date(Date.UTC(year, month, 0));
    const lastWeekdayValue = last.getUTCDay();
    const delta = (lastWeekdayValue - weekday + 7) % 7;
    const day = last.getUTCDate() - delta;
    return dateKey(year, month, day);
}

function easterSunday(year) {
    const a = year % 19;
    const b = Math.floor(year / 100);
    const c = year % 100;
    const d = Math.floor(b / 4);
    const e = b % 4;
    const f = Math.floor((b + 8) / 25);
    const g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4);
    const k = c % 4;
    const l = (32 + (2 * e) + (2 * i) - h - k) % 7;
    const m = Math.floor((a + (11 * h) + (22 * l)) / 451);
    const month = Math.floor((h + l - (7 * m) + 114) / 31);
    const day = ((h + l - (7 * m) + 114) % 31) + 1;
    return { month, day };
}

function nyseHolidays(year) {
    const key = String(year);
    if (nyseHolidayCache[key]) return nyseHolidayCache[key];

    const out = new Set();
    out.add(observedDate(year, 1, 1));   // New Year's Day
    out.add(nthWeekday(year, 1, 1, 3));  // Martin Luther King Jr. Day
    out.add(nthWeekday(year, 2, 1, 3));  // Presidents Day
    out.add(lastWeekday(year, 5, 1));    // Memorial Day
    out.add(observedDate(year, 6, 19));  // Juneteenth
    out.add(observedDate(year, 7, 4));   // Independence Day
    out.add(nthWeekday(year, 9, 1, 1));  // Labor Day
    out.add(nthWeekday(year, 11, 4, 4)); // Thanksgiving
    out.add(observedDate(year, 12, 25)); // Christmas

    const easter = easterSunday(year);
    const gf = new Date(Date.UTC(year, easter.month - 1, easter.day));
    gf.setUTCDate(gf.getUTCDate() - 2);  // Good Friday
    out.add(dateKey(gf.getUTCFullYear(), gf.getUTCMonth() + 1, gf.getUTCDate()));

    nyseHolidayCache[key] = out;
    return out;
}

function marketStateNow() {
    const now = new Date();
    const parts = nyDateParts(now);
    const wd = parts.weekday;
    const hour = parts.hour;
    const minute = parts.minute;
    const mins = hour * 60 + minute;
    const dayKey = dateKey(parts.year, parts.month, parts.day);
    const holiday = nyseHolidays(parts.year).has(dayKey);
    const weekend = wd === 'Sat' || wd === 'Sun';
    if (weekend || holiday) return { state: 'closed', label: 'MARKET CLOSED' };

    const openStart = 9 * 60 + 30;
    const openEnd = 16 * 60;
    const extStart = 4 * 60;
    const extEnd = 20 * 60;

    if (mins >= openStart && mins < openEnd) return { state: 'open', label: 'MARKET OPEN' };
    if (mins >= extStart && mins < openStart) return { state: 'after-hours', label: 'AFTER HOURS' };
    if (mins >= openEnd && mins < extEnd) return { state: 'after-hours', label: 'AFTER HOURS' };
    return { state: 'closed', label: 'MARKET CLOSED' };
}

function renderStockScanner(scanner) {
    const card = document.getElementById('stockScannerCard');
    const title = document.getElementById('stockScannerTitle');
    const grid = document.getElementById('stockScannerGrid');
    const overlay = document.getElementById('stockScannerOverlay');
    if (!card || !title || !grid || !overlay) return;

    card.classList.remove('market-open', 'after-hours', 'market-closed');
    const m = marketStateNow();
    card.classList.add(m.state);
    title.textContent = `STOCK SCANNER | ${m.label}`;
    overlay.textContent = 'MARKET CLOSED';

    const entries = Object.entries(scanner || {});
    const stocks = [];
    for (const [label, raw] of entries) {
        const parsed = parseScannerLabel(label);
        const pair = normalizeSymbol(parsed.pair.toUpperCase());
        const assetClass = String(raw?.asset_class || '').trim().toLowerCase();
        const isEquityFamily = assetClass === 'stock' || assetClass === 'option' || parsed.exchange === 'stocks';
        if (!isEquityFamily) continue;
        stocks.push({
            symbol: pair,
            exchange: parsed.exchange,
            assetClass,
            price: Number(raw?.price ?? raw?.last_price ?? 0) || 0,
            stale: !!raw?.stale,
        });
    }

    stocks.sort((a, b) => a.symbol.localeCompare(b.symbol));
    if (!stocks.length) {
        grid.innerHTML = '<div class="stock-item empty">No stock symbols scanned yet</div>';
        return;
    }

    let html = '';
    for (const s of stocks) {
        html += `<div class="stock-item${s.stale ? ' stale' : ''}">
            <span class="stock-main">
                <span class="stock-symbol">${escHtml(s.symbol)}</span>
                ${favoriteButtonHtml(s.symbol)}
            </span>
            <span class="stock-price">${formatPrice(s.price)}</span>
        </div>`;
    }
    grid.innerHTML = html;
}

// ---- Scanner Chart Modal ----

function setupChartModal() {
    const grid = document.getElementById('scannerGrid');
    const tfRow = document.getElementById('chartTfRow');
    const shareRow = document.getElementById('chartShareRow');
    const chartFavoriteBtn = document.getElementById('chartFavoriteBtn');
    if (grid) {
        grid.addEventListener('click', (ev) => {
            const btn = ev.target.closest('.scanner-chart-btn');
            if (!btn) return;
            ev.preventDefault();
            ev.stopPropagation();
            openChartModal(
                btn.dataset.pair || '',
                btn.dataset.exchange || '',
                btn.dataset.accountId || '',
            );
        });
    }

    if (tfRow) {
        tfRow.addEventListener('click', (ev) => {
            const btn = ev.target.closest('.chart-tf-btn');
            if (!btn || !chartState.open) return;
            const tf = String(btn.dataset.tf || '').toLowerCase();
            if (!tf || tf === chartState.timeframe) return;
            chartState.timeframe = tf;
            activateChartTimeframe(tf);
            loadChartData();
        });
    }

    if (shareRow) {
        shareRow.addEventListener('click', async (ev) => {
            const btn = ev.target.closest('.chart-share-btn');
            if (!btn || !chartState.open) return;
            ev.preventDefault();
            ev.stopPropagation();
            await shareChart(btn.dataset.share || '');
        });
    }

    if (chartFavoriteBtn) {
        chartFavoriteBtn.addEventListener('click', async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            if (!chartState.open || !chartState.pair) return;
            await toggleFavoriteSymbol(chartState.pair);
            syncChartFavoriteButton();
        });
    }

    window.addEventListener('resize', () => {
        if (!chartState.open) return;
        clearTimeout(chartResizeTimer);
        chartResizeTimer = setTimeout(() => renderChartPanels(), 120);
    });
}

function activateChartTimeframe(tf) {
    const row = document.getElementById('chartTfRow');
    if (!row) return;
    row.querySelectorAll('.chart-tf-btn').forEach((btn) => {
        btn.classList.toggle('active', String(btn.dataset.tf || '').toLowerCase() === tf);
    });
}

function openChartModal(pair, exchange = '', accountId = '') {
    const p = String(pair || '').trim().toUpperCase();
    if (!p) return;
    chartState.open = true;
    chartState.pair = p;
    chartState.exchange = String(exchange || '').trim().toLowerCase();
    chartState.accountId = String(accountId || '').trim().toLowerCase();
    chartState.timeframe = '5m';
    chartState.candles = [];
    chartState.source = '';

    const overlay = document.getElementById('chartOverlay');
    const title = document.getElementById('chartTitle');
    const meta = document.getElementById('chartMeta');
    if (title) {
        const scope = chartState.exchange
            ? `${chartState.exchange.toUpperCase()}${chartState.accountId ? `:${chartState.accountId}` : ''}`
            : '';
        title.textContent = `HEIKIN ASHI · ${p}${scope ? ` (${scope})` : ''}`;
    }
    if (meta) meta.textContent = 'Loading...';
    syncChartFavoriteButton();
    activateChartTimeframe(chartState.timeframe);
    setChartStatus('Loading chart...');
    if (overlay) overlay.classList.remove('hidden');
    loadChartData();
    startChartLivePolling();
}

function closeChartModal() {
    chartState.open = false;
    stopChartLivePolling();
    const overlay = document.getElementById('chartOverlay');
    if (overlay) overlay.classList.add('hidden');
    syncChartFavoriteButton();
}

function syncChartFavoriteButton() {
    const btn = document.getElementById('chartFavoriteBtn');
    if (!btn) return;
    const sym = normalizeSymbol(chartState.pair || '');
    const active = !!sym && isFavorite(sym);
    btn.classList.toggle('active', active);
    btn.textContent = active ? '♥' : '♡';
    btn.title = active ? 'Remove from favorites' : 'Add to favorites';
}

function startChartLivePolling() {
    stopChartLivePolling();
    // Light polling keeps candles current between websocket scanner updates.
    chartPollTimer = setInterval(() => {
        if (!chartState.open) return;
        loadChartData({ showLoading: false });
    }, 8000);
}

function stopChartLivePolling() {
    if (chartPollTimer) {
        clearInterval(chartPollTimer);
        chartPollTimer = null;
    }
}

function setChartStatus(msg, isError = false) {
    const status = document.getElementById('chartStatus');
    if (!status) return;
    status.textContent = msg || '';
    status.style.color = isError ? 'var(--red)' : 'var(--text-3)';
}

function getPublicDashboardUrl() {
    const explicit = String(window.NOVA_DASHBOARD_URL || '').trim().replace(/\/+$/, '');
    if (explicit) return explicit;
    const origin = String(window.location.origin || '').trim().replace(/\/+$/, '');
    if (origin && origin !== 'null') return origin;
    return 'https://nova.horizonsvc.com';
}

function chartShareContext() {
    const symbol = chartState.pair || 'UNKNOWN';
    const tf = (chartState.timeframe || '5m').toUpperCase();
    const ex = chartState.exchange
        ? ` (${chartState.exchange.toUpperCase()}${chartState.accountId ? `:${chartState.accountId}` : ''})`
        : '';
    const summary = `${symbol}${ex} · Heikin Ashi ${tf} · RSI + MACD`;
    const url = `${getPublicDashboardUrl()}/`;
    const subject = `NovaPulse Chart Snapshot · ${symbol} ${tf}`;
    return {
        summary,
        url,
        text: `NovaPulse chart: ${summary}`,
        subject,
    };
}

async function copyTextSafe(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch {
        return false;
    }
}

async function buildChartSnapshotBlob() {
    const price = document.getElementById('priceChartCanvas');
    const rsi = document.getElementById('rsiChartCanvas');
    const macd = document.getElementById('macdChartCanvas');
    if (!price || !rsi || !macd) return null;

    const rectPrice = price.getBoundingClientRect();
    const rectRsi = rsi.getBoundingClientRect();
    const rectMacd = macd.getBoundingClientRect();
    const panelW = Math.max(1, Math.round(rectPrice.width || 0));
    const panelH1 = Math.max(1, Math.round(rectPrice.height || 0));
    const panelH2 = Math.max(1, Math.round(rectRsi.height || 0));
    const panelH3 = Math.max(1, Math.round(rectMacd.height || 0));
    if (panelW <= 1) return null;

    const scale = 2;
    const margin = 24;
    const gap = 10;
    const headerH = 58;
    const footerH = 42;
    const outW = panelW + (margin * 2);
    const outH = headerH + panelH1 + gap + panelH2 + gap + panelH3 + footerH + margin;

    const canvas = document.createElement('canvas');
    canvas.width = outW * scale;
    canvas.height = outH * scale;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.setTransform(scale, 0, 0, scale, 0, 0);

    const grad = ctx.createLinearGradient(0, 0, 0, outH);
    grad.addColorStop(0, '#1A2236');
    grad.addColorStop(1, '#101625');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, outW, outH);

    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fillRect(margin, margin, panelW, outH - (margin * 2));

    const titleEl = document.getElementById('chartTitle');
    const metaEl = document.getElementById('chartMeta');
    ctx.fillStyle = '#F0C942';
    ctx.font = "700 18px 'Chakra Petch', sans-serif";
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText((titleEl && titleEl.textContent) ? titleEl.textContent : 'HEIKIN ASHI', margin + 8, margin + 6);
    ctx.fillStyle = '#A3AEC6';
    ctx.font = "12px 'JetBrains Mono', monospace";
    ctx.fillText((metaEl && metaEl.textContent) ? metaEl.textContent : '', margin + 8, margin + 30);

    let y = margin + headerH;
    ctx.drawImage(price, 0, 0, price.width, price.height, margin, y, panelW, panelH1);
    y += panelH1 + gap;
    ctx.drawImage(rsi, 0, 0, rsi.width, rsi.height, margin, y, panelW, panelH2);
    y += panelH2 + gap;
    ctx.drawImage(macd, 0, 0, macd.width, macd.height, margin, y, panelW, panelH3);

    const markY = outH - 18;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = 'rgba(226, 232, 240, 0.82)';
    ctx.font = "600 12px 'Chakra Petch', sans-serif";
    ctx.fillText('Nova by Horizon', outW - margin, markY - 14);
    ctx.fillStyle = 'rgba(212, 160, 18, 0.92)';
    ctx.font = "11px 'JetBrains Mono', monospace";
    ctx.fillText(getPublicDashboardUrl(), outW - margin, markY);

    return await new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), 'image/png', 0.95));
}

function downloadBlob(blob, filename) {
    const link = document.createElement('a');
    const href = URL.createObjectURL(blob);
    link.href = href;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1200);
}

async function shareChart(platform) {
    const ctx = chartShareContext();
    const p = String(platform || '').toLowerCase();

    const payload = `${ctx.text}\n${ctx.url}`;
    let shareUrl = '';
    if (p === 'facebook') {
        const url = encodeURIComponent(ctx.url);
        const quote = encodeURIComponent(ctx.text);
        shareUrl = `https://www.facebook.com/sharer/sharer.php?u=${url}&quote=${quote}`;
    } else if (p === 'x') {
        const msg = encodeURIComponent(`${ctx.text} ${ctx.url}`);
        shareUrl = `https://twitter.com/intent/tweet?text=${msg}`;
    } else if (p === 'instagram') {
        const blob = await buildChartSnapshotBlob();
        if (!blob) {
            setChartStatus('Snapshot unavailable', true);
            return;
        }
        const filename = `novapulse-${(chartState.pair || 'chart').replace(/[^A-Z0-9]+/gi, '_')}-${Date.now()}.png`;
        downloadBlob(blob, filename);
        setChartStatus('Instagram snapshot downloaded (watermark included)');
        try {
            window.open('https://www.instagram.com/', '_blank', 'noopener,noreferrer');
        } catch {}
        return;
    } else if (p === 'reddit') {
        const url = encodeURIComponent(ctx.url);
        const title = encodeURIComponent(ctx.text);
        shareUrl = `https://www.reddit.com/submit?url=${url}&title=${title}`;
    } else if (p === 'discord') {
        const copied = await copyTextSafe(payload);
        if (copied) setChartStatus('Copied message for Discord');
        else setChartStatus('Open Discord and share manually');
        window.open('https://discord.com/channels/@me', '_blank', 'noopener,noreferrer,width=960,height=760');
        return;
    } else if (p === 'telegram') {
        const msg = encodeURIComponent(ctx.text);
        const url = encodeURIComponent(ctx.url);
        shareUrl = `https://t.me/share/url?url=${url}&text=${msg}`;
    } else if (p === 'stocktwits') {
        const copied = await copyTextSafe(payload);
        if (copied) setChartStatus('Copied message for Stocktwits');
        else setChartStatus('Open Stocktwits and share manually');
        window.open('https://stocktwits.com/', '_blank', 'noopener,noreferrer,width=960,height=760');
        return;
    } else if (p === 'gmail') {
        const su = encodeURIComponent(ctx.subject);
        const body = encodeURIComponent(`${ctx.text}\n\n${ctx.url}`);
        shareUrl = `https://mail.google.com/mail/?view=cm&fs=1&su=${su}&body=${body}`;
    }

    if (!shareUrl) return;
    window.open(shareUrl, '_blank', 'noopener,noreferrer,width=760,height=640');
}

async function loadChartData(options = {}) {
    if (!chartState.open || !serverReachable) return;
    if (chartRequestInFlight) return;
    const showLoading = options.showLoading !== false;
    const params = new URLSearchParams({
        pair: chartState.pair,
        timeframe: chartState.timeframe,
        limit: '320',
    });
    if (chartState.exchange) params.set('exchange', chartState.exchange);
    if (chartState.accountId) params.set('account_id', chartState.accountId);

    chartRequestInFlight = true;
    try {
        if (showLoading) setChartStatus('Loading chart...');
        const resp = await fetch(`/api/v1/chart?${params.toString()}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const payload = await resp.json();
        const candles = Array.isArray(payload.candles) ? payload.candles : [];
        chartState.candles = candles
            .map((c) => ({
                time: Number(c.time) || 0,
                open: Number(c.open) || 0,
                high: Number(c.high) || 0,
                low: Number(c.low) || 0,
                close: Number(c.close) || 0,
                volume: Number(c.volume) || 0,
            }))
            .filter((c) => c.time > 0 && c.open > 0 && c.high > 0 && c.low > 0 && c.close > 0);
        chartState.source = String(payload.source || '').trim();
        renderChartPanels();
        if (chartState.candles.length === 0) {
            setChartStatus('No candles available', true);
        } else {
            setChartStatus(`${chartState.candles.length} bars · ${chartState.timeframe.toUpperCase()} · ${chartState.source || 'data'}`);
        }
    } catch (e) {
        chartState.candles = [];
        renderChartPanels();
        setChartStatus(`Chart load failed (${e.message || 'error'})`, true);
    } finally {
        chartRequestInFlight = false;
    }
}

function setupCanvas(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const dpr = window.devicePixelRatio || 1;
    const pxW = Math.max(1, Math.floor(rect.width * dpr));
    const pxH = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== pxW || canvas.height !== pxH) {
        canvas.width = pxW;
        canvas.height = pxH;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    return { ctx, w: rect.width, h: rect.height };
}

function renderChartPanels() {
    const meta = document.getElementById('chartMeta');
    const candles = chartState.candles || [];
    if (meta) {
        const latest = candles.length ? candles[candles.length - 1] : null;
        const latestTs = latest ? new Date(latest.time * 1000).toLocaleString() : '--';
        const scope = chartState.exchange
            ? `${chartState.exchange.toUpperCase()}${chartState.accountId ? `:${chartState.accountId}` : ''}`
            : '';
        meta.textContent = `${chartState.pair}${scope ? ` (${scope})` : ''} · ${latestTs}`;
    }

    const priceCanvas = setupCanvas('priceChartCanvas');
    const rsiCanvas = setupCanvas('rsiChartCanvas');
    const macdCanvas = setupCanvas('macdChartCanvas');
    if (!priceCanvas || !rsiCanvas || !macdCanvas) return;

    if (!candles.length) {
        drawEmptyPanel(priceCanvas.ctx, priceCanvas.w, priceCanvas.h, 'No candle data');
        drawEmptyPanel(rsiCanvas.ctx, rsiCanvas.w, rsiCanvas.h, 'RSI');
        drawEmptyPanel(macdCanvas.ctx, macdCanvas.w, macdCanvas.h, 'MACD');
        return;
    }

    const clipped = candles.slice(-260);
    const heikin = toHeikinAshi(clipped);
    const closes = clipped.map((c) => c.close);
    const rsiVals = calcRsi(closes, 14);
    const { macd, signal, hist } = calcMacd(closes);

    drawPricePanel(priceCanvas.ctx, priceCanvas.w, priceCanvas.h, heikin, chartState.timeframe);
    drawRsiPanel(rsiCanvas.ctx, rsiCanvas.w, rsiCanvas.h, rsiVals);
    drawMacdPanel(macdCanvas.ctx, macdCanvas.w, macdCanvas.h, macd, signal, hist);
}

function drawEmptyPanel(ctx, w, h, label) {
    ctx.fillStyle = 'rgba(10, 12, 18, 0.95)';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
    ctx.fillStyle = 'rgba(136, 146, 168, 0.8)';
    ctx.font = "12px 'JetBrains Mono', monospace";
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, w / 2, h / 2);
}

function drawPricePanel(ctx, w, h, candles, tf) {
    ctx.fillStyle = 'rgba(10, 12, 18, 0.95)';
    ctx.fillRect(0, 0, w, h);
    const m = { top: 10, right: 60, bottom: 22, left: 8 };
    const pw = Math.max(10, w - m.left - m.right);
    const ph = Math.max(10, h - m.top - m.bottom);

    const highs = candles.map((c) => c.high);
    const lows = candles.map((c) => c.low);
    let maxP = Math.max(...highs);
    let minP = Math.min(...lows);
    if (!Number.isFinite(maxP) || !Number.isFinite(minP) || maxP <= minP) {
        maxP = candles[candles.length - 1].close * 1.01;
        minP = candles[candles.length - 1].close * 0.99;
    }
    const pad = (maxP - minP) * 0.08;
    maxP += pad;
    minP -= pad;
    const yr = maxP - minP || 1;
    const y = (p) => m.top + ((maxP - p) / yr) * ph;

    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const gy = m.top + (ph / 4) * i;
        ctx.beginPath();
        ctx.moveTo(m.left, gy);
        ctx.lineTo(m.left + pw, gy);
        ctx.stroke();
    }

    const n = candles.length;
    const step = pw / Math.max(n, 1);
    const bodyW = Math.max(2, Math.min(10, step * 0.65));
    for (let i = 0; i < n; i++) {
        const c = candles[i];
        const cx = m.left + (i + 0.5) * step;
        const yo = y(c.open);
        const yc = y(c.close);
        const yh = y(c.high);
        const yl = y(c.low);
        const up = c.close >= c.open;
        ctx.strokeStyle = up ? '#22C55E' : '#EF4444';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(cx, yh);
        ctx.lineTo(cx, yl);
        ctx.stroke();

        const top = Math.min(yo, yc);
        const bh = Math.max(1, Math.abs(yc - yo));
        ctx.fillStyle = up ? 'rgba(34,197,94,0.92)' : 'rgba(239,68,68,0.92)';
        ctx.fillRect(cx - bodyW / 2, top, bodyW, bh);
    }

    ctx.fillStyle = 'rgba(136,146,168,0.9)';
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
        const val = maxP - (yr / 4) * i;
        const gy = m.top + (ph / 4) * i;
        ctx.fillText(formatPrice(val), w - 6, gy);
    }

    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = 'rgba(212,160,18,0.9)';
    ctx.font = "11px 'JetBrains Mono', monospace";
    ctx.fillText(`Heikin Ashi · ${tf.toUpperCase()}`, m.left, h - 4);
}

function drawRsiPanel(ctx, w, h, rsiVals) {
    ctx.fillStyle = 'rgba(10, 12, 18, 0.95)';
    ctx.fillRect(0, 0, w, h);
    const m = { top: 8, right: 50, bottom: 18, left: 8 };
    const pw = Math.max(10, w - m.left - m.right);
    const ph = Math.max(10, h - m.top - m.bottom);
    const y = (v) => m.top + ((100 - v) / 100) * ph;

    const y30 = y(30);
    const y70 = y(70);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.beginPath(); ctx.moveTo(m.left, y30); ctx.lineTo(m.left + pw, y30); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(m.left, y70); ctx.lineTo(m.left + pw, y70); ctx.stroke();

    const n = rsiVals.length;
    const step = pw / Math.max(n - 1, 1);
    ctx.strokeStyle = '#3B82F6';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < n; i++) {
        const v = rsiVals[i];
        if (!Number.isFinite(v)) continue;
        const x = m.left + i * step;
        const yy = y(v);
        if (!started) {
            ctx.moveTo(x, yy);
            started = true;
        } else {
            ctx.lineTo(x, yy);
        }
    }
    ctx.stroke();

    const latest = [...rsiVals].reverse().find((v) => Number.isFinite(v));
    ctx.fillStyle = 'rgba(136,146,168,0.9)';
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText('70', w - 6, y70);
    ctx.fillText('30', w - 6, y30);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = '#3B82F6';
    ctx.fillText(`RSI 14${Number.isFinite(latest) ? `: ${latest.toFixed(1)}` : ''}`, m.left, h - 3);
}

function drawMacdPanel(ctx, w, h, macdVals, signalVals, histVals) {
    ctx.fillStyle = 'rgba(10, 12, 18, 0.95)';
    ctx.fillRect(0, 0, w, h);
    const m = { top: 8, right: 50, bottom: 18, left: 8 };
    const pw = Math.max(10, w - m.left - m.right);
    const ph = Math.max(10, h - m.top - m.bottom);
    const all = [...macdVals, ...signalVals, ...histVals].filter((v) => Number.isFinite(v));
    const absMax = all.length ? Math.max(...all.map((v) => Math.abs(v))) : 1;
    const rng = absMax * 2 || 1;
    const y = (v) => m.top + ((absMax - v) / rng) * ph;
    const zeroY = y(0);

    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath(); ctx.moveTo(m.left, zeroY); ctx.lineTo(m.left + pw, zeroY); ctx.stroke();

    const n = histVals.length;
    const step = pw / Math.max(n, 1);
    for (let i = 0; i < n; i++) {
        const v = histVals[i];
        if (!Number.isFinite(v)) continue;
        const x = m.left + i * step;
        const yy = y(v);
        ctx.fillStyle = v >= 0 ? 'rgba(34,197,94,0.55)' : 'rgba(239,68,68,0.55)';
        ctx.fillRect(x, Math.min(yy, zeroY), Math.max(1, step - 1), Math.max(1, Math.abs(yy - zeroY)));
    }

    drawLineSeries(ctx, macdVals, m.left, m.top, pw, ph, absMax, '#F0C942');
    drawLineSeries(ctx, signalVals, m.left, m.top, pw, ph, absMax, '#3B82F6');

    ctx.fillStyle = 'rgba(136,146,168,0.9)';
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText('0', w - 6, zeroY);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = '#F0C942';
    ctx.fillText('MACD 12/26/9', m.left, h - 3);
}

function drawLineSeries(ctx, vals, left, top, width, height, absMax, color) {
    const n = vals.length;
    if (!n) return;
    const step = width / Math.max(n - 1, 1);
    const rng = absMax * 2 || 1;
    const y = (v) => top + ((absMax - v) / rng) * height;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < n; i++) {
        const v = vals[i];
        if (!Number.isFinite(v)) continue;
        const x = left + i * step;
        const yy = y(v);
        if (!started) {
            ctx.moveTo(x, yy);
            started = true;
        } else {
            ctx.lineTo(x, yy);
        }
    }
    ctx.stroke();
}

function toHeikinAshi(candles) {
    const out = [];
    let prevOpen = 0;
    let prevClose = 0;
    for (let i = 0; i < candles.length; i++) {
        const c = candles[i];
        const haClose = (c.open + c.high + c.low + c.close) / 4;
        const haOpen = i === 0 ? (c.open + c.close) / 2 : (prevOpen + prevClose) / 2;
        const haHigh = Math.max(c.high, haOpen, haClose);
        const haLow = Math.min(c.low, haOpen, haClose);
        out.push({
            time: c.time,
            open: haOpen,
            high: haHigh,
            low: haLow,
            close: haClose,
            volume: c.volume,
        });
        prevOpen = haOpen;
        prevClose = haClose;
    }
    return out;
}

function calcEma(values, period) {
    const out = new Array(values.length).fill(null);
    if (!Array.isArray(values) || values.length < period || period < 1) return out;
    let sum = 0;
    for (let i = 0; i < period; i++) sum += Number(values[i]) || 0;
    let ema = sum / period;
    out[period - 1] = ema;
    const k = 2 / (period + 1);
    for (let i = period; i < values.length; i++) {
        const v = Number(values[i]) || 0;
        ema = (v - ema) * k + ema;
        out[i] = ema;
    }
    return out;
}

function calcRsi(values, period = 14) {
    const out = new Array(values.length).fill(null);
    if (!Array.isArray(values) || values.length <= period) return out;
    let gain = 0;
    let loss = 0;
    for (let i = 1; i <= period; i++) {
        const d = (Number(values[i]) || 0) - (Number(values[i - 1]) || 0);
        if (d >= 0) gain += d;
        else loss -= d;
    }
    let avgGain = gain / period;
    let avgLoss = loss / period;
    out[period] = avgLoss === 0 ? 100 : 100 - (100 / (1 + (avgGain / avgLoss)));
    for (let i = period + 1; i < values.length; i++) {
        const d = (Number(values[i]) || 0) - (Number(values[i - 1]) || 0);
        const up = d > 0 ? d : 0;
        const down = d < 0 ? -d : 0;
        avgGain = ((avgGain * (period - 1)) + up) / period;
        avgLoss = ((avgLoss * (period - 1)) + down) / period;
        if (avgLoss === 0 && avgGain === 0) out[i] = 50;
        else if (avgLoss === 0) out[i] = 100;
        else {
            const rs = avgGain / avgLoss;
            out[i] = 100 - (100 / (1 + rs));
        }
    }
    return out;
}

function calcEmaNullable(values, period) {
    const out = new Array(values.length).fill(null);
    const seed = [];
    let ema = null;
    const k = 2 / (period + 1);
    for (let i = 0; i < values.length; i++) {
        const v = values[i];
        if (!Number.isFinite(v)) continue;
        if (!Number.isFinite(ema)) {
            seed.push(v);
            if (seed.length === period) {
                ema = seed.reduce((a, b) => a + b, 0) / period;
                out[i] = ema;
            }
            continue;
        }
        ema = (v - ema) * k + ema;
        out[i] = ema;
    }
    return out;
}

function calcMacd(values) {
    const ema12 = calcEma(values, 12);
    const ema26 = calcEma(values, 26);
    const macd = values.map((_, i) => (
        Number.isFinite(ema12[i]) && Number.isFinite(ema26[i]) ? (ema12[i] - ema26[i]) : null
    ));
    const signal = calcEmaNullable(macd, 9);
    const hist = macd.map((v, i) => (
        Number.isFinite(v) && Number.isFinite(signal[i]) ? (v - signal[i]) : null
    ));
    return { macd, signal, hist };
}

// ---- Risk Monitor ----

function renderRisk(risk) {
    if (!risk) return;
    setGauge('rorGauge', 'rorValue', (risk.risk_of_ruin || 0) * 100, v => v.toFixed(2) + '%');
    const dl = Math.abs(risk.daily_pnl || 0);
    const maxDl = (risk.bankroll || 10000) * 0.05;
    setGauge('dailyLossGauge', 'dailyLossValue', (dl / maxDl) * 100, () => formatMoney(risk.daily_pnl || 0));
    const exp = risk.total_exposure_usd || 0;
    const maxExp = (risk.bankroll || 10000) * 0.5;
    setGauge('exposureGauge', 'exposureValue', (exp / maxExp) * 100, () => formatMoney(exp));
    setText('ddFactor', (risk.drawdown_factor || 1.0).toFixed(2) + 'x');
}

function setGauge(barId, valId, pct, fmt) {
    const bar = document.getElementById(barId);
    const val = document.getElementById(valId);
    if (bar) bar.style.width = Math.min(pct, 100) + '%';
    if (val) val.textContent = fmt(pct);
}

// ---- Sparkline ----

function generateSparkline(data) {
    if (!data || data.length < 2) return '';
    const min = Math.min(...data), max = Math.max(...data), range = max - min || 1;
    return data.map(v => `<div class="spark-bar" style="height:${Math.max(2, ((v - min) / range) * 18)}px"></div>`).join('');
}

// ---- Settings ----

function getCookie(name) {
    const n = String(name || '').trim();
    if (!n) return '';
    const parts = document.cookie.split(';');
    for (const p of parts) {
        const s = p.trim();
        if (s.startsWith(n + '=')) return decodeURIComponent(s.slice(n.length + 1));
    }
    return '';
}

function csrfToken() {
    return getCookie('np_csrf') || '';
}

function csrfHeaders() {
    const t = csrfToken();
    return t ? { 'X-CSRF-Token': t } : {};
}

// ================================================================
//  Settings Modal — Schema, Load, Render, Save
// ================================================================

const SETTINGS_SCHEMA = {
    ai: {
        label: 'AI & CONFLUENCE',
        fields: [
            { key: 'confluence_threshold', label: 'Confluence Threshold', type: 'int', min: 2, max: 8,
              desc: 'Minimum number of strategies that must agree on a direction before the bot enters a trade.',
              example: '3 = at least 3 of 8 strategies must signal the same direction' },
            { key: 'min_confidence', label: 'Min Confidence', type: 'float', min: 0.45, max: 0.75, step: 0.01,
              desc: 'Minimum blended confidence score (strategy + AI) required to execute a trade.',
              example: '0.68 = 68% confidence threshold. Lower = more trades but riskier' },
            { key: 'min_risk_reward_ratio', label: 'Min Risk/Reward Ratio', type: 'float', min: 0.5, max: 5.0, step: 0.1,
              desc: 'Minimum ratio of take-profit distance to stop-loss distance. Higher = only take trades with better upside.',
              example: '1.5 = TP must be at least 1.5x the SL distance' },
            { key: 'obi_counts_as_confluence', label: 'Weighted Order Book', type: 'bool',
              desc: 'When ON, order-book imbalance counts as a confluence vote (OBI + 1 strategy = tradable).',
              example: 'ON = more aggressive, uses microstructure data' },
            { key: 'obi_weight', label: 'OBI Weight', type: 'float', min: 0.0, max: 1.0, step: 0.05,
              desc: 'Weight of the Order Book Imbalance signal when weighted mode is enabled.',
              example: '0.4 = OBI contributes 40% of a full confluence vote' },
            { key: 'allow_keltner_solo', label: 'Allow Keltner Solo', type: 'bool',
              desc: 'Allow Keltner Channel strategy to open trades by itself, without needing other strategies to agree.',
              example: 'ON = Keltner can trade alone if confidence is high enough' },
            { key: 'allow_any_solo', label: 'Allow Any Solo', type: 'bool',
              desc: 'Allow any single strategy to trade alone without confluence. Use with caution.',
              example: 'ON = any strategy can trade solo. High risk of false signals' },
            { key: 'keltner_solo_min_confidence', label: 'Keltner Solo Min Confidence', type: 'float', min: 0.50, max: 0.90, step: 0.01,
              desc: 'Minimum confidence for Keltner to trade solo (only applies if Keltner solo is enabled).',
              example: '0.62 = Keltner needs 62%+ confidence to trade alone' },
            { key: 'solo_min_confidence', label: 'Any Solo Min Confidence', type: 'float', min: 0.50, max: 0.90, step: 0.01,
              desc: 'Minimum confidence for any strategy to trade solo (only applies if any solo is enabled).',
              example: '0.67 = single strategy needs 67%+ confidence to trade alone' },
        ]
    },
    risk: {
        label: 'RISK MANAGEMENT',
        fields: [
            { key: 'max_risk_per_trade', label: 'Max Risk Per Trade', type: 'float', min: 0.001, max: 0.10, step: 0.001,
              desc: 'Fraction of your bankroll risked on each trade. This is the most important risk setting.',
              example: '0.005 = 0.5% of bankroll. On $10,000, you risk $50 per trade' },
            { key: 'max_daily_loss', label: 'Max Daily Loss', type: 'float', min: 0.01, max: 0.20, step: 0.01,
              desc: 'Maximum daily drawdown as a fraction of bankroll. Trading pauses if this limit is hit.',
              example: '0.05 = 5%. On $10,000, trading stops after $500 daily loss' },
            { key: 'max_position_usd', label: 'Max Position Size ($)', type: 'float', min: 10, max: 50000, step: 10,
              desc: 'Maximum USD value of a single position, regardless of other sizing calculations.',
              example: '$200 = no single position will exceed $200' },
            { key: 'atr_multiplier_sl', label: 'ATR Multiplier (Stop Loss)', type: 'float', min: 0.5, max: 5.0, step: 0.1,
              desc: 'How many ATRs (Average True Range) away to place the initial stop-loss.',
              example: '2.0 = stop-loss is 2x the ATR distance from entry' },
            { key: 'atr_multiplier_tp', label: 'ATR Multiplier (Take Profit)', type: 'float', min: 0.5, max: 10.0, step: 0.1,
              desc: 'How many ATRs away to place the take-profit target.',
              example: '3.0 = take-profit is 3x the ATR distance from entry' },
            { key: 'trailing_activation_pct', label: 'Trailing Stop Activation', type: 'float', min: 0.005, max: 0.10, step: 0.001,
              desc: 'Profit percentage needed before the trailing stop activates to lock in gains.',
              example: '0.018 = trailing stop kicks in after 1.8% profit' },
            { key: 'trailing_step_pct', label: 'Trailing Step Size', type: 'float', min: 0.001, max: 0.05, step: 0.001,
              desc: 'How tightly the trailing stop follows price. Smaller = tighter trailing.',
              example: '0.005 = stop trails 0.5% behind the high-water mark' },
            { key: 'breakeven_activation_pct', label: 'Breakeven Activation', type: 'float', min: 0.005, max: 0.10, step: 0.001,
              desc: 'Profit percentage to move stop-loss to breakeven (entry price), eliminating downside.',
              example: '0.012 = after 1.2% profit, SL moves to entry price' },
            { key: 'kelly_fraction', label: 'Kelly Fraction', type: 'float', min: 0.05, max: 0.50, step: 0.05,
              desc: 'Fraction of the Kelly criterion used for position sizing. Lower = more conservative.',
              example: '0.25 = quarter-Kelly. Full Kelly is too aggressive for most traders' },
            { key: 'global_cooldown_seconds_on_loss', label: 'Loss Cooldown (seconds)', type: 'int', min: 0, max: 3600,
              desc: 'Seconds to wait after a losing trade before allowing new entries. Prevents tilt trading.',
              example: '600 = 10 minute cooldown after each loss' },
        ]
    },
    trading: {
        label: 'TRADING',
        fields: [
            { key: 'scan_interval_seconds', label: 'Scan Interval (seconds)', type: 'int', min: 5, max: 300,
              desc: 'How often the bot scans all pairs for new trading opportunities.',
              example: '30 = scan every 30 seconds. Lower = more responsive but more CPU' },
            { key: 'max_concurrent_positions', label: 'Max Open Positions', type: 'int', min: 1, max: 20,
              desc: 'Maximum number of positions open at the same time.',
              example: '5 = never hold more than 5 trades simultaneously' },
            { key: 'cooldown_seconds', label: 'Strategy Cooldown (seconds)', type: 'int', min: 0, max: 3600,
              desc: 'Default cooldown per strategy per pair after a trade closes.',
              example: '600 = wait 10 min before the same strategy can trade the same pair' },
            { key: 'max_spread_pct', label: 'Max Spread %', type: 'float', min: 0, max: 0.01, step: 0.0001,
              desc: 'Maximum bid-ask spread allowed to enter a trade. Prevents entries in illiquid conditions.',
              example: '0.0015 = skip if spread > 0.15%' },
            { key: 'quiet_hours_utc', label: 'Quiet Hours (UTC)', type: 'text',
              desc: 'UTC hours when the bot will not open new positions. Comma-separated list.',
              example: '2,3,4,5 = no new trades between 2:00-5:59 UTC (low liquidity)' },
        ]
    },
    ml: {
        label: 'ML / LEARNING',
        fields: [
            { key: 'retrain_interval_hours', label: 'Retrain Interval (hours)', type: 'int', min: 1, max: 720,
              desc: 'Hours between full TFLite model retrain cycles. The model learns from all historical trade outcomes.',
              example: '168 = retrain weekly. Shorter = adapts faster but needs more data' },
            { key: 'min_samples', label: 'Min Training Samples', type: 'int', min: 100, max: 100000,
              desc: 'Minimum number of closed trades needed before the system will train/retrain the AI model.',
              example: '10000 = need 10k labeled trades before first retrain. Lower for faster cold start' },
        ]
    }
};

let currentSettingsData = {};
let activeSettingsTab = 'ai';

async function loadSettings() {
    // No-op now; settings are loaded on modal open
}

function setupSettings() {
    // No-op; modal handles everything
}

function openSettingsModal() {
    if (!serverReachable) return;
    const overlay = document.getElementById('settingsOverlay');
    const body = document.getElementById('settingsModalBody');
    const status = document.getElementById('settingsStatus');
    if (!overlay || !body) return;

    status.textContent = 'Loading...';
    overlay.classList.remove('hidden');
    body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim)">Loading settings...</div>';

    fetch('/api/v1/settings')
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(data => {
            currentSettingsData = data;
            renderAllSettingsTabs(body);
            switchSettingsTab(activeSettingsTab);
            status.textContent = '';
        })
        .catch(e => {
            body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--red)">Failed to load settings</div>';
            status.textContent = '';
        });
}

function closeSettingsModal() {
    const overlay = document.getElementById('settingsOverlay');
    if (overlay) overlay.classList.add('hidden');
}

function renderAllSettingsTabs(container) {
    container.innerHTML = '';
    for (const [sectionKey, section] of Object.entries(SETTINGS_SCHEMA)) {
        const sectionDiv = document.createElement('div');
        sectionDiv.className = 'settings-section';
        sectionDiv.id = `settings-section-${sectionKey}`;

        const sectionData = currentSettingsData[sectionKey] || {};

        for (const field of section.fields) {
            const val = sectionData[field.key];
            sectionDiv.appendChild(renderSettingRow(sectionKey, field, val));
        }
        container.appendChild(sectionDiv);
    }
}

function renderSettingRow(sectionKey, field, currentValue) {
    const row = document.createElement('div');
    row.className = 'setting-row';

    const inputId = `setting-${sectionKey}-${field.key}`;

    let inputHtml;
    if (field.type === 'bool') {
        const checked = currentValue ? 'checked' : '';
        inputHtml = `<label class="setting-toggle">
            <input type="checkbox" id="${inputId}" ${checked} data-section="${sectionKey}" data-key="${field.key}" data-type="bool">
            <span class="toggle-slider"></span>
        </label>`;
    } else if (field.type === 'text') {
        const displayVal = Array.isArray(currentValue) ? currentValue.join(', ') : (currentValue || '');
        inputHtml = `<input class="setting-input wide" type="text" id="${inputId}" value="${escHtml(String(displayVal))}" data-section="${sectionKey}" data-key="${field.key}" data-type="text">`;
    } else {
        const step = field.step || (field.type === 'int' ? 1 : 0.01);
        const v = currentValue != null ? currentValue : '';
        inputHtml = `<input class="setting-input" type="number" id="${inputId}" value="${v}" min="${field.min}" max="${field.max}" step="${step}" data-section="${sectionKey}" data-key="${field.key}" data-type="${field.type}">`;
    }

    row.innerHTML = `
        <div class="setting-row-top">
            <div>
                <span class="setting-label">${escHtml(field.label)}</span>
                <span class="setting-key">${sectionKey}.${field.key}</span>
            </div>
            ${inputHtml}
        </div>
        <div class="setting-desc">${escHtml(field.desc)}</div>
        ${field.example ? `<div class="setting-example">${escHtml(field.example)}</div>` : ''}
    `;
    return row;
}

function switchSettingsTab(tabKey) {
    activeSettingsTab = tabKey;
    document.querySelectorAll('.settings-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tabKey);
    });
    document.querySelectorAll('.settings-section').forEach(s => {
        s.classList.toggle('active', s.id === `settings-section-${tabKey}`);
    });
}

async function saveSettings() {
    if (!serverReachable) return;

    const saveBtn = document.getElementById('settingsSaveBtn');
    const status = document.getElementById('settingsStatus');
    if (saveBtn) saveBtn.disabled = true;
    if (status) status.textContent = 'Saving...';

    // Collect all values from inputs
    const payload = {};
    document.querySelectorAll('.settings-section [data-section]').forEach(el => {
        const section = el.dataset.section;
        const key = el.dataset.key;
        const type = el.dataset.type;

        if (!section || !key) return;
        if (!(section in payload)) payload[section] = {};

        if (type === 'bool') {
            payload[section][key] = el.checked;
        } else if (type === 'int') {
            payload[section][key] = parseInt(el.value, 10);
        } else if (type === 'float') {
            payload[section][key] = parseFloat(el.value);
        } else if (type === 'text') {
            payload[section][key] = el.value;
        }
    });

    try {
        const r = await fetch('/api/v1/settings', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
            body: JSON.stringify(payload)
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${r.status}`);
        }
        const data = await r.json();
        currentSettingsData = data;
        if (status) status.textContent = '';
        showSettingsToast('Settings saved successfully', 'success');
        closeSettingsModal();
    } catch (e) {
        if (status) status.textContent = '';
        showSettingsToast(e.message || 'Save failed', 'error');
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

function showSettingsToast(msg, type) {
    const toast = document.getElementById('settingsToast');
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `settings-toast ${type}`;
    // Re-trigger animation
    toast.style.animation = 'none';
    toast.offsetHeight; // force reflow
    toast.style.animation = '';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { toast.classList.add('hidden'); }, 3000);
}

// ---- Controls ----

async function togglePause() {
    if (!serverReachable) return;
    const ep = isPaused ? '/api/v1/control/resume' : '/api/v1/control/pause';
    try { await fetch(ep, { method: 'POST', headers: { ...csrfHeaders() } }); } catch {}
}

async function closeAll() {
    if (!serverReachable) return;
    if (!confirm('EMERGENCY: Close ALL open positions?')) return;
    try {
        const r = await fetch('/api/v1/control/close_all', { method: 'POST', headers: { ...csrfHeaders() } });
        const d = await r.json();
        alert(`Closed ${d.closed} positions`);
    } catch {}
}

async function logout() {
    try { await fetch('/logout', { method: 'POST', headers: { ...csrfHeaders() } }); } catch {}
    try { window.location.href = '/login'; } catch {}
}

// ---- Exports ----

async function downloadTradesCsv() {
    if (!serverReachable) return;
    try {
        const r = await fetch('/api/v1/export/trades.csv?limit=10000');
        if (!r.ok) {
            if (r.status === 401 || r.status === 403) alert('API key required to export trades.');
            return;
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'trades.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {}
}

// ---- Strategy Stats (only when server is reachable) ----

function strategyDisplayName(name) {
    if (!name) return 'UNKNOWN';
    return String(name).replace(/_/g, ' ').toUpperCase();
}

function ensureStrategyRow(name) {
    const grid = document.getElementById('strategyGrid');
    if (!grid) return null;
    if (strategyElements.has(name)) return strategyElements.get(name);

    if (strategyElements.size === 0) grid.innerHTML = '';

    const item = document.createElement('div');
    item.className = 'strategy-item';

    const nameEl = document.createElement('span');
    nameEl.className = 'strategy-name';
    nameEl.textContent = strategyDisplayName(name);

    const barWrap = document.createElement('div');
    barWrap.className = 'strategy-bar';
    const bar = document.createElement('div');
    bar.className = 'bar-fill';
    bar.style.width = '0%';
    barWrap.appendChild(bar);

    const stat = document.createElement('span');
    stat.className = 'strategy-stat';
    stat.textContent = '--';

    item.appendChild(nameEl);
    item.appendChild(barWrap);
    item.appendChild(stat);
    grid.appendChild(item);

    const entry = { bar, stat, nameEl, item };
    strategyElements.set(name, entry);
    return entry;
}

function initAlgoTooltip() {
    algoTooltip = document.getElementById('algoTooltip');
    const grid = document.getElementById('strategyGrid');
    if (!algoTooltip || !grid) return;

    grid.addEventListener('mousemove', (e) => {
        if (!algoTooltip || algoTooltip.classList.contains('hidden')) return;
        const offset = 12;
        const x = Math.min(window.innerWidth - 20, e.clientX + offset);
        const y = Math.min(window.innerHeight - 20, e.clientY + offset);
        algoTooltip.style.left = `${x}px`;
        algoTooltip.style.top = `${y}px`;
    });

    grid.addEventListener('mouseover', (e) => {
        const item = e.target.closest('.strategy-item');
        if (!item || !algoTooltip) return;
        const note = item.dataset.note;
        if (!note) {
            algoTooltip.classList.add('hidden');
            return;
        }
        algoTooltip.textContent = note;
        algoTooltip.classList.remove('hidden');
    });

    grid.addEventListener('mouseout', (e) => {
        const item = e.target.closest('.strategy-item');
        if (item && algoTooltip) algoTooltip.classList.add('hidden');
    });
}

function renderStrategies(strategies) {
    if (!Array.isArray(strategies)) return;

    // Remove stale strategy rows that are no longer in the payload
    const activeNames = new Set(strategies.filter(s => s && s.name).map(s => s.name));
    for (const [name, entry] of strategyElements) {
        if (!activeNames.has(name)) {
            entry.item.remove();
            strategyElements.delete(name);
        }
    }

    for (const s of strategies) {
        if (!s || !s.name) continue;
        const row = ensureStrategyRow(s.name);
        if (!row) continue;

        const winRate = Number(s.win_rate);
        const trades = Number(s.trades);
        const enabled = s.enabled !== false;
        const kind = s.kind || 'strategy';
        const isStrategy = kind === 'strategy';
        if (s.note) row.item.dataset.note = s.note;
        else delete row.item.dataset.note;

        if (isStrategy) {
            if (!enabled) {
                row.bar.style.width = '0%';
                row.stat.textContent = 'OFF';
                row.item.classList.add('disabled');
            } else if (Number.isFinite(winRate) && trades > 0) {
                row.bar.style.width = (Math.max(0, Math.min(winRate, 1)) * 100) + '%';
                row.stat.textContent = `${(winRate * 100).toFixed(0)}% (${trades})`;
                row.item.classList.remove('disabled');
            } else {
                row.bar.style.width = '100%';
                row.stat.textContent = 'ACTIVE';
                row.item.classList.remove('disabled');
            }
        } else {
            row.bar.style.width = enabled ? '100%' : '0%';
            row.stat.textContent = enabled ? 'ON' : 'OFF';
            if (!enabled) row.item.classList.add('disabled');
            else row.item.classList.remove('disabled');
        }
    }
}

// ---- Utilities ----

function setText(id, val) {
    const el = document.getElementById(id);
    if (el && el.textContent !== String(val)) el.textContent = val;
}

function formatMoney(v) {
    const n = Number(v) || 0;
    return (n >= 0 ? '+$' : '-$') + Math.abs(n).toFixed(2);
}

function formatMoneyPlain(v) {
    const n = Number(v) || 0;
    return '$' + Math.abs(n).toFixed(2);
}

function formatPrice(p) {
    p = Number(p) || 0;
    if (p >= 1000) return '$' + p.toFixed(2);
    if (p >= 1) return '$' + p.toFixed(4);
    return '$' + p.toFixed(6);
}

function formatQty(q) {
    const n = Number(q) || 0;
    if (Math.abs(n) >= 100) return n.toFixed(2);
    if (Math.abs(n) >= 1) return n.toFixed(4);
    return n.toFixed(6);
}

function formatUptime(s) {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

function formatTime(iso) {
    if (!iso) return '--:--:--';
    try { return new Date(iso).toLocaleTimeString('en-US', { hour12: false }); } catch { return '--:--:--'; }
}

function escHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

function safeJsonParse(val) {
    if (!val || typeof val !== 'string') return null;
    try { return JSON.parse(val); } catch { return null; }
}

function resolveConfidence(pos) {
    const direct = Number(pos?.confidence);
    if (Number.isFinite(direct)) return direct;
    const meta = typeof pos?.metadata === 'string' ? safeJsonParse(pos.metadata) : pos?.metadata;
    const metaConf = Number(meta?.ai_confidence);
    return Number.isFinite(metaConf) ? metaConf : null;
}

function renderConfidence(conf) {
    if (!Number.isFinite(conf)) return '<span class="cell-sub">--</span>';
    let pct = conf;
    if (pct > 1.01) pct = pct / 100;
    pct = Math.max(0, Math.min(pct, 1));
    const pctLabel = Math.round(pct * 100);
    return `<div class="conf-wrap">
        <span class="conf-text">${pctLabel}%</span>
        <div class="conf-bar"><div class="conf-fill" style="width:${pctLabel}%"></div></div>
    </div>`;
}

function getPnlPct(pos, entry, qty, pnl) {
    const raw = Number(pos?.unrealized_pnl_pct);
    if (Number.isFinite(raw)) return raw;
    const denom = Math.abs(entry * qty);
    if (denom <= 0) return 0;
    return pnl / denom;
}

// ---- Init ----

document.addEventListener('DOMContentLoaded', () => {
    const chartWatermarkUrl = document.getElementById('chartWatermarkUrl');
    if (chartWatermarkUrl) chartWatermarkUrl.textContent = getPublicDashboardUrl();
    connectWebSocket();
    setupThoughtScroll();
    setupFavorites();
    setupSettings();
    setupChartModal();
    initAlgoTooltip();
    // Load settings when server is reachable (after first WS connect)
    setInterval(loadSettings, 15000);
    loadSettings();
    // NO fallback polling — WebSocket is the sole data channel.
    // Strategies are now included in the WS update payload.
});
