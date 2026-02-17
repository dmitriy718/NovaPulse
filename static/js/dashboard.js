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
    renderStatus(data.status);
    renderPerformance(data.performance, data.risk);
    renderPositions(data.positions);
    renderThoughts(data.thoughts);
    renderScanner(data.scanner);
    renderRisk(data.risk);
    if (data.strategies) renderStrategies(data.strategies);
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
        const qty = Number(pos.quantity) || 0;
        const entry = Number(pos.entry_price) || 0;
        const current = Number(pos.current_price) || 0;
        const pnl = Number(pos.unrealized_pnl) || 0;
        const pnlPct = getPnlPct(pos, entry, qty, pnl);
        const sizeUsd = Math.abs((current || entry) * qty);
        const conf = resolveConfidence(pos);
        html += `<tr>
            <td>${pos.pair}</td>
            <td class="${pos.side === 'buy' ? 'side-buy' : 'side-sell'}">${pos.side.toUpperCase()}</td>
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
    const existing = grid.querySelectorAll('.scanner-item');

    if (existing.length === entries.length) {
        entries.forEach(([pair, data], i) => {
            const item = existing[i];
            const price = data.price || 0;
            if (!priceHistory[pair]) priceHistory[pair] = [];
            priceHistory[pair].push(price);
            if (priceHistory[pair].length > 20) priceHistory[pair].shift();
            item.querySelector('.scanner-pair').textContent = pair;
            item.querySelector('.scanner-price').textContent = formatPrice(price);
            item.querySelector('.scanner-bars').textContent = (data.bars || 0) + ' bars';
            item.classList.toggle('stale', !!data.stale);
            const spark = item.querySelector('.sparkline');
            if (spark) spark.innerHTML = generateSparkline(priceHistory[pair]);
        });
        return;
    }

    let html = '';
    for (const [pair, data] of entries) {
        const price = data.price || 0;
        if (!priceHistory[pair]) priceHistory[pair] = [];
        priceHistory[pair].push(price);
        if (priceHistory[pair].length > 20) priceHistory[pair].shift();
        html += `<div class="scanner-item${data.stale ? ' stale' : ''}">
            <span class="scanner-pair">${pair}</span>
            <span class="scanner-price">${formatPrice(price)}</span>
            <div class="sparkline">${generateSparkline(priceHistory[pair])}</div>
            <span class="scanner-bars">${data.bars || 0} bars</span>
        </div>`;
    }
    grid.innerHTML = html || '<div class="scanner-item"><span class="scanner-pair">Waiting...</span></div>';
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
            if (Number.isFinite(winRate) && trades > 0) {
                row.bar.style.width = (Math.max(0, Math.min(winRate, 1)) * 100) + '%';
                row.stat.textContent = `${(winRate * 100).toFixed(0)}% (${trades})`;
            } else {
                row.bar.style.width = '0%';
                row.stat.textContent = '--';
            }
        } else {
            row.bar.style.width = enabled ? '100%' : '0%';
            row.stat.textContent = enabled ? 'ON' : 'OFF';
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
    connectWebSocket();
    setupThoughtScroll();
    setupSettings();
    initAlgoTooltip();
    // Load settings when server is reachable (after first WS connect)
    setInterval(loadSettings, 15000);
    loadSettings();
    // NO fallback polling — WebSocket is the sole data channel.
    // Strategies are now included in the WS update payload.
});
