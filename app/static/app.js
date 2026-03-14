// Detect base path for reverse proxy support (e.g. /zoom/)
const BASE = window.location.pathname.replace(/\/+$/, '');
const API = `${BASE}/api/v1/zoom`;
let pollingIntervals = {};
let elapsedTimers = {};

// --- DOM refs ---
const zoomUrl = document.getElementById('zoomUrl');
const botName = document.getElementById('botName');
const langSelect = document.getElementById('langSelect');
const autoTranscribe = document.getElementById('autoTranscribe');
const joinBtn = document.getElementById('joinBtn');
const sessionsList = document.getElementById('sessionsList');
const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modalTitle');
const modalBody = document.getElementById('modalBody');
const statusCard = document.getElementById('statusCard');
const statusGrid = document.getElementById('statusGrid');
const statusOverall = document.getElementById('statusOverall');
const healthDot = document.getElementById('healthDot');

// --- URL validation ---
function isValidZoomUrl(url) {
    return /https?:\/\/[^/]*zoom\.[^/]+\/j\/\d+/.test(url);
}

zoomUrl.addEventListener('input', () => {
    joinBtn.disabled = !zoomUrl.value.trim();
});

zoomUrl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !joinBtn.disabled) joinBtn.click();
});

// --- Join meeting ---
joinBtn.addEventListener('click', async () => {
    const url = zoomUrl.value.trim();
    if (!url) return;

    if (!isValidZoomUrl(url)) {
        showNotification('Некорректная ссылка на Zoom-встречу. Ожидается формат: https://zoom.us/j/12345678', 'error');
        return;
    }

    joinBtn.disabled = true;
    joinBtn.textContent = 'Подключение...';

    try {
        const body = {
            zoom_url: url,
            language: langSelect.value,
            auto_transcribe: autoTranscribe.checked,
        };

        const name = botName.value.trim();
        if (name) body.bot_name = name;

        const resp = await fetch(`${API}/join`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const session = await resp.json();
        showNotification('Бот подключается к встрече...', 'info');
        zoomUrl.value = '';
        joinBtn.disabled = true;

        addSessionToList(session);
        startPolling(session.session_id);

    } catch (e) {
        showNotification('Ошибка: ' + e.message, 'error');
    } finally {
        joinBtn.disabled = !zoomUrl.value.trim();
        joinBtn.textContent = 'Подключиться и записать';
    }
});

// --- Notification ---
function showNotification(message, type = 'info') {
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();

    const el = document.createElement('div');
    el.className = `notification notification-${type}`;
    el.innerHTML = `
        <span class="notification-text">${escapeHtml(message)}</span>
        <button class="notification-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    document.body.appendChild(el);

    setTimeout(() => el.classList.add('visible'), 10);
    setTimeout(() => {
        el.classList.remove('visible');
        setTimeout(() => el.remove(), 300);
    }, 6000);
}

// --- Health check ---
function toggleStatus() {
    statusCard.style.display = statusCard.style.display === 'none' ? 'block' : 'none';
}

async function checkHealth() {
    statusCard.style.display = 'block';
    healthDot.className = 'health-dot checking';

    statusGrid.innerHTML = `
        <div class="status-item checking">
            <div class="status-item-header">
                <span class="status-icon">&#9679;</span> AIAP Protocol
                <span class="status-checking">проверка...</span>
            </div>
        </div>
    `;
    statusOverall.textContent = 'Проверка...';
    statusOverall.className = 'status-overall checking';

    try {
        const resp = await fetch(`${BASE}/health/details`);
        const data = await resp.json();

        const aiap = data.aiap_protocol;
        const isOk = aiap.ok;

        statusGrid.innerHTML = `
            <div class="status-item ${isOk ? 'ok' : 'error'}">
                <div class="status-item-header">
                    <span class="status-icon status-icon-${isOk ? 'ok' : 'error'}">&#9679;</span>
                    <span class="status-name">&#129302; AIAP Protocol (расшифровка)</span>
                </div>
                <div class="status-message">${isOk ? 'Подключён — ' + escapeHtml(aiap.url) : 'Недоступен: ' + escapeHtml(aiap.error || 'unknown')}</div>
            </div>
            <div class="status-item ${data.recordings_dir_exists ? 'ok' : 'error'}">
                <div class="status-item-header">
                    <span class="status-icon status-icon-${data.recordings_dir_exists ? 'ok' : 'error'}">&#9679;</span>
                    <span class="status-name">&#128451; Хранилище записей</span>
                </div>
                <div class="status-message">${data.recordings_dir}</div>
            </div>
        `;

        const overall = data.status === 'ok';
        statusOverall.textContent = overall ? 'Все службы работают' : 'Есть проблемы';
        statusOverall.className = `status-overall ${overall ? 'ok' : 'error'}`;
        healthDot.className = `health-dot ${overall ? 'ok' : 'error'}`;
    } catch (e) {
        statusGrid.innerHTML = `
            <div class="status-item error">
                <div class="status-item-header">
                    <span class="status-icon">&#9679;</span> Ошибка проверки
                </div>
                <div class="status-message">${escapeHtml(e.message)}</div>
            </div>
        `;
        statusOverall.textContent = 'Ошибка';
        statusOverall.className = 'status-overall error';
        healthDot.className = 'health-dot error';
    }
}

// --- Sessions ---
async function loadSessions() {
    try {
        const resp = await fetch(`${API}/sessions`);
        const sessions = await resp.json();

        if (!sessions.length) {
            sessionsList.innerHTML = '<div class="jobs-empty">Нет активных сессий. Введите ссылку на Zoom-встречу для начала.</div>';
            return;
        }

        sessionsList.innerHTML = '';
        sessions.reverse().forEach(session => {
            renderSession(session);
            if (!isTerminal(session.status)) startPolling(session.session_id);
        });
    } catch (e) {
        sessionsList.innerHTML = '<div class="jobs-empty">Не удалось загрузить сессии</div>';
    }
}

function addSessionToList(session) {
    const empty = sessionsList.querySelector('.jobs-empty');
    if (empty) empty.remove();
    renderSession(session, true);
}

function renderSession(session, prepend = false) {
    const el = document.createElement('div');
    el.className = 'job-item';
    el.id = `session-${session.session_id}`;
    el.innerHTML = buildSessionHTML(session);

    if (prepend) {
        sessionsList.prepend(el);
    } else {
        sessionsList.appendChild(el);
    }

    if (!isTerminal(session.status) && session.started_at) {
        startElapsedTimer(session.session_id, new Date(session.started_at).getTime() / 1000);
    }
}

function updateSession(session) {
    const el = document.getElementById(`session-${session.session_id}`);
    if (el) {
        el.innerHTML = buildSessionHTML(session);
    } else {
        addSessionToList(session);
    }

    if (isTerminal(session.status)) {
        stopElapsedTimer(session.session_id);
    } else if (session.started_at) {
        startElapsedTimer(session.session_id, new Date(session.started_at).getTime() / 1000);
    }
}

function buildSessionHTML(session) {
    const statusLabel = getStatusLabel(session.status);
    const progress = getProgress(session.status);
    const isActive = !isTerminal(session.status);
    const shortId = session.session_id.substring(0, 8);

    let html = `
        <div class="job-header">
            <span class="job-id">${shortId}... &middot; ${escapeHtml(session.bot_name)}</span>
            <span class="status-badge status-${session.status}">
                ${statusLabel}
                ${isActive ? `<span class="elapsed-timer" id="elapsed-${session.session_id}"></span>` : ''}
            </span>
        </div>
        <div class="job-url">&#128279; ${escapeHtml(session.zoom_url)}</div>
    `;

    // Meta info
    const meta = [];
    if (session.created_at) {
        meta.push(`&#128197; ${formatDate(session.created_at)}`);
    }
    if (session.duration_sec != null) {
        meta.push(`&#9201; ${formatDuration(session.duration_sec)}`);
    }
    if (meta.length) {
        html += `<div class="job-meta">${meta.map(m => `<span class="job-meta-item">${m}</span>`).join('')}</div>`;
    }

    // Progress
    if (isActive) {
        const isRec = session.status === 'recording';
        html += `
            <div class="job-progress-section">
                <div class="progress-bar active">
                    <div class="progress-fill ${isRec ? 'recording' : ''}" style="width: ${progress}%"></div>
                </div>
                <div class="job-steps">
                    ${buildStepIndicators(session.status)}
                </div>
            </div>
        `;
    }

    // Actions
    if (session.status === 'recording') {
        html += `
            <div class="session-actions">
                <button class="btn btn-sm btn-danger" onclick="stopSession('${session.session_id}')">
                    Остановить запись
                </button>
            </div>
        `;
    }

    if (session.status === 'completed' && !session.transcription_job_id) {
        html += `
            <div class="session-actions">
                <button class="btn btn-sm btn-success" onclick="transcribeSession('${session.session_id}')">
                    Отправить на расшифровку
                </button>
            </div>
        `;
    }

    // Transcription info
    if (session.transcription_job_id) {
        html += `
            <div class="transcription-info">
                <div class="label">Расшифровка</div>
                <div class="value">
                    Job ID: ${escapeHtml(session.transcription_job_id)}
                    ${session.transcription_status ? ' &middot; ' + escapeHtml(session.transcription_status) : ''}
                </div>
            </div>
        `;
    }

    // Error
    if (session.status === 'failed' && session.error) {
        html += `
            <div class="job-error">
                <strong>Ошибка:</strong> ${escapeHtml(session.error)}
            </div>
        `;
    }

    return html;
}

function buildStepIndicators(currentStatus) {
    const steps = [
        { key: 'pending', label: 'Ожидание' },
        { key: 'joining', label: 'Подключение' },
        { key: 'recording', label: 'Запись' },
        { key: 'stopping', label: 'Остановка' },
        { key: 'uploading', label: 'Расшифровка' },
    ];
    const order = ['pending', 'joining', 'recording', 'stopping', 'uploading', 'completed'];
    const currentIdx = order.indexOf(currentStatus);

    return steps.map((step, i) => {
        let cls = 'step-pending';
        if (i < currentIdx) cls = 'step-done';
        else if (i === currentIdx) cls = step.key === 'recording' ? 'step-recording' : 'step-active';
        return `<span class="job-step ${cls}">${step.label}</span>`;
    }).join('');
}

// --- Actions ---
async function stopSession(sessionId) {
    try {
        const resp = await fetch(`${API}/stop/${sessionId}`, { method: 'POST' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const session = await resp.json();
        updateSession(session);
        showNotification('Запись останавливается...', 'info');
    } catch (e) {
        showNotification('Ошибка остановки: ' + e.message, 'error');
    }
}

async function transcribeSession(sessionId) {
    try {
        const resp = await fetch(`${API}/transcribe/${sessionId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: langSelect.value }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        showNotification('Отправлено на расшифровку: ' + data.transcription_job_id, 'success');
        // Refresh the session
        const statusResp = await fetch(`${API}/status/${sessionId}`);
        if (statusResp.ok) updateSession(await statusResp.json());
    } catch (e) {
        showNotification('Ошибка: ' + e.message, 'error');
    }
}

// --- Polling ---
function startPolling(sessionId) {
    if (pollingIntervals[sessionId]) return;

    pollingIntervals[sessionId] = setInterval(async () => {
        try {
            const resp = await fetch(`${API}/status/${sessionId}`);
            const session = await resp.json();
            updateSession(session);

            if (isTerminal(session.status)) {
                clearInterval(pollingIntervals[sessionId]);
                delete pollingIntervals[sessionId];

                if (session.status === 'completed') {
                    if (session.transcription_job_id) {
                        showNotification('Запись завершена и отправлена на расшифровку!', 'success');
                    } else {
                        showNotification('Запись завершена!', 'success');
                    }
                } else if (session.status === 'failed') {
                    showNotification('Сессия завершилась с ошибкой', 'error');
                }
            }
        } catch (e) {
            // silently retry
        }
    }, 3000);
}

function isTerminal(status) {
    return status === 'completed' || status === 'failed';
}

function getProgress(status) {
    const map = {
        pending: 5,
        joining: 20,
        recording: 50,
        stopping: 75,
        uploading: 90,
        completed: 100,
        failed: 100,
    };
    return map[status] || 0;
}

function getStatusLabel(status) {
    const map = {
        pending: 'Ожидание',
        joining: 'Подключение',
        recording: 'Запись',
        stopping: 'Остановка',
        uploading: 'Отправка на расшифровку',
        completed: 'Завершено',
        failed: 'Ошибка',
    };
    return map[status] || status;
}

// --- Elapsed timer ---
function formatDuration(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}ч ${m}м ${s}с`;
    if (m > 0) return `${m}м ${s}с`;
    return `${s}с`;
}

function formatDate(isoString) {
    const d = new Date(isoString);
    return d.toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

function startElapsedTimer(sessionId, startTimestamp) {
    stopElapsedTimer(sessionId);
    if (!startTimestamp) return;

    function update() {
        const el = document.getElementById(`elapsed-${sessionId}`);
        if (!el) return;
        const elapsed = (Date.now() / 1000) - startTimestamp;
        el.textContent = formatDuration(Math.max(0, elapsed));
    }
    update();
    elapsedTimers[sessionId] = setInterval(update, 1000);
}

function stopElapsedTimer(sessionId) {
    if (elapsedTimers[sessionId]) {
        clearInterval(elapsedTimers[sessionId]);
        delete elapsedTimers[sessionId];
    }
}

// --- Modal ---
function closeModal() {
    modal.classList.remove('active');
}

modal.addEventListener('click', e => {
    if (e.target === modal) closeModal();
});

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
});

// --- Utils ---
function escapeHtml(text) {
    if (!text) return '';
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

// --- Init ---
loadSessions();
