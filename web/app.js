// VANTIQ: AI-Powered Business Intelligence Assistant — HUD Controller

let recognition = null;
let isListening = false;
let synth = window.speechSynthesis;
let currentBIReport = null;
let activeBITab = 'overview';
let isCommandExecuting = false;
let currentActiveRequestId = null;

if (!window.vantiqSessionId) {
    window.sarthiSessionId = window.vantiqSessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
}

document.addEventListener('DOMContentLoaded', () => {
    initVoiceRecognition();
    fetchSystemStatus();
    setInterval(fetchSystemStatus, 2000);
    initDataImportModule();
    loadSavedDatasets();
    initCatalogueModule();
    initConsoleExampleRotator();

    // Keyboard shortcut: Spacebar to toggle voice when input not focused
    window.addEventListener('keydown', (e) => {
        const tag = document.activeElement ? document.activeElement.tagName : '';
        if (e.code === 'Space' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
            e.preventDefault();
            toggleVoiceListening();
        }
    });
});

// Update Telemetry & Status
async function fetchSystemStatus() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        // Update Date & Time
        document.getElementById('hudDate').textContent = data.date || '--';
        document.getElementById('hudTime').textContent = data.time || '--';

        // Update CPU & RAM
        const cpu = Math.round(data.cpu || 0);
        const ram = Math.round(data.ram || 0);
        document.getElementById('cpuVal').textContent = `${cpu}%`;
        document.getElementById('cpuBar').style.width = `${cpu}%`;
        document.getElementById('ramVal').textContent = `${ram}%`;
        document.getElementById('ramBar').style.width = `${ram}%`;

        // Update Battery / Arc Reactor
        if (data.battery) {
            const battP = data.battery.percent;
            const plug = data.battery.power_plugged ? '⚡ Charging' : 'On Arc Core';
            document.getElementById('batteryVal').textContent = `${battP}% (${plug})`;
            document.getElementById('batteryBar').style.width = `${battP}%`;
        } else {
            document.getElementById('batteryVal').textContent = '100% (STABLE CORE)';
            document.getElementById('batteryBar').style.width = '100%';
        }

        // Update Platform Info
        if (data.system) {
            document.getElementById('platformVal').textContent = `${data.system} ${data.release || ''}`;
        }

        // Update Local AI Telemetry
        if (data.local_llm) {
            const llm = data.local_llm;
            const statusEl = document.getElementById('hudLlmStatusVal');
            const latencyEl = document.getElementById('hudLlmLatencyVal');
            const dotEl = document.getElementById('llmPulseDot');
            const badgeEl = document.getElementById('llmModelBadge');

            if (statusEl) {
                if (llm.status === 'busy') {
                    statusEl.textContent = 'BUSY';
                    statusEl.className = 'cat-stat-val cyan';
                } else if (llm.status === 'online') {
                    statusEl.textContent = 'ONLINE';
                    statusEl.className = 'cat-stat-val cyan';
                } else if (llm.status === 'standby') {
                    statusEl.textContent = 'STANDBY';
                    statusEl.className = 'cat-stat-val amber';
                } else if (llm.status === 'timeout') {
                    statusEl.textContent = 'TIMEOUT';
                    statusEl.className = 'cat-stat-val amber';
                } else if (llm.status === 'model_missing') {
                    statusEl.textContent = 'MISSING';
                    statusEl.className = 'cat-stat-val red';
                } else {
                    statusEl.textContent = 'OFFLINE';
                    statusEl.className = 'cat-stat-val red';
                }
            }
            if (latencyEl) {
                latencyEl.textContent = llm.latency_ms ? `${llm.latency_ms}ms` : (llm.status === 'busy' ? 'ACTIVE' : '--');
            }
            if (dotEl) {
                dotEl.className = `ai-pulse-dot ${llm.status || 'offline'}`;
            }
            if (badgeEl && llm.model) {
                badgeEl.textContent = llm.model;
            }
        }
        if (data.processor) {
            document.getElementById('procVal').textContent = data.processor.substring(0, 24);
        }

        // Update System Status Badge in HUD Header
        const systemBadge = document.getElementById('systemStatusBadge');
        const statusText = document.getElementById('statusText');
        if (systemBadge && statusText) {
            const dbOk = (data.database && (data.database.connected || data.database.healthy)) || 
                         (data.subsystems && data.subsystems.database && data.subsystems.database.healthy);
            const llmOk = data.local_llm && (data.local_llm.status === 'online' || data.local_llm.status === 'busy');
            if (dbOk && llmOk) {
                systemBadge.className = 'status-badge online';
                statusText.textContent = 'SYSTEM ONLINE';
            } else if (dbOk) {
                systemBadge.className = 'status-badge warning';
                statusText.textContent = 'SYSTEM OPERATIONAL (AI STANDBY)';
            } else {
                systemBadge.className = 'status-badge offline';
                statusText.textContent = 'SYSTEM DEGRADED';
            }
        }

        const footerStatusEl = document.getElementById('footerStatus');
        if (footerStatusEl) {
            const llm = data.local_llm;
            let llmStatus = 'LOCAL AI OFFLINE';
            if (llm) {
                if (llm.status === 'busy') {
                    llmStatus = 'LOCAL AI INFERENCE ACTIVE';
                } else if (llm.status === 'online' && llm.model_available) {
                    llmStatus = `LOCAL AI ONLINE (${llm.latency_ms || 0}ms)`;
                } else if (llm.status === 'model_missing') {
                    llmStatus = `MODEL MISSING (${llm.model || 'qwen'})`;
                } else if (llm.status === 'timeout') {
                    llmStatus = 'LOCAL AI TIMEOUT';
                } else if (llm.service_running) {
                    llmStatus = 'LOCAL AI STANDBY';
                }
            }
            const dbConnected = (data.database && (data.database.connected || data.database.healthy)) || (data.subsystems && data.subsystems.database && data.subsystems.database.healthy);
            const dbStatus = dbConnected ? 'DB: ONLINE' : 'DB: OFFLINE';
            const ragOk = data.subsystems && data.subsystems.rag && data.subsystems.rag.healthy;
            const ragStatus = ragOk ? 'RAG: READY' : 'RAG: STANDBY';
            footerStatusEl.textContent = `CORE: ONLINE // ${dbStatus} // ${ragStatus} // ${llmStatus}`;
        }

        // Update Radar Telemetry Label with truthful system indicator
        const radarLabel = document.getElementById('radarTelemetryLabel');
        if (radarLabel) {
            radarLabel.textContent = `SYSTEM ENGINE: ${data.status || 'ONLINE'}`;
        }

    } catch (err) {
        console.warn('Status poll warning:', err);
        const systemBadge = document.getElementById('systemStatusBadge');
        const statusText = document.getElementById('statusText');
        if (systemBadge && statusText) {
            systemBadge.className = 'status-badge offline';
            statusText.textContent = 'SYSTEM OFFLINE';
        }
        const footerStatusEl = document.getElementById('footerStatus');
        if (footerStatusEl) {
            footerStatusEl.textContent = 'STATUS: OFFLINE / DISCONNECTED';
        }
        const radarLabel = document.getElementById('radarTelemetryLabel');
        if (radarLabel) {
            radarLabel.textContent = 'SYSTEM ENGINE: OFFLINE';
        }
    }
}

// Log message to HUD Terminal
function logTerminal(message, type = 'system') {
    const logBox = document.getElementById('terminalLog');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    
    let prefix = '[SYS]';
    if (type === 'user') prefix = '[COMMAND]';
    if (type === 'jarvis' || type === 'vantiq') prefix = '[VANTIQ]';

    entry.textContent = `${prefix} ${message}`;
    logBox.appendChild(entry);
    logBox.scrollTop = logBox.scrollHeight;
}

let isAssistantSpeaking = false;
let currentSpeechLang = (localStorage.getItem('sarthi_speech_lang') || localStorage.getItem('vantiq_speech_lang')) || 'en-IN';

// Speak out response using Web SpeechSynthesis
function vantiqSpeak(text) {
    if (!synth) return;
    synth.cancel(); // cancel any active speech
    isAssistantSpeaking = true;

    // Prevent echo: If mic is currently active, abort recognition to avoid hearing itself
    if (recognition && isListening) {
        try { recognition.abort(); } catch (e) {}
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.05;
    utterance.pitch = 0.95;

    // Detect if response contains Hindi Devanagari script
    const hasDevanagari = /[\u0900-\u097F]/.test(text);

    // Pick professional voice matching the language
    const voices = synth.getVoices();
    let chosenVoice = null;
    if (hasDevanagari) {
        chosenVoice = voices.find(v => v.lang.startsWith('hi'));
        utterance.lang = 'hi-IN';
    }
    if (!chosenVoice) {
        chosenVoice = voices.find(v => v.lang.includes('IN') || v.name.includes('India')) ||
                      voices.find(v => v.name.includes('David') || v.name.includes('George') || v.name.includes('Male') || v.lang.startsWith('en'));
    }
    if (chosenVoice) {
        utterance.voice = chosenVoice;
    }

    utterance.onend = () => {
        setTimeout(() => { isAssistantSpeaking = false; }, 400);
    };
    utterance.onerror = () => {
        isAssistantSpeaking = false;
    };

    synth.speak(utterance);
}
const jarvisSpeak = vantiqSpeak; // Backwards-compatible alias

// Speech Recognition Init
function initVoiceRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        document.getElementById('listenerStatus').textContent = 'WEB SPEECH API NOT SUPPORTED';
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = currentSpeechLang;

    recognition.onstart = () => {
        isListening = true;
        document.getElementById('micBtn').classList.add('listening');
        document.getElementById('listenerStatus').textContent = `LISTENING (${currentSpeechLang})...`;
        document.getElementById('voiceIndicator').textContent = 'AUDIO SENSORS ACTIVE...';
    };

    recognition.onresult = (event) => {
        // Echo prevention: Ignore self-produced audio
        if (isAssistantSpeaking) {
            console.log('Ignored speech event while assistant was speaking.');
            return;
        }
        if (isCommandExecuting) {
            console.log('Ignored speech event: another command is currently executing.');
            return;
        }
        const transcript = event.results[0][0].transcript;
        logTerminal(transcript, 'user');
        executeCommand(transcript);
    };

    recognition.onerror = (event) => {
        console.warn('Recognition error:', event.error);
        stopListeningState();
    };

    recognition.onend = () => {
        stopListeningState();
    };
}

function setSpeechLanguage(lang) {
    currentSpeechLang = lang || 'en-IN';
    localStorage.setItem('sarthi_speech_lang', currentSpeechLang); localStorage.setItem('vantiq_speech_lang', currentSpeechLang);
    if (recognition) {
        recognition.lang = currentSpeechLang;
    }
    logTerminal(`Speech recognition language set to ${currentSpeechLang}`, 'system');
}

function stopListeningState() {
    isListening = false;
    document.getElementById('micBtn').classList.remove('listening');
    document.getElementById('listenerStatus').textContent = 'VOICE ENGINE READY';
    document.getElementById('voiceIndicator').textContent = 'CLICK TO ENGAGE SPEECH';
}

function toggleVoiceListening() {
    if (!recognition) {
        logTerminal('Web Speech Recognition is not supported on this browser. Please use text input or Chrome/Edge.', 'system');
        return;
    }

    if (isListening) {
        recognition.stop();
        stopListeningState();
    } else {
        try {
            recognition.start();
        } catch (e) {
            console.error('Recognition start error:', e);
        }
    }
}

// Rotating Example Queries & Console Guidance
const SARTHI_CONSOLE_EXAMPLES = [
    "Which products are currently low in stock?",
    "Show me the latest purchase price of a product.",
    "Which products have the highest gross margins?",
    "Summarize this month's sales performance.",
    "Which suppliers provide a particular product?",
    "Show products that have not been sold recently."
];

let sarthiExampleIndex = 0;
let sarthiExampleTimer = null;

function initConsoleExampleRotator() {
    const el = document.getElementById('exampleRotatorQuery');
    if (!el) return;

    const cycleNext = () => {
        sarthiExampleIndex = (sarthiExampleIndex + 1) % SARTHI_CONSOLE_EXAMPLES.length;
        el.style.opacity = '0';
        setTimeout(() => {
            el.textContent = SARTHI_CONSOLE_EXAMPLES[sarthiExampleIndex];
            el.style.opacity = '1';
        }, 220);
    };

    sarthiExampleTimer = setInterval(cycleNext, 4500);

    const rotatorBox = document.getElementById('guidanceExampleRotator');
    if (rotatorBox) {
        rotatorBox.addEventListener('mouseenter', () => {
            if (sarthiExampleTimer) clearInterval(sarthiExampleTimer);
        });
        rotatorBox.addEventListener('mouseleave', () => {
            sarthiExampleTimer = setInterval(cycleNext, 4500);
        });
    }
}

function setConsoleQuery(queryText) {
    const input = document.getElementById('commandInput');
    if (!input) return;
    const clean = (queryText || '').trim();
    if (clean) {
        input.value = clean;
        input.focus();
    }
}

// Handle Form Submission
function handleCommandSubmit(e) {
    e.preventDefault();
    if (isCommandExecuting) {
        console.warn('Command currently executing. Please wait.');
        return;
    }
    const input = document.getElementById('commandInput');
    const command = input.value.trim();
    if (!command) return;

    logTerminal(command, 'user');
    input.value = '';
    executeCommand(command);
}

// Execute Command against Backend
async function executeCommand(cmd) {
    if (isCommandExecuting) {
        console.warn('A command is already executing. Concurrent submission blocked.');
        return;
    }
    const trimmed = (cmd || '').trim();
    if (!trimmed) return;

    isCommandExecuting = true;
    const requestId = 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
    currentActiveRequestId = requestId;

    const sendBtn = document.getElementById('sendBtn');
    const input = document.getElementById('commandInput');
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.classList.add('loading');
        sendBtn.textContent = 'EXECUTING...';
    }
    if (input) {
        input.disabled = true;
    }

    document.getElementById('listenerStatus').textContent = 'PROCESSING TACTICAL ORDER...';
    try {
        const res = await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                command: trimmed,
                request_id: requestId,
                session_id: window.sarthiSessionId || window.vantiqSessionId
            })
        });
        const data = await res.json();

        // Stale response protection: Drop if superseded
        if (data.request_id && data.request_id !== currentActiveRequestId) {
            console.warn(`[${data.request_id}] Dropped stale response (active: ${currentActiveRequestId})`);
            return;
        }

        if (data.speak) {
            logTerminal(data.speak, 'jarvis');
            jarvisSpeak(data.speak);
        }

        // Action handlers
        if (data.action === 'joke') {
            displayIntelCard('PROGRAMMING JOKE', `<p style="font-size: 1.1rem; color: #fff;">"${data.display}"</p>`);
        } else if (data.action === 'time' || data.action === 'date') {
            displayIntelCard('CHRONOMETRIC DATA', `<h2 style="color: var(--cyan);">${data.display}</h2>`);
        } else if (data.action === 'youtube' && data.url) {
            displayIntelCard('MEDIA PROTOCOL', `<p>${data.display}</p><a href="${data.url}" target="_blank" style="color: var(--cyan); text-decoration: underline;">Launch YouTube Stream</a>`);
            window.open(data.url, '_blank');
        } else if (data.action === 'llm_explanation') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('LOCAL AI EXPLANATION', `
                <div class="source-badge">SOURCE: ${data.source || 'Local AI (qwen3:4b-instruct)'}</div>
                <div class="llm-explanation-box">
                    ${escapeHtml(data.explanation || data.display)}
                </div>
                <div class="llm-meta-tag">
                    <span>⚡ Model: ${escapeHtml(data.model || 'qwen3:4b-instruct')}</span>
                    ${data.inference_time_seconds ? `<span>• Latency: ${data.inference_time_seconds}s</span>` : ''}
                    <span>• Local Offline Inference</span>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'identity' || data.action === 'capabilities' || data.action === 'greeting' || data.action === 'acknowledgement') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('VANTIQ AI ASSISTANT', `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'VANTIQ Core')}</div>
                <div class="llm-explanation-box">
                    ${escapeHtml(data.display || data.speak)}
                </div>
                ${followUps}
            `);
        } else if (data.action === 'general_chat') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('VANTIQ CONVERSATIONAL AI', `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'Local AI')}</div>
                <div class="llm-explanation-box">
                    ${escapeHtml(data.display || data.speak)}
                </div>
                ${followUps}
            `);
        } else if (data.action === 'wikipedia') {
            displayIntelCard('WIKIPEDIA ARCHIVE', `<p style="line-height: 1.5;">${data.display}</p>`);
        } else if (data.action === 'covid') {
            requestCovid(data.state || 'delhi');
        } else if (data.action === 'contacts') {
            requestContacts();
        } else if (data.action === 'news') {
            requestNews();
        } else if (data.action === 'bi_report_summary') {
            displayIntelCard('BUSINESS INTELLIGENCE REPORT', `<p style="color: var(--cyan);">${data.display}</p><button class="launch-bi-btn" style="margin-top: 8px;" onclick="openBIModal()">⚡ OPEN DOSSIER</button>`);
            if (data.report) currentBIReport = data.report;
        } else if (data.action === 'bi_quality') {
            let list = '<ul style="list-style: none; font-size: 0.75rem; display: flex; flex-direction: column; gap: 4px;">';
            (data.issues || []).forEach(it => {
                list += `<li>⚠️ [${it.severity}] ${it.column}: ${it.message}</li>`;
            });
            list += '</ul>';
            displayIntelCard('DATA QUALITY AUDIT', `<p style="margin-bottom: 6px; font-weight: bold; color: var(--gold);">${data.display}</p>${list}<button class="launch-bi-btn" style="margin-top: 8px;" onclick="openBIModal(); switchBITab('quality');">VIEW AUDIT DETAILS</button>`);
        } else if (data.action === 'bi_pricing' || data.action === 'bi_pricing_unavailable') {
            displayIntelCard('PRICING & PROFITABILITY', `<p style="color: #fff; line-height: 1.4;">${data.display}</p><button class="launch-bi-btn" style="margin-top: 8px;" onclick="openBIModal(); switchBITab('pricing');">VIEW MARGINS</button>`);
        } else if (data.action === 'bi_inventory' || data.action === 'bi_inventory_unavailable') {
            displayIntelCard('INVENTORY TELEMETRY', `<p style="color: #fff; line-height: 1.4;">${data.display}</p><button class="launch-bi-btn" style="margin-top: 8px;" onclick="openBIModal(); switchBITab('inventory');">VIEW INVENTORY</button>`);
        } else if (data.action === 'bi_sales' || data.action === 'bi_sales_unavailable') {
            displayIntelCard('SALES & REVENUE', `<p style="color: #fff; line-height: 1.4;">${data.display}</p><button class="launch-bi-btn" style="margin-top: 8px;" onclick="openBIModal(); switchBITab('sales');">VIEW SALES DECK</button>`);
        } else if (data.action === 'bi_insights') {
            let list = '<ul style="list-style: none; font-size: 0.75rem; display: flex; flex-direction: column; gap: 6px;">';
            (data.insights || []).forEach(i => {
                list += `<li><strong style="color: var(--cyan);">⚡ ${i.title}:</strong> ${i.explanation}</li>`;
            });
            list += '</ul>';
            displayIntelCard('SYNTHESIZED INSIGHTS', list + `<button class="launch-bi-btn" style="margin-top: 8px;" onclick="openBIModal(); switchBITab('overview');">OPEN DOSSIER</button>`);
        } else if (data.action === 'bi_no_data') {
            displayIntelCard('BI ENGINE STANDBY', `<p style="color: var(--text-muted);">${data.display}</p>`);
        } else if (data.action === 'web_search' && data.url) {
            displayIntelCard('SEARCH MATRIX', `<p>Accessing online neural grid: <a href="${data.url}" target="_blank" style="color: var(--cyan);">${data.display}</a></p>`);
        } else if (data.action === 'catalogue_list') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('PRODUCT CATALOGUE', `
                <div class="source-badge">SOURCE: ${data.source || 'Product Catalogue'}</div>
                <p style="color: #fff; margin-bottom: 8px;">${escapeHtml(data.display)}</p>
                ${tableHtml}
                <div style="margin-top: 10px; display: flex; gap: 8px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">⚡ OPEN CATALOGUE MODAL</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'catalogue_low_stock' || data.action === 'catalogue_out_of_stock' || data.action === 'catalogue_no_price') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('INVENTORY AUDIT', `
                <div class="source-badge">SOURCE: ${data.source || 'Inventory Ledger'}</div>
                <p style="color: var(--gold); margin-bottom: 8px;">${escapeHtml(data.display)}</p>
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">MANAGE INVENTORY</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'catalogue_stock' || data.action === 'catalogue_price' || data.action === 'catalogue_selling_price' || data.action === 'catalogue_find' || data.action === 'catalogue_count' || data.action === 'cheapest_product' || data.action === 'expensive_product') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('CATALOGUE INTELLIGENCE', `
                <div class="source-badge">SOURCE: ${data.source || 'Product Catalogue'}</div>
                <h3 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display)}</h3>
                <p style="color: #fff; line-height: 1.4;">${escapeHtml(data.speak)}</p>
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">OPEN CATALOGUE</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'product_verify') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('CATALOGUE INTEGRITY AUDIT', `
                <div class="source-badge">SOURCE: ${data.source || 'Catalogue Audit'}</div>
                <h4 style="color: ${data.issues_count ? 'var(--gold)' : 'var(--cyan)'}; margin: 6px 0;">${escapeHtml(data.display)}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak)}</p>
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">REVIEW IN CATALOGUE</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'inventory_summary' || data.action === 'catalogue_lowest_stock') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('INVENTORY SUMMARY', `
                <div class="source-badge">SOURCE: ${data.source || 'Inventory Ledger'}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display)}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak)}</p>
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">OPEN INVENTORY</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'product_margin' || data.action === 'product_profit' || data.action === 'catalogue_margin') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            let metricsHtml = '';
            if (data.metrics) {
                metricsHtml = `
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin: 8px 0;">
                        <div style="background: rgba(0, 240, 255, 0.08); border: 1px solid rgba(0, 240, 255, 0.3); border-radius: 4px; padding: 6px 8px; text-align: center;">
                            <div style="font-size: 0.65rem; color: var(--text-muted);">SELLING PRICE</div>
                            <div style="font-size: 0.95rem; font-weight: bold; color: #fff;">₹${(data.metrics.selling_price || 0).toFixed(2)}</div>
                        </div>
                        <div style="background: rgba(0, 240, 255, 0.08); border: 1px solid rgba(0, 240, 255, 0.3); border-radius: 4px; padding: 6px 8px; text-align: center;">
                            <div style="font-size: 0.65rem; color: var(--text-muted);">COST PRICE</div>
                            <div style="font-size: 0.95rem; font-weight: bold; color: #fff;">₹${(data.metrics.purchase_price || 0).toFixed(2)}</div>
                        </div>
                        <div style="background: rgba(0, 255, 128, 0.08); border: 1px solid rgba(0, 255, 128, 0.3); border-radius: 4px; padding: 6px 8px; text-align: center;">
                            <div style="font-size: 0.65rem; color: var(--text-muted);">GROSS PROFIT</div>
                            <div style="font-size: 0.95rem; font-weight: bold; color: #00ff80;">₹${(data.metrics.gross_profit || 0).toFixed(2)}</div>
                        </div>
                        <div style="background: rgba(0, 255, 128, 0.12); border: 1px solid rgba(0, 255, 128, 0.4); border-radius: 4px; padding: 6px 8px; text-align: center;">
                            <div style="font-size: 0.65rem; color: var(--text-muted);">MARGIN %</div>
                            <div style="font-size: 0.95rem; font-weight: bold; color: #00ff80;">${data.metrics.gross_margin_pct}%</div>
                        </div>
                    </div>
                `;
            }
            displayIntelCard('PROFITABILITY MATRIX', `
                <div class="source-badge">SOURCE: ${data.source || 'Profitability Analysis'}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display)}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 6px;">${escapeHtml(data.speak)}</p>
                ${metricsHtml}
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">VIEW IN CATALOGUE</button>
                </div>
                ${followUps}
            `);

        } else if (data.action === 'supplier_lookup' || data.action === 'supplier_list') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('SUPPLIER LEDGER', `
                <div class="source-badge">SOURCE: ${data.source || 'Supplier Ledger'}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display)}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak)}</p>
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">OPEN CATALOGUE</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'dataset_summary' || data.action === 'dataset_dimensions' || data.action === 'dataset_columns' || data.action === 'dataset_missing_values' || data.action === 'dataset_duplicates' || data.action === 'dataset_head' || data.action === 'dataset_stats' || data.action === 'dataset_filter' || data.action === 'dataset_group' || data.action === 'dataset_dates') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('DATASET INTELLIGENCE', `
                <div class="source-badge">SOURCE: ${data.source || 'Active Dataset'}</div>
                <h4 style="color: var(--cyan); margin: 4px 0 8px 0;">${escapeHtml(data.display)}</h4>
                <p style="color: #fff; font-size: 0.9rem; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak)}</p>
                ${tableHtml}
                ${followUps}
            `);
        } else if (data.action === 'dataset_clarify') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('DISAMBIGUATION REQUIRED', `
                <div class="source-badge">SOURCE: ${data.source || 'Dataset Library'}</div>
                <p style="color: var(--gold); line-height: 1.4;">${escapeHtml(data.speak)}</p>
                <p style="color: var(--text-muted); font-size: 0.8rem;">Please specify which dataset you want to query:</p>
                ${followUps}
            `);
        } else if (data.action === 'dataset_no_data') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('DATASET STANDBY', `
                <div class="source-badge">SOURCE: Dataset Engine</div>
                <p style="color: var(--text-muted); line-height: 1.4;">${escapeHtml(data.speak)}</p>
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openSavedDataModal()">OPEN SAVED DATA LIBRARY</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'document_query' || data.action === 'document_no_evidence' || data.action === 'mixed_intelligence') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            let citationsHtml = '';
            if (data.citations && data.citations.length > 0) {
                citationsHtml = `
                    <div style="margin-top: 10px; padding: 8px 10px; background: rgba(0, 210, 255, 0.08); border-left: 3px solid var(--cyan); border-radius: 4px;">
                        <span style="font-size: 0.72rem; color: var(--cyan); font-weight: bold; text-transform: uppercase;">GROUNDED SOURCES & CITATIONS:</span>
                        <div style="display: flex; flex-direction: column; gap: 4px; margin-top: 6px;">
                            ${data.citations.map(c => `
                                <div style="font-size: 0.78rem; color: #fff;">
                                    <span class="bi-badge" style="background: rgba(0,255,170,0.15); color: #00ffaa; border: 1px solid #00ffaa; margin-right: 6px;">${escapeHtml(c.citation)}</span>
                                    <span style="color: var(--text-muted);">${escapeHtml(c.excerpt || '')}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;
            }
            displayIntelCard(data.action === 'mixed_intelligence' ? 'HYBRID INTELLIGENCE (DB + RAG)' : 'DOCUMENT INTELLIGENCE (RAG)', `
                <div class="source-badge">SOURCE: ${data.source || 'Document Intelligence'}</div>
                <div style="color: #fff; font-size: 0.92rem; line-height: 1.5; white-space: pre-wrap; margin: 8px 0;">${escapeHtml(data.display || data.speak)}</div>
                ${citationsHtml}
                ${followUps}
            `);
        } else if (data.action === 'assistant_help') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('TACTICAL ASSISTANT STANDBY', `
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak)}</p>
                <p style="color: var(--cyan); font-size: 0.85rem; margin-bottom: 6px;">Suggested tactical operations:</p>
                ${followUps}
            `);
        } else if (data.action === 'purchase_rate_history' || data.action === 'product_details') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('COMMERCIAL INTELLIGENCE', `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'Product Catalogue')}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display || '')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">OPEN CATALOGUE</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'purchase_list' || data.action === 'sales_list') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            let title = data.action === 'purchase_list' ? 'PROCUREMENT LEDGER' : 'SALES TRANSACTIONS';
            displayIntelCard(title, `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'Business Ledger')}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display || '')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">VIEW IN CATALOGUE</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'sales_comparison' || data.action === 'margin_rankings') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            let title = data.action === 'sales_comparison' ? 'SALES PERFORMANCE COMPARISON' : 'MARGIN & PROFITABILITY RANKINGS';
            displayIntelCard(title, `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'Commercial Intelligence')}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display || '')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">EXPLORE CATALOGUE</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'inventory_movements') {
            let tableHtml = renderTableHtml(data.table);
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('STOCK LEDGER & MOVEMENTS', `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'Stock Ledger')}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display || '')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                ${tableHtml}
                <div style="margin-top: 10px;">
                    <button class="launch-bi-btn" onclick="openCatalogueModal()">OPEN INVENTORY</button>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'out_of_scope') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('TACTICAL SCOPE ADVISORY', `
                <div class="source-badge">SOURCE: VANTIQ Core</div>
                <p style="color: var(--gold); line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.display || data.speak)}</p>
                ${followUps}
            `);
        } else if (data.action === 'clarify_query') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('DISAMBIGUATION REQUIRED', `
                <div class="source-badge">SOURCE: Clarification Engine</div>
                <p style="color: var(--gold); line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.display || data.speak)}</p>
                ${followUps}
            `);
        } else if (data.action === 'ai_service_offline') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('LOCAL AI SERVICE OFFLINE', `
                <div class="source-badge" style="color: #ef4444; border-color: rgba(239, 68, 68, 0.4);">STATUS: OFFLINE</div>
                <h4 style="color: #ef4444; margin: 6px 0;">${escapeHtml(data.display || 'Local AI Service Offline')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                <div class="llm-meta-tag" style="color: #ef4444;">
                    <span>⚠️ Ollama service is unreachable at 127.0.0.1:11434</span>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'ai_model_missing') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('LOCAL MODEL NOT INSTALLED', `
                <div class="source-badge" style="color: #f43f5e; border-color: rgba(244, 63, 94, 0.4);">STATUS: MODEL MISSING</div>
                <h4 style="color: #f43f5e; margin: 6px 0;">${escapeHtml(data.display || 'Model Missing')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                <div class="llm-meta-tag" style="color: #f43f5e;">
                    <span>⚠️ Configured model is not pulled in local Ollama</span>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'ai_timeout') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('LOCAL AI TIMEOUT', `
                <div class="source-badge" style="color: #fb923c; border-color: rgba(251, 146, 60, 0.4);">STATUS: INFERENCE TIMEOUT</div>
                <h4 style="color: #fb923c; margin: 6px 0;">${escapeHtml(data.display || 'Inference Timeout')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                <div class="llm-meta-tag" style="color: #fb923c;">
                    <span>⏱️ Model took longer than allowed timeout</span>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'clarification_needed') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('CLARIFICATION REQUIRED', `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'Clarification Engine')}</div>
                <h4 style="color: var(--gold); margin: 6px 0;">${escapeHtml(data.display || 'Clarification Needed')}</h4>
                <p style="color: #fff; font-size: 0.95rem; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                ${followUps}
            `);
        } else if (data.action === 'market_price_clarification') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('MARKET PRICE DIAGNOSTICS', `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'Catalogue & Market Diagnostics')}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display || '')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                <div class="llm-meta-tag" style="color: var(--gold); margin-top: 6px;">
                    <span>⚠️ External open-market pricing unverified • Internal records shown</span>
                </div>
                ${followUps}
            `);
        } else if (data.action === 'cancelled') {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard('OPERATION CANCELLED', `
                <div class="source-badge">SOURCE: Session Sentinel</div>
                <h4 style="color: var(--gold); margin: 6px 0;">${escapeHtml(data.display || 'Action Cancelled')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                ${followUps}
            `);
        } else {
            let followUps = renderFollowUpsHtml(data.follow_ups);
            displayIntelCard(data.source || 'VANTIQ INTELLIGENCE', `
                <div class="source-badge">SOURCE: ${escapeHtml(data.source || 'VANTIQ Core')}</div>
                <h4 style="color: var(--cyan); margin: 6px 0;">${escapeHtml(data.display || '')}</h4>
                <p style="color: #fff; line-height: 1.4; margin-bottom: 8px;">${escapeHtml(data.speak || '')}</p>
                ${followUps}
            `);
        }

    } catch (err) {
        logTerminal(`Command execution failed: ${err.message}`, 'system');
    } finally {
        isCommandExecuting = false;
        const sendBtn = document.getElementById('sendBtn');
        const input = document.getElementById('commandInput');
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.classList.remove('loading');
            sendBtn.textContent = 'EXECUTE';
        }
        if (input) {
            input.disabled = false;
        }
        document.getElementById('listenerStatus').textContent = isListening ? `LISTENING (${currentSpeechLang})...` : 'VOICE ENGINE READY';
    }
}

// Helper to render responsive intel tables
function renderTableHtml(table) {
    if (!table || !table.columns || !table.rows || table.rows.length === 0) return '';
    let ths = table.columns.map(c => `<th>${escapeHtml(c)}</th>`).join('');
    let trs = table.rows.map(r => {
        let tds = '';
        if (Array.isArray(r)) {
            tds = r.map(v => `<td>${escapeHtml(String(v ?? '--'))}</td>`).join('');
        } else if (typeof r === 'object') {
            tds = Object.values(r).map(v => `<td>${escapeHtml(String(v ?? '--'))}</td>`).join('');
        }
        return `<tr>${tds}</tr>`;
    }).join('');
    return `
        <div class="intel-table-wrapper">
            <table class="intel-table">
                <thead><tr>${ths}</tr></thead>
                <tbody>${trs}</tbody>
            </table>
        </div>
    `;
}

// Helper to render interactive follow-up chips
function renderFollowUpsHtml(chips) {
    if (!chips || chips.length === 0) return '';
    let buttons = chips.map(c => `<button type="button" class="intel-followup-chip" onclick="executeCommand('${escapeHtml(c)}')">💡 ${escapeHtml(c)}</button>`).join('');
    return `
        <div class="intel-followup-container">
            <span style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">SUGGESTIONS:</span>
            <div class="intel-followups">${buttons}</div>
        </div>
    `;
}

// Display Dynamic Card in Right Panel
function displayIntelCard(title, htmlContent) {
    const viewport = document.getElementById('intelViewport');
    viewport.innerHTML = `
        <div class="intel-card active-card">
            <h3 class="card-title">${title}</h3>
            <div class="card-body">${htmlContent}</div>
        </div>
    `;
}

// ==========================================
// BUSINESS SHORTCUT ACTION HANDLERS
// ==========================================

async function openBusinessInsights() {
    logTerminal('Accessing Business Intelligence & Analytics Dossier...', 'system');
    
    // 1. If in-memory report is already present, open BI modal directly
    if (currentBIReport) {
        renderBIDashboard(currentBIReport);
        document.getElementById('biModal').style.display = 'flex';
        const docName = currentBIReport.file_name || currentBIReport.dataset_name || 'Active Dataset';
        logTerminal(`[REPORT ENGINE] Intelligence dossier loaded for ${docName}.`, 'jarvis');
        vantiqSpeak(`Business intelligence dossier loaded for ${docName}.`);
        return;
    }

    // 2. Try fetching latest cached/generated report
    try {
        const res = await fetch('/api/generate-report');
        if (res.ok) {
            const data = await res.json();
            if (data.success && data.report) {
                currentBIReport = data.report;
                renderBIDashboard(currentBIReport);
                document.getElementById('biModal').style.display = 'flex';
                logTerminal(`[REPORT ENGINE] Loaded commercial intelligence report for ${data.report.file_name || 'dataset'}.`, 'jarvis');
                vantiqSpeak('Loaded commercial intelligence dossier.');
                return;
            }
        }
    } catch (err) {
        console.warn('Error fetching BI report:', err);
    }

    // 3. Check if saved datasets exist in SQLite to open report
    try {
        const dsRes = await fetch('/api/datasets?page_size=1');
        if (dsRes.ok) {
            const dsData = await dsRes.json();
            const items = dsData.items || dsData.datasets || [];
            if (items.length > 0) {
                await viewDatasetReport(items[0].id);
                return;
            }
        }
    } catch (err) {
        console.warn('Error querying datasets:', err);
    }

    // 4. Truthful fallback: No active dataset or report
    const html = `
        <div class="data-row"><span class="label">BI ENGINE:</span><span class="val cyan">STANDBY</span></div>
        <div class="data-row"><span class="label">DATASET:</span><span class="val amber">NO REPORT LOADED</span></div>
        <p style="color: var(--text-muted); font-size: 0.84rem; line-height: 1.4; margin-top: 8px;">
            Import an Excel spreadsheet or PDF document via the Business Data Import module below to generate executive KPI analytics, margin breakdowns, and data quality audits.
        </p>
        <button type="button" class="cat-btn-primary" style="margin-top: 10px; width: 100%;" onclick="document.getElementById('businessFileInput').click()">📁 SELECT FILE TO ANALYZE</button>
    `;
    displayIntelCard('BUSINESS INTELLIGENCE', html);
    logTerminal('[BI NOTICE] No active business report. Please import an Excel or PDF dataset.', 'system');
    vantiqSpeak('No business report is currently active. Please import a dataset to generate intelligence.');
}

async function openSuppliersPurchases() {
    logTerminal('Querying Supplier Directory & Procurement Ledger from SQLite...', 'system');
    try {
        const [supRes, movRes] = await Promise.all([
            fetch('/api/suppliers'),
            fetch('/api/inventory/movements?limit=15')
        ]);

        let suppliers = [];
        let movements = [];

        if (supRes.ok) {
            const supData = await supRes.json();
            suppliers = supData.suppliers || [];
        }
        if (movRes.ok) {
            const movData = await movRes.json();
            movements = movData.items || [];
        }

        const receipts = movements.filter(m => m.movement_type === 'receipt');

        let html = '';

        // Suppliers section
        html += `<div style="margin-bottom: 12px;">`;
        html += `<div class="data-row"><span class="label">REGISTERED SUPPLIERS:</span><span class="val cyan">${suppliers.length}</span></div>`;
        if (suppliers.length > 0) {
            html += `<div style="max-height: 130px; overflow-y: auto; margin-top: 6px; display: flex; flex-direction: column; gap: 4px;">`;
            suppliers.forEach(s => {
                const contact = s.contact_name ? ` (${escapeHtml(s.contact_name)})` : '';
                const phone = s.phone ? ` • ${escapeHtml(s.phone)}` : '';
                html += `<div style="padding: 5px 8px; background: rgba(0,240,255,0.04); border-left: 2px solid var(--cyan); font-size: 0.8rem;">
                    <span style="color: #fff; font-weight: 600;">${escapeHtml(s.name)}</span>${contact}
                    <div style="color: var(--text-muted); font-size: 0.74rem;">${s.email ? escapeHtml(s.email) : ''}${phone}</div>
                </div>`;
            });
            html += `</div>`;
        } else {
            html += `<p style="color: var(--text-muted); font-size: 0.8rem; margin: 4px 0;">No dedicated supplier profiles registered yet. Suppliers can be mapped during catalogue imports or assigned in product management.</p>`;
        }
        html += `</div>`;

        // Procurement movements section
        html += `<div style="border-top: 1px solid rgba(0,240,255,0.15); padding-top: 8px;">`;
        html += `<div class="data-row"><span class="label">STOCK RECEIPTS:</span><span class="val">${receipts.length} recorded</span></div>`;
        if (receipts.length > 0) {
            html += `<div style="max-height: 100px; overflow-y: auto; margin-top: 4px; display: flex; flex-direction: column; gap: 4px;">`;
            receipts.slice(0, 5).forEach(m => {
                const cost = m.unit_cost ? ` @ ₹${m.unit_cost}` : '';
                html += `<div style="font-size: 0.78rem; display: flex; justify-content: space-between; color: var(--text-muted);">
                    <span style="color: #fff;">${escapeHtml(m.product_name || 'Product #' + m.product_id)}</span>
                    <span style="color: #00ff88;">+${m.quantity_delta}${cost}</span>
                </div>`;
            });
            html += `</div>`;
        } else {
            html += `<p style="color: var(--text-muted); font-size: 0.8rem; margin: 4px 0;">No stock receipt entries recorded in inventory movements.</p>`;
        }
        html += `</div>`;

        html += `<button type="button" class="cat-btn-secondary" style="margin-top: 10px; width: 100%; font-size: 0.76rem;" onclick="openCatalogueModal()">📦 OPEN CATALOGUE & INVENTORY</button>`;

        displayIntelCard('SUPPLIERS & PURCHASES', html);
        const speakText = `Supplier and procurement ledger loaded. Found ${suppliers.length} registered suppliers and ${receipts.length} stock receipts.`;
        logTerminal(`[PROCUREMENT] Loaded ${suppliers.length} suppliers and ${receipts.length} stock receipts from database.`, 'jarvis');
        vantiqSpeak(speakText);
    } catch (err) {
        logTerminal('Failed to query suppliers database', 'system');
        displayIntelCard('SUPPLIERS & PURCHASES', `<p style="color: var(--red);">Unable to retrieve supplier data from SQLite.</p>`);
    }
}

async function showSystemStatus() {
    logTerminal('Scanning telemetry across system subsystems...', 'system');
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        const subs = data.subsystems || {};
        const apiSub = subs.api || {};
        const dbSub = subs.database || {};
        const llmSub = subs.local_llm || {};
        const ragSub = subs.rag || {};
        const voiceSub = subs.voice_engine || {};

        const statusColor = (st) => {
            const s = (st || '').toLowerCase();
            if (s === 'online' || s === 'ready' || s === 'connected') return '#00ff88';
            if (s === 'model_missing' || s === 'degraded' || s === 'warning') return '#ffaa00';
            return 'var(--red)';
        };

        const html = `
            <div class="data-row">
                <span class="label">OVERALL STATUS:</span>
                <span class="val" style="color: ${statusColor(data.status)}; font-weight: bold;">${data.status || 'OPERATIONAL'}</span>
            </div>
            <div class="data-row">
                <span class="label">API GATEWAY:</span>
                <span class="val" style="color: ${statusColor(apiSub.status)};">${(apiSub.status || 'ONLINE').toUpperCase()}</span>
            </div>
            <div class="data-row">
                <span class="label">SQLITE STORAGE:</span>
                <span class="val" style="color: ${statusColor(dbSub.status)};">${(dbSub.status || 'ONLINE').toUpperCase()} (${data.database?.latency_ms || 0}ms)</span>
            </div>
            <div class="data-row">
                <span class="label">LOCAL AI (OLLAMA):</span>
                <span class="val" style="color: ${statusColor(llmSub.status)};">${(llmSub.status || 'OFFLINE').toUpperCase()} (${llmSub.model || 'qwen3:4b-instruct'})</span>
            </div>
            <div class="data-row">
                <span class="label">DOCUMENT RAG:</span>
                <span class="val" style="color: ${statusColor(ragSub.status)};">${(ragSub.status || 'ONLINE').toUpperCase()} (${ragSub.total_documents || 0} docs, ${ragSub.total_chunks || 0} chunks)</span>
            </div>
            <div class="data-row">
                <span class="label">VOICE SYNTHESIS:</span>
                <span class="val" style="color: ${statusColor(voiceSub.status)};">${(voiceSub.status || 'READY').toUpperCase()}</span>
            </div>
            <div style="border-top: 1px solid rgba(0,240,255,0.15); margin-top: 8px; padding-top: 6px;">
                <div class="data-row"><span class="label">CPU USAGE:</span><span class="val">${data.cpu || 0}%</span></div>
                <div class="data-row"><span class="label">RAM USAGE:</span><span class="val">${data.ram || 0}%</span></div>
                <div class="data-row"><span class="label">CATALOGUE ITEMS:</span><span class="val cyan">${data.database?.active_products || 0} active</span></div>
            </div>
        `;
        displayIntelCard('SYSTEM SUBSYSTEM STATUS', html);

        const speakText = `System status is ${data.status}. API Gateway, SQLite database, Document RAG, and Voice Engine are operational.`;
        logTerminal(`[DIAGNOSTICS] Overall: ${data.status} | DB: ${data.database?.latency_ms}ms | LLM: ${llmSub.status}`, 'jarvis');
        vantiqSpeak(speakText);
    } catch (e) {
        logTerminal('Failed to read system status telemetry', 'system');
        displayIntelCard('SYSTEM STATUS', `<p style="color: var(--red);">System status telemetry unavailable.</p>`);
    }
}

async function openDocumentLibrary() {
    logTerminal('Synchronizing and opening Document & Dataset Library...', 'system');
    
    // 1. Refresh library datasets
    await loadSavedDatasets(1);

    // 2. Fetch RAG indexed documents status
    let ragDocs = [];
    try {
        const ragRes = await fetch('/api/rag/documents');
        if (ragRes.ok) {
            const ragData = await ragRes.json();
            ragDocs = ragData.documents || [];
        }
    } catch (e) {
        console.warn('Error fetching RAG docs:', e);
    }

    // 3. Scroll to Library module with highlight pulse
    const libBox = document.getElementById('libraryModuleBox');
    if (libBox) {
        libBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        libBox.style.boxShadow = '0 0 16px var(--cyan)';
        setTimeout(() => {
            libBox.style.boxShadow = '';
        }, 1500);
    }

    // 4. Render summary card in viewport
    let html = `
        <div class="data-row"><span class="label">SAVED DATASETS:</span><span class="val cyan" id="intelLibCount">Loading...</span></div>
        <div class="data-row"><span class="label">RAG INDEXED DOCS:</span><span class="val">${ragDocs.length}</span></div>
    `;

    if (ragDocs.length > 0) {
        html += `<div style="max-height: 120px; overflow-y: auto; margin-top: 6px; display: flex; flex-direction: column; gap: 4px;">`;
        ragDocs.forEach(d => {
            html += `<div style="padding: 4px 6px; background: rgba(0,240,255,0.04); border-left: 2px solid var(--cyan); font-size: 0.8rem; display: flex; justify-content: space-between;">
                <span style="color: #fff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px;">${escapeHtml(d.original_filename)}</span>
                <span style="color: var(--cyan); font-size: 0.74rem;">${d.chunk_count || 0} chunks</span>
            </div>`;
        });
        html += `</div>`;
    }

    html += `<p style="color: var(--text-muted); font-size: 0.78rem; margin-top: 8px;">
        Use the Saved Data Library below to search datasets, view BI reports, or re-index documents for local RAG intelligence.
    </p>`;

    displayIntelCard('DOCUMENT & DATASET LIBRARY', html);

    // Update count once library renders
    const badge = document.getElementById('libraryCountBadge');
    const intelCount = document.getElementById('intelLibCount');
    if (badge && intelCount) {
        intelCount.textContent = badge.textContent || '0';
    }

    logTerminal(`[DOCUMENT LIBRARY] Loaded saved datasets and ${ragDocs.length} indexed RAG documents.`, 'jarvis');
    vantiqSpeak('Document and dataset library loaded.');
}

window.openBusinessInsights = openBusinessInsights;
window.openSuppliersPurchases = openSuppliersPurchases;
window.showSystemStatus = showSystemStatus;
window.openDocumentLibrary = openDocumentLibrary;

// Quick Actions
async function requestJoke() {
    logTerminal('Requesting programming joke protocol...', 'system');
    try {
        const res = await fetch('/api/joke');
        const data = await res.json();
        logTerminal(data.joke, 'jarvis');
        jarvisSpeak(data.joke);
        displayIntelCard('STARK HUMOR ARCHIVE', `<p style="font-size: 1.05rem; color: #fff; line-height: 1.5;">"${data.joke}"</p>`);
    } catch (e) {
        logTerminal('Failed to load joke protocol', 'system');
    }
}

async function requestNews() {
    logTerminal('Downloading top tech intelligence headlines...', 'system');
    try {
        const res = await fetch('/api/news');
        const data = await res.json();
        let listHtml = '<ul style="list-style: none; display: flex; flex-direction: column; gap: 8px;">';
        data.articles.forEach(art => {
            listHtml += `<li><a href="${art.url}" target="_blank" style="color: var(--cyan); text-decoration: none; font-size: 0.88rem;">⚡ ${art.title}</a></li>`;
        });
        listHtml += '</ul>';
        displayIntelCard('LIVE TECH INTEL', listHtml);
        logTerminal('Loaded latest headlines into tactical intel viewport.', 'jarvis');
        jarvisSpeak('Top intelligence headlines loaded on your dashboard.');
    } catch (e) {
        logTerminal('News retrieval offline', 'system');
    }
}

async function requestCovid(stateName = 'Delhi') {
    logTerminal(`Checking health & COVID-19 statistics for ${stateName}...`, 'system');
    try {
        const res = await fetch(`/api/covid?state=${encodeURIComponent(stateName)}`);
        const data = await res.json();
        
        const html = `
            <div class="data-row"><span class="label">REGION:</span><span class="val cyan">${data.state}</span></div>
            <div class="data-row"><span class="label">ACTIVE CASES:</span><span class="val">${data.active}</span></div>
            <div class="data-row"><span class="label">TOTAL CASES:</span><span class="val">${data.total}</span></div>
            <div class="data-row"><span class="label">RECOVERIES:</span><span class="val" style="color: #00ff88;">${data.cured}</span></div>
            <div class="data-row"><span class="label">STATUS:</span><span class="val">${data.note || 'Regional database synchronized.'}</span></div>
        `;
        displayIntelCard('REGIONAL HEALTH METRICS', html);
        const speakText = `In ${data.state}, active cases are ${data.active}. System status stable.`;
        logTerminal(speakText, 'jarvis');
        jarvisSpeak(speakText);
    } catch (e) {
        logTerminal('Health statistics feed unavailable', 'system');
    }
}

async function requestContacts() {
    logTerminal('Reading communications directory from Contacts.txt...', 'system');
    try {
        const res = await fetch('/api/contacts');
        const data = await res.json();
        let html = `<p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 8px;">TOTAL CONTACTS STORED: ${data.total}</p>`;
        html += '<div style="max-height: 180px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px;">';
        data.contacts.forEach(c => {
            html += `<div class="data-row"><span class="label">${c.name.toUpperCase()}:</span><span class="val cyan">${c.phone}</span></div>`;
        });
        html += '</div>';
        displayIntelCard('COMMUNICATIONS DIRECTORY', html);
        logTerminal(`Loaded ${data.total} contacts from database.`, 'jarvis');
        jarvisSpeak(`Communications directory loaded. Found ${data.total} contacts.`);
    } catch (e) {
        logTerminal('Failed to read contacts database', 'system');
    }
}

// ==========================================
// BUSINESS DATA IMPORT MODULE CONTROLLER
// ==========================================

let currentImportFile = null;
let isImportingData = false;
let lastExtractionResult = null;

function initDataImportModule() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('businessFileInput');

    if (!dropZone || !fileInput) return;

    // Dropzone click -> trigger file input
    dropZone.addEventListener('click', () => {
        if (!isImportingData) {
            fileInput.click();
        }
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileSelection(e.target.files[0]);
        }
    });

    // Drag & drop events
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (!isImportingData) {
                dropZone.classList.add('dragover');
            }
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('dragover');
        });
    });

    dropZone.addEventListener('drop', (e) => {
        if (isImportingData) return;
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length > 0) {
            handleFileSelection(dt.files[0]);
        }
    });
}

function handleFileSelection(file) {
    if (!file) return;

    const allowedExtensions = ['xlsx', 'xls', 'pdf'];
    const parts = file.name.split('.');
    const ext = parts.length > 1 ? parts.pop().toLowerCase() : '';

    hideImportError();

    // Client-side extension validation
    if (!allowedExtensions.includes(ext)) {
        showImportError(`Unsupported file format '.${ext || 'unknown'}'. Please select an XLSX, XLS, or PDF file.`);
        return;
    }

    // Client-side size validation (10 MB limit)
    const maxBytes = 10 * 1024 * 1024;
    if (file.size > maxBytes) {
        showImportError(`File size (${(file.size / (1024 * 1024)).toFixed(2)} MB) exceeds the 10 MB maximum limit.`);
        return;
    }

    currentImportFile = file;

    // Update UI elements
    document.getElementById('selectedFileName').textContent = file.name;
    document.getElementById('selectedFileSize').textContent = formatFileSize(file.size);
    document.getElementById('selectedFileStatus').textContent = 'Ready to import';

    // File type icon
    const iconElem = document.getElementById('fileTypeIcon');
    if (ext === 'pdf') {
        iconElem.textContent = '📕';
    } else {
        iconElem.textContent = '📊';
    }

    // Toggle view states
    document.getElementById('dropZone').style.display = 'none';
    document.getElementById('selectedFileCard').style.display = 'flex';
    document.getElementById('cancelBtn').style.display = 'inline-block';
    document.getElementById('importBtn').disabled = false;
    document.getElementById('importResultViewport').style.display = 'none';

    logTerminal(`File staged for import: ${file.name} (${formatFileSize(file.size)})`, 'system');
}

function cancelFileSelection() {
    if (isImportingData) return;

    currentImportFile = null;
    const fileInput = document.getElementById('businessFileInput');
    if (fileInput) fileInput.value = '';

    document.getElementById('dropZone').style.display = 'block';
    document.getElementById('selectedFileCard').style.display = 'none';
    document.getElementById('cancelBtn').style.display = 'none';
    document.getElementById('importBtn').disabled = true;
    document.getElementById('importProcessing').style.display = 'none';
    hideImportError();
}

async function submitDataImport() {
    if (!currentImportFile || isImportingData) return;

    isImportingData = true;
    hideImportError();

    const importBtn = document.getElementById('importBtn');
    const cancelBtn = document.getElementById('cancelBtn');
    const processingElem = document.getElementById('importProcessing');
    const statusElem = document.getElementById('selectedFileStatus');

    importBtn.disabled = true;
    cancelBtn.disabled = true;
    processingElem.style.display = 'flex';
    statusElem.textContent = 'Processing extraction...';

    logTerminal(`Transmitting ${currentImportFile.name} to Tactical Import Engine...`, 'system');

    const formData = new FormData();
    formData.append('file', currentImportFile);

    try {
        const response = await fetch('/api/data-import', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            const errorMsg = data.error || 'Failed to process file.';
            showImportError(errorMsg);
            statusElem.textContent = 'Extraction failed';
            logTerminal(`[ERROR] Data import failed: ${errorMsg}`, 'system');
            jarvisSpeak('Data import failed. Check terminal error log.');
        } else {
            statusElem.textContent = 'Import complete';
            if (data.dataset_id) {
                activeDatasetId = data.dataset_id;
            }
            renderImportResult(data);
            if (data.is_duplicate) {
                logTerminal(`Identical file recognized in database (${data.dataset_id}). Loaded existing dataset.`, 'jarvis');
                jarvisSpeak('Existing dataset recognized and loaded from database.');
            } else {
                logTerminal(`Extraction successful for ${data.file_name} (Saved ID: ${data.dataset_id}).`, 'jarvis');
                jarvisSpeak('Business data successfully extracted and persisted to database.');
            }
            loadSavedDatasets(1);
        }
    } catch (err) {
        showImportError(`Network or server error during upload: ${err.message}`);
        statusElem.textContent = 'Upload error';
        logTerminal(`[ERROR] Transmission error: ${err.message}`, 'system');
    } finally {
        isImportingData = false;
        processingElem.style.display = 'none';
        importBtn.disabled = false;
        cancelBtn.disabled = false;
    }
}

function renderImportResult(data) {
    lastExtractionResult = data;
    if (data.report) {
        currentBIReport = data.report;
    }
    const resultViewport = document.getElementById('importResultViewport');
    const summaryBar = document.getElementById('resultSummaryBar');
    const sheetsTabs = document.getElementById('resultSheetsTabs');
    const previewContent = document.getElementById('resultPreviewContent');

    resultViewport.style.display = 'flex';

    if (data.file_type === 'xlsx' || data.file_type === 'xls') {
        const s = data.summary;
        summaryBar.innerHTML = `
            <div class="summary-metric">SHEETS: <span class="metric-val">${s.sheet_count}</span></div>
            <span class="meta-dot">•</span>
            <div class="summary-metric">TOTAL ROWS: <span class="metric-val">${s.total_rows}</span></div>
            <span class="meta-dot">•</span>
            <div class="summary-metric">COLUMNS: <span class="metric-val">${s.total_columns}</span></div>
        `;

        // Render sheet selector tabs
        if (data.sheets && data.sheets.length > 0) {
            sheetsTabs.style.display = data.sheets.length > 1 ? 'flex' : 'none';
            sheetsTabs.innerHTML = '';
            data.sheets.forEach((sheet, idx) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = `sheet-tab-btn ${idx === 0 ? 'active' : ''}`;
                btn.textContent = `${sheet.sheet_name} (${sheet.row_count})`;
                btn.onclick = () => renderExcelSheetPreview(idx);
                sheetsTabs.appendChild(btn);
            });

            // Render first sheet by default
            renderExcelSheetPreview(0);
        } else {
            sheetsTabs.style.display = 'none';
            previewContent.innerHTML = '<p style="color: var(--text-muted); padding: 8px;">No sheet rows found.</p>';
        }

        // Also update Main Intel Deck Viewport
        displayIntelCard(
            `EXCEL MATRIX: ${data.file_name}`,
            `<p style="color: var(--cyan); margin-bottom: 6px;">Sheets: ${s.sheet_count} | Total Rows: ${s.total_rows}</p>
             <p style="font-size: 0.8rem; color: var(--text-muted);">${data.message}</p>`
        );

    } else if (data.file_type === 'pdf') {
        const s = data.summary;
        sheetsTabs.style.display = 'none';
        summaryBar.innerHTML = `
            <div class="summary-metric">PAGES: <span class="metric-val">${s.page_count}</span></div>
            <span class="meta-dot">•</span>
            <div class="summary-metric">CHARS: <span class="metric-val">${s.char_count}</span></div>
            <span class="meta-dot">•</span>
            <div class="summary-metric">READABLE: <span class="metric-val">${s.has_text ? 'YES' : 'NO'}</span></div>
        `;

        if (s.has_text && data.text_preview) {
            previewContent.innerHTML = `
                <div class="pdf-text-preview">${escapeHtml(data.text_preview)}</div>
            `;
        } else {
            previewContent.innerHTML = `
                <div class="import-error-banner" style="margin: 4px 0;">
                    <span class="error-icon">ℹ️</span>
                    <span class="error-text">${escapeHtml(data.message)}</span>
                </div>
            `;
        }

        // Also update Main Intel Deck Viewport
        displayIntelCard(
            `PDF INTEL: ${data.file_name}`,
            `<p style="color: var(--cyan); margin-bottom: 6px;">Pages: ${s.page_count} | Extracted Characters: ${s.char_count}</p>
             <p style="font-size: 0.8rem; color: var(--text-muted);">${data.message}</p>`
        );
    }
}

function renderExcelSheetPreview(sheetIdx) {
    if (!lastExtractionResult || !lastExtractionResult.sheets) return;
    const sheet = lastExtractionResult.sheets[sheetIdx];
    if (!sheet) return;

    // Update active tab styles
    const tabBtns = document.querySelectorAll('.sheet-tab-btn');
    tabBtns.forEach((btn, idx) => {
        btn.classList.toggle('active', idx === sheetIdx);
    });

    const previewContent = document.getElementById('resultPreviewContent');

    if (!sheet.preview_rows || sheet.preview_rows.length === 0) {
        previewContent.innerHTML = `<p style="color: var(--text-muted); padding: 8px;">Sheet '${sheet.sheet_name}' is empty.</p>`;
        return;
    }

    let tableHtml = '<table class="data-preview-table"><thead><tr>';
    sheet.columns.forEach(col => {
        tableHtml += `<th>${escapeHtml(col)}</th>`;
    });
    tableHtml += '</tr></thead><tbody>';

    sheet.preview_rows.forEach(row => {
        tableHtml += '<tr>';
        sheet.columns.forEach(col => {
            const val = row[col];
            if (val === null || val === undefined) {
                tableHtml += '<td class="cell-null">null</td>';
            } else {
                tableHtml += `<td>${escapeHtml(String(val))}</td>`;
            }
        });
        tableHtml += '</tr>';
    });

    tableHtml += '</tbody></table>';
    previewContent.innerHTML = tableHtml;
}

function closeImportPreview() {
    document.getElementById('importResultViewport').style.display = 'none';
}

function showImportError(msg) {
    const errorBanner = document.getElementById('importErrorBanner');
    const errorText = document.getElementById('importErrorText');
    errorText.textContent = msg;
    errorBanner.style.display = 'flex';
}

function hideImportError() {
    const errorBanner = document.getElementById('importErrorBanner');
    if (errorBanner) errorBanner.style.display = 'none';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/* ========================================================
   BUSINESS INTELLIGENCE DOSSIER CONTROLLER
   ======================================================== */

async function launchReport() {
    logTerminal('Initiating Intelligence Dossier Generation Protocol...', 'system');
    const launchBtn = document.getElementById('launchReportBtn') || document.getElementById('launchBIBtn');
    if (launchBtn) {
        launchBtn.classList.add('loading');
        launchBtn.innerHTML = '⚡ ANALYZING...';
    }

    try {
        const res = await fetch('/api/generate-report', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            if (data.success && data.report) {
                currentBIReport = data.report;
            }
        } else if (!currentBIReport) {
            const getRes = await fetch('/api/generate-report');
            if (getRes.ok) {
                const data = await getRes.json();
                if (data.success && data.report) {
                    currentBIReport = data.report;
                }
            }
        }
    } catch (err) {
        console.warn('Error fetching generated report:', err);
    } finally {
        if (launchBtn) {
            launchBtn.classList.remove('loading');
            launchBtn.innerHTML = '⚡ LAUNCH REPORT';
        }
    }

    if (!currentBIReport) {
        logTerminal('[SYSTEM NOTICE] No document currently imported. Please select and import an Excel or PDF file first.', 'system');
        jarvisSpeak('No document is currently imported, Boss. Please import an Excel or PDF file first.');
        return;
    }

    renderBIDashboard(currentBIReport);
    document.getElementById('biModal').style.display = 'flex';
    logTerminal(`[REPORT ENGINE] Intelligence report launched for ${currentBIReport.file_name || 'dataset'}.`, 'jarvis');
    jarvisSpeak(`Intelligence dossier loaded for ${currentBIReport.file_name || 'your dataset'}.`);
}

// Backwards-compatible alias
const openBIModal = launchReport;
window.launchReport = launchReport;
window.openBIModal = launchReport;

function closeBIModal() {
    const modal = document.getElementById('biModal');
    if (modal) modal.style.display = 'none';
}

function switchBITab(tabName) {
    activeBITab = tabName;
    const tabBtns = document.querySelectorAll('.bi-tab-btn');
    tabBtns.forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tabName);
    });

    const panes = document.querySelectorAll('.bi-tab-pane');
    panes.forEach(pane => {
        pane.classList.toggle('active', pane.getAttribute('id') === `biPane_${tabName}`);
    });

    if (tabName === 'history' && activeDatasetId) {
        loadModalHistoryRuns(activeDatasetId);
    }
}

function exportCurrentReport(format) {
    if (!currentBIReport) return;
    logTerminal(`[REPORT EXPORT] Initiating ${format.toUpperCase()} export stream...`, 'system');
    jarvisSpeak(`Exporting intelligence dossier in ${format.toUpperCase()} format.`);
    window.location.href = `/api/export-report?format=${format}`;
}

function renderBIDashboard(report) {
    // 1. Header Information
    document.getElementById('biDocTitle').textContent = `DOSSIER: ${report.file_name || 'CLASSIFIED_DATASET'}`;
    const badge = document.getElementById('biClassificationBadge');
    const detectedType = report.classification ? report.classification.detected_type : 'GENERAL TABULAR';
    badge.textContent = detectedType.toUpperCase();

    const tsElem = document.getElementById('biDocTimestamp');
    if (report.timestamp) {
        tsElem.textContent = `GENERATED: ${report.timestamp}`;
    }

    // 2. Top KPI Grid
    const kpiGrid = document.getElementById('biKpiGrid');
    kpiGrid.innerHTML = '';

    const summary = report.dataset_summary || {};
    const dq = report.data_quality || {};
    const pricing = report.pricing || {};
    const inv = report.inventory || {};
    const sales = report.sales || {};

    // Standard KPIs
    if (report.file_type === 'pdf') {
        addKpiCard(kpiGrid, 'PAGES ANALYZED', summary.page_count || 1);
        addKpiCard(kpiGrid, 'CHARACTERS', (summary.char_count || 0).toLocaleString());
        addKpiCard(kpiGrid, 'READABLE TEXT', summary.has_text ? 'VERIFIED' : 'SCANNED/OCR REQ', summary.has_text ? 'green' : 'red');
    } else {
        addKpiCard(kpiGrid, 'RECORDS ANALYZED', (summary.total_rows || 0).toLocaleString());
        addKpiCard(kpiGrid, 'COLUMNS DETECTED', summary.total_columns || 0);

        const qScore = dq.score !== undefined ? `${dq.score}%` : 'N/A';
        const qColor = dq.score >= 80 ? 'green' : (dq.score >= 60 ? 'gold' : 'red');
        addKpiCard(kpiGrid, 'QUALITY SCORE', qScore, qColor);

        addKpiCard(kpiGrid, 'MISSING VALUES', dq.missing_cells_count || 0, dq.missing_cells_count > 0 ? 'gold' : 'green');
        addKpiCard(kpiGrid, 'DUPLICATES', dq.duplicate_rows_count || 0, dq.duplicate_rows_count > 0 ? 'red' : 'green');
    }

    // Conditional Business KPIs
    if (pricing.computed) {
        addKpiCard(kpiGrid, 'AVG GROSS MARGIN', `${pricing.average_gross_margin_pct}%`, 'cyan');
    }
    if (inv.computed) {
        addKpiCard(kpiGrid, 'STOCK UNITS', (inv.total_units_in_stock || 0).toLocaleString(), 'cyan');
        if (inv.low_stock_count > 0) {
            addKpiCard(kpiGrid, 'LOW STOCK ALERT', inv.low_stock_count, 'red');
        }
    }
    if (sales.computed) {
        addKpiCard(kpiGrid, 'TOTAL REVENUE', `$${(sales.total_revenue || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`, 'green');
    }

    // 3. Render Tab Panes
    const container = document.getElementById('biTabContentArea');
    container.innerHTML = `
        <!-- PANE: OVERVIEW & INSIGHTS -->
        <div class="bi-tab-pane ${activeBITab === 'overview' ? 'active' : ''}" id="biPane_overview">
            ${renderOverviewPane(report)}
        </div>

        <!-- PANE: DATA QUALITY -->
        <div class="bi-tab-pane ${activeBITab === 'quality' ? 'active' : ''}" id="biPane_quality">
            ${renderQualityPane(report)}
        </div>

        <!-- PANE: STATISTICAL ANALYSIS -->
        <div class="bi-tab-pane ${activeBITab === 'stats' ? 'active' : ''}" id="biPane_stats">
            ${renderStatsPane(report)}
        </div>

        <!-- PANE: PRICING & MARGINS -->
        <div class="bi-tab-pane ${activeBITab === 'pricing' ? 'active' : ''}" id="biPane_pricing">
            ${renderPricingPane(report)}
        </div>

        <!-- PANE: INVENTORY -->
        <div class="bi-tab-pane ${activeBITab === 'inventory' ? 'active' : ''}" id="biPane_inventory">
            ${renderInventoryPane(report)}
        </div>

        <!-- PANE: SALES -->
        <div class="bi-tab-pane ${activeBITab === 'sales' ? 'active' : ''}" id="biPane_sales">
            ${renderSalesPane(report)}
        </div>

        <!-- PANE: SUPPLIERS -->
        <div class="bi-tab-pane ${activeBITab === 'suppliers' ? 'active' : ''}" id="biPane_suppliers">
            ${renderSuppliersPane(report)}
        </div>

        <!-- PANE: RAW PREVIEW -->
        <div class="bi-tab-pane ${activeBITab === 'raw' ? 'active' : ''}" id="biPane_raw">
            ${renderRawPreviewPane(report)}
        </div>

        <!-- PANE: ANALYSIS RUNS HISTORY -->
        <div class="bi-tab-pane ${activeBITab === 'history' ? 'active' : ''}" id="biPane_history">
            ${renderHistoryPane(report)}
        </div>
    `;
}

function addKpiCard(container, label, value, colorClass = '') {
    const card = document.createElement('div');
    card.className = `bi-kpi-card ${colorClass}`;
    card.innerHTML = `
        <span class="bi-kpi-label">${escapeHtml(label)}</span>
        <span class="bi-kpi-value">${escapeHtml(String(value))}</span>
    `;
    container.appendChild(card);
}

/* ========================================================
   TAB PANE RENDERERS
   ======================================================== */

function renderOverviewPane(report) {
    const insights = report.insights || [];
    const profiles = report.column_profiles || [];
    const summary = report.dataset_summary || {};
    const cls = report.classification || {};
    const rIntel = report.resume_intelligence || {};
    const unavail = report.unavailable_metrics || [];

    let insightsHtml = '';
    if (insights.length === 0) {
        insightsHtml = '<div class="bi-notice-box">No critical anomalies or specific findings triggered for this document.</div>';
    } else {
        insightsHtml = '<div class="bi-insights-feed">';
        insights.forEach(ins => {
            const sevClass = (ins.severity || 'info').toLowerCase();
            insightsHtml += `
                <div class="bi-insight-card">
                    <div class="bi-insight-header">
                        <span class="bi-insight-title">${escapeHtml(ins.title)}</span>
                        <span class="severity-badge ${sevClass}">${escapeHtml(ins.severity)}</span>
                    </div>
                    <div class="bi-insight-desc">${escapeHtml(ins.explanation)}</div>
                    <div class="bi-insight-footer">
                        <span>METRIC: <strong style="color: var(--cyan);">${escapeHtml(String(ins.underlying_metric || 'N/A'))}</strong></span>
                        <span>FIELDS: ${escapeHtml((ins.fields_used || []).join(', ') || 'N/A')}</span>
                    </div>
                </div>
            `;
        });
        insightsHtml += '</div>';
    }

    let resumeCardHtml = '';
    if (rIntel.is_resume) {
        const cInfo = rIntel.contact_info || {};
        const secs = rIntel.detected_sections || {};
        resumeCardHtml = `
            <div class="bi-section-card">
                <div class="bi-section-header">
                    <span class="bi-section-title" style="color: var(--cyan);">RÉSUMÉ DOSSIER INTELLIGENCE</span>
                    <span class="bi-section-subtitle">Verified Candidate Curriculum Vitae</span>
                </div>
                <p style="color: #c5e3f6; font-size: 0.88rem; line-height: 1.5; margin-bottom: 12px;">
                    ${escapeHtml(rIntel.document_summary || '')}
                </p>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 14px;">
                    <div style="background: rgba(0,240,255,0.05); padding: 8px 12px; border-radius: 4px;">
                        <div style="font-size: 0.72rem; color: var(--text-muted);">EMAILS:</div>
                        <div style="color: var(--cyan); font-size: 0.82rem; font-weight: bold;">${escapeHtml((cInfo.emails || []).join(', ') || 'None detected')}</div>
                    </div>
                    <div style="background: rgba(0,240,255,0.05); padding: 8px 12px; border-radius: 4px;">
                        <div style="font-size: 0.72rem; color: var(--text-muted);">PHONES:</div>
                        <div style="color: var(--cyan); font-size: 0.82rem; font-weight: bold;">${escapeHtml((cInfo.phones || []).join(', ') || 'None detected')}</div>
                    </div>
                    <div style="background: rgba(0,240,255,0.05); padding: 8px 12px; border-radius: 4px;">
                        <div style="font-size: 0.72rem; color: var(--text-muted);">PROFILES / LINKS:</div>
                        <div style="color: var(--cyan); font-size: 0.82rem; font-weight: bold;">${escapeHtml((cInfo.links || []).join(', ') || 'None detected')}</div>
                    </div>
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <div style="font-size: 0.8rem; color: var(--text-muted); font-weight: bold;">IDENTIFIED PROFILE SECTIONS:</div>
                    ${Object.entries(secs).map(([sName, sVal]) => `
                        <div style="background: rgba(0,240,255,0.03); border-left: 2px solid var(--cyan); padding: 6px 10px;">
                            <strong style="color: #fff; font-size: 0.82rem;">${escapeHtml(sName)}:</strong>
                            <span style="color: #a0c4df; font-size: 0.78rem; margin-left: 6px;">${escapeHtml(sVal.summary || '')}</span>
                        </div>
                    `).join('')}
                </div>
                <div style="margin-top: 14px; font-size: 0.75rem; color: var(--text-muted);">
                    <strong>EXTRACTION LIMITATIONS:</strong>
                    <ul style="margin: 4px 0 0 0; padding-left: 18px;">
                        ${(rIntel.extraction_limitations || []).map(l => `<li>${escapeHtml(l)}</li>`).join('')}
                    </ul>
                </div>
            </div>
        `;
    }

    let colProfilesHtml = '';
    if (profiles.length > 0) {
        colProfilesHtml = `
            <div class="bi-section-card">
                <div class="bi-section-header">
                    <span class="bi-section-title">COLUMN SCHEMA & DATA PROFILES</span>
                    <span class="bi-section-subtitle">${profiles.length} detected columns</span>
                </div>
                <div style="overflow-x: auto;">
                    <table class="data-preview-table">
                        <thead>
                            <tr>
                                <th>COLUMN NAME</th>
                                <th>INFERRED TYPE</th>
                                <th>VALID COUNT</th>
                                <th>NULL COUNT</th>
                                <th>NULL %</th>
                                <th>DISTINCT</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${profiles.map(p => `
                                <tr>
                                    <td><strong>${escapeHtml(p.column)}</strong></td>
                                    <td><span class="bi-badge" style="font-size: 0.6rem;">${escapeHtml(p.inferred_type)}</span></td>
                                    <td>${p.non_null_count}</td>
                                    <td>${p.null_count}</td>
                                    <td style="color: ${p.null_pct > 10 ? 'var(--gold)' : 'inherit'};">${p.null_pct}%</td>
                                    <td>${p.distinct_count}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    return `
        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">EXECUTIVE EVIDENCE-BASED INSIGHTS</span>
                <span class="bi-section-subtitle">${insights.length} Synthesized Findings</span>
            </div>
            ${insightsHtml}
        </div>

        ${resumeCardHtml}

        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">DATASET OVERVIEW & TELEMETRY</span>
                <span class="bi-section-subtitle">${escapeHtml(report.file_name)}</span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; font-size: 0.78rem;">
                <div><span style="color: var(--text-muted);">CLASSIFICATION:</span> <strong>${escapeHtml(cls.detected_type || 'General Tabular')}</strong></div>
                <div><span style="color: var(--text-muted);">CONFIDENCE:</span> <strong>${escapeHtml(cls.confidence || 'Medium')}</strong></div>
                <div><span style="color: var(--text-muted);">FILE TYPE:</span> <strong>${escapeHtml(report.file_type || '').toUpperCase()}</strong></div>
                <div><span style="color: var(--text-muted);">DATE RANGES:</span> <strong>${escapeHtml((report.date_ranges || []).join(' → ') || 'No Date Columns Detected')}</strong></div>
            </div>
        </div>

        ${colProfilesHtml}
        ${renderUnavailableMetricsSection(unavail)}
    `;
}

function renderQualityPane(report) {
    const dq = report.data_quality || {};
    const issues = dq.issues || [];
    const score = dq.score !== undefined ? dq.score : 100;
    const scoreColor = score >= 80 ? '#00ffaa' : (score >= 60 ? '#ffaa00' : '#ff3344');

    // Circumference calculation for 36 radius circle: 2 * pi * 36 ~= 226
    const circ = 226;
    const offset = circ - (circ * score) / 100;

    let issuesRows = '';
    if (issues.length === 0) {
        issuesRows = '<tr><td colspan="6" style="text-align: center; color: #00ffaa; padding: 14px;">✅ No data quality violations detected. Dataset is fully intact.</td></tr>';
    } else {
        issuesRows = issues.map(iss => {
            const sevClass = (iss.severity || 'info').toLowerCase();
            return `
                <tr>
                    <td><span class="severity-badge ${sevClass}">${escapeHtml(iss.severity)}</span></td>
                    <td><strong>${escapeHtml(iss.column)}</strong></td>
                    <td>${iss.affected_records}</td>
                    <td>${escapeHtml((iss.example_rows || []).slice(0, 5).join(', ') || '-')}</td>
                    <td>${escapeHtml(iss.message)}</td>
                    <td style="color: var(--cyan);">${escapeHtml(iss.suggested_correction)}</td>
                </tr>
            `;
        }).join('');
    }

    return `
        <div class="quality-meter-box">
            <div class="quality-circle-container">
                <svg class="quality-circle-svg" viewBox="0 0 80 80" width="80" height="80">
                    <circle class="quality-circle-bg" cx="40" cy="40" r="34" fill="none"></circle>
                    <circle class="quality-circle-bar" cx="40" cy="40" r="34" fill="none" style="stroke: ${scoreColor}; stroke-dasharray: ${circ}; stroke-dashoffset: ${offset};"></circle>
                </svg>
                <span class="quality-circle-text">${score}%</span>
            </div>
            <div>
                <h3 style="font-family: var(--font-display); font-size: 0.95rem; color: #fff;">TACTICAL DATA QUALITY INDEX</h3>
                <p style="font-size: 0.74rem; color: var(--text-muted); margin-top: 4px;">
                    Deterministic scoring model: Starts at 100%, deducting points for missing required identifiers, duplicate records, negative prices, and inverted margins.
                </p>
                <div style="font-size: 0.72rem; color: var(--cyan); margin-top: 6px;">
                    Duplicate Rows: ${dq.duplicate_rows_count || 0} | Missing Cells: ${dq.missing_cells_count || 0}
                </div>
            </div>
        </div>

        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">AUDIT ISSUES & ANOMALIES FEED</span>
                <span class="bi-section-subtitle">${issues.length} flagged issues</span>
            </div>
            <div style="overflow-x: auto;">
                <table class="bi-issues-table">
                    <thead>
                        <tr>
                            <th>SEVERITY</th>
                            <th>COLUMN</th>
                            <th>AFFECTED</th>
                            <th>EXAMPLE ROWS</th>
                            <th>EXPLANATION</th>
                            <th>SUGGESTED CORRECTION</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${issuesRows}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderStatsPane(report) {
    const stats = report.statistics || {};
    const corrs = stats.correlations || {};
    const cats = stats.categorical_distributions || {};
    const numStats = stats.numeric_descriptive || [];
    const unavail = report.unavailable_metrics || [];

    if (!stats.available && (!numStats || numStats.length === 0)) {
        return `
            <div class="bi-notice-box" style="margin-bottom: 16px;">
                ℹ️ Statistical analysis and numerical correlations are not applicable to unstructured document text.
            </div>
            ${renderUnavailableMetricsSection(unavail)}
        `;
    }

    let numTableHtml = '';
    if (numStats && numStats.length > 0) {
        numTableHtml = `
            <div class="bi-section-card">
                <div class="bi-section-header">
                    <span class="bi-section-title">NUMERIC DESCRIPTIVE STATISTICS</span>
                    <span class="bi-section-subtitle">${numStats.length} continuous variables</span>
                </div>
                <div style="overflow-x: auto;">
                    <table class="data-preview-table">
                        <thead>
                            <tr>
                                <th>VARIABLE</th>
                                <th>COUNT</th>
                                <th>MEAN</th>
                                <th>STD</th>
                                <th>MIN</th>
                                <th>25% (Q1)</th>
                                <th>MEDIAN</th>
                                <th>75% (Q3)</th>
                                <th>MAX</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${numStats.map(ns => `
                                <tr>
                                    <td><strong>${escapeHtml(ns.column)}</strong></td>
                                    <td>${ns.count}</td>
                                    <td style="color: var(--cyan);">${ns.mean !== null && ns.mean !== undefined ? ns.mean : '-'}</td>
                                    <td>${ns.std !== null && ns.std !== undefined ? ns.std : '-'}</td>
                                    <td>${ns.min !== null && ns.min !== undefined ? ns.min : '-'}</td>
                                    <td>${ns.q25 !== null && ns.q25 !== undefined ? ns.q25 : '-'}</td>
                                    <td style="color: var(--gold); font-weight: bold;">${ns.median !== null && ns.median !== undefined ? ns.median : '-'}</td>
                                    <td>${ns.q75 !== null && ns.q75 !== undefined ? ns.q75 : '-'}</td>
                                    <td>${ns.max !== null && ns.max !== undefined ? ns.max : '-'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    let corrHtml = '';
    if (corrs.available && corrs.columns && corrs.columns.length >= 2) {
        const cols = corrs.columns;
        const matrix = corrs.matrix || {};
        const sigs = corrs.significant_correlations || [];

        let tableHeader = '<th>VARIABLE</th>' + cols.map(c => `<th>${escapeHtml(c)}</th>`).join('');
        let tableRows = cols.map(rCol => {
            let rowCells = cols.map(cCol => {
                const val = matrix[rCol] ? matrix[rCol][cCol] : null;
                if (val === null || val === undefined) return '<td class="cell-null">N/A</td>';
                let style = '';
                if (rCol === cCol) {
                    style = 'color: var(--cyan); font-weight: bold;';
                } else if (val >= 0.5) {
                    style = 'color: #00ffaa; font-weight: bold; background: rgba(0,255,170,0.1);';
                } else if (val <= -0.5) {
                    style = 'color: #ff3344; font-weight: bold; background: rgba(255,51,68,0.1);';
                }
                return `<td style="${style}">${Number(val).toFixed(3)}</td>`;
            }).join('');
            return `<tr><td><strong>${escapeHtml(rCol)}</strong></td>${rowCells}</tr>`;
        }).join('');

        let sigsHtml = '';
        if (sigs.length > 0) {
            sigsHtml = `
                <div style="margin-top: 14px; display: flex; flex-direction: column; gap: 8px;">
                    <div style="font-size: 0.8rem; color: var(--text-muted); font-weight: bold;">NOTABLE LINEAR CORRELATIONS (|r| &ge; 0.50):</div>
                    ${sigs.map(s => `
                        <div style="background: rgba(0,240,255,0.04); border-left: 3px solid ${s.correlation >= 0 ? 'var(--cyan)' : 'var(--neon-red)'}; padding: 8px 12px; border-radius: 4px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <strong style="color: #fff; font-size: 0.85rem;">${escapeHtml(s.col1)} &harr; ${escapeHtml(s.col2)}</strong>
                                <span class="bi-badge" style="font-size: 0.7rem; color: ${s.correlation >= 0 ? '#00ffaa' : '#ff3344'};">r = ${s.correlation} (${escapeHtml(s.strength)})</span>
                            </div>
                            <p style="margin: 4px 0 0 0; font-size: 0.78rem; color: #a0c4df;">${escapeHtml(s.interpretation)}</p>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        corrHtml = `
            <div class="bi-section-card">
                <div class="bi-section-header">
                    <span class="bi-section-title">PEARSON CORRELATION MATRIX</span>
                    <span class="bi-section-subtitle">${cols.length} numeric columns &bull; Measured from -1.00 to +1.00</span>
                </div>
                <div style="overflow-x: auto;">
                    <table class="data-preview-table" style="text-align: center;">
                        <thead><tr>${tableHeader}</tr></thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
                ${sigsHtml}
            </div>
        `;
    } else {
        corrHtml = `
            <div class="bi-section-card">
                <div class="bi-section-header">
                    <span class="bi-section-title">PEARSON CORRELATION MATRIX</span>
                </div>
                <div class="bi-notice-box">
                    ${escapeHtml(corrs.reason || 'Insufficient numeric columns with variance to compute Pearson correlation.')}
                </div>
            </div>
        `;
    }

    let catHtml = '';
    if (cats.available && cats.distributions && Object.keys(cats.distributions).length > 0) {
        catHtml = `
            <div class="bi-section-card">
                <div class="bi-section-header">
                    <span class="bi-section-title">CATEGORICAL FREQUENCY DISTRIBUTIONS</span>
                    <span class="bi-section-subtitle">${cats.columns_analyzed.length} discrete categorical fields</span>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
                    ${Object.entries(cats.distributions).map(([col, dist]) => `
                        <div style="background: rgba(0, 240, 255, 0.03); border: 1px solid rgba(0, 240, 255, 0.15); padding: 12px; border-radius: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <strong style="color: var(--cyan); font-size: 0.88rem;">${escapeHtml(col)}</strong>
                                <span style="font-size: 0.72rem; color: var(--text-muted);">${dist.distinct_count} distinct</span>
                            </div>
                            <div style="font-size: 0.78rem; margin-bottom: 10px; color: #a0c4df;">
                                MODE: <strong style="color: #fff;">${escapeHtml(dist.mode)}</strong> (${dist.mode_count} records)
                            </div>
                            <div style="display: flex; flex-direction: column; gap: 6px;">
                                ${(dist.breakdown || []).slice(0, 6).map(b => `
                                    <div>
                                        <div style="display: flex; justify-content: space-between; font-size: 0.75rem; margin-bottom: 2px;">
                                            <span style="color: #fff;">${escapeHtml(b.value)}</span>
                                            <span style="color: var(--cyan);">${b.count} (${b.percentage}%)</span>
                                        </div>
                                        <div style="height: 4px; background: rgba(0, 240, 255, 0.1); border-radius: 2px; overflow: hidden;">
                                            <div style="height: 100%; width: ${b.percentage}%; background: var(--cyan);"></div>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    return `
        ${numTableHtml}
        ${corrHtml}
        ${catHtml}
        ${renderUnavailableMetricsSection(unavail)}
    `;
}

function renderUnavailableMetricsSection(unavail) {
    if (!unavail || unavail.length === 0) return '';
    return `
        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title" style="color: var(--gold);">EXPLANATION OF UNAVAILABLE METRICS</span>
                <span class="bi-section-subtitle">Explicit explanation of non-applicable metrics</span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px;">
                ${unavail.map(u => `
                    <div style="background: rgba(255,170,0,0.05); border-left: 3px solid var(--gold); padding: 10px; border-radius: 4px;">
                        <strong style="color: #fff; font-size: 0.85rem;">${escapeHtml(u.metric)}</strong>
                        <div style="font-size: 0.72rem; color: var(--gold); margin: 3px 0;">REQUIRED: ${escapeHtml((u.required_columns || []).join(', '))}</div>
                        <p style="margin: 0; font-size: 0.78rem; color: #a0c4df;">${escapeHtml(u.reason)}</p>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function renderPricingPane(report) {
    const pricing = report.pricing || {};
    if (!pricing.computed) {
        return `
            <div class="bi-notice-box warning">
                <strong>PRICING & MARGIN ANALYTICS UNAVAILABLE</strong><br>
                ${escapeHtml(pricing.reason || 'Cost price and selling price columns are required.')}<br>
                <span style="font-size: 0.7rem; color: var(--text-muted);">Required Fields: ${escapeHtml((pricing.missing_fields || []).join(', '))}</span>
            </div>
        `;
    }

    const topProducts = pricing.highest_margin_products || [];
    const lowProducts = pricing.lowest_margin_products || [];

    // Simple SVG horizontal bar chart for top products
    let chartSvg = renderHorizontalBarChart(topProducts, 'gross_margin_pct', 'product', '%');

    return `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
            <div class="bi-kpi-card cyan">
                <span class="bi-kpi-label">AVERAGE GROSS MARGIN</span>
                <span class="bi-kpi-value">${pricing.average_gross_margin_pct}%</span>
            </div>
            <div class="bi-kpi-card gold">
                <span class="bi-kpi-label">AVERAGE MARKUP</span>
                <span class="bi-kpi-value">${pricing.average_markup_pct}%</span>
            </div>
            <div class="bi-kpi-card">
                <span class="bi-kpi-label">ANALYZED PRODUCTS</span>
                <span class="bi-kpi-value">${pricing.analyzed_products_count}</span>
            </div>
            <div class="bi-kpi-card ${pricing.negative_margin_count > 0 ? 'red' : 'green'}">
                <span class="bi-kpi-label">NEGATIVE MARGINS</span>
                <span class="bi-kpi-value">${pricing.negative_margin_count}</span>
            </div>
        </div>

        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">TOP GROSS MARGIN PRODUCTS</span>
                <span class="bi-section-subtitle">Ranked by ((Sale - Cost) / Sale) * 100</span>
            </div>
            <div class="bi-chart-container">
                ${chartSvg}
            </div>
            <div style="overflow-x: auto; margin-top: 10px;">
                <table class="data-preview-table">
                    <thead>
                        <tr>
                            <th>PRODUCT</th>
                            <th>COST PRICE</th>
                            <th>SELLING PRICE</th>
                            <th>UNIT PROFIT</th>
                            <th>GROSS MARGIN</th>
                            <th>MARKUP</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${topProducts.map(p => `
                            <tr>
                                <td><strong>${escapeHtml(p.product)}</strong></td>
                                <td>$${p.cost_price.toFixed(2)}</td>
                                <td>$${p.selling_price.toFixed(2)}</td>
                                <td style="color: var(--cyan);">$${p.gross_profit_per_unit.toFixed(2)}</td>
                                <td style="color: #00ffaa; font-weight: bold;">${p.gross_margin_pct}%</td>
                                <td>${p.markup_pct !== null ? p.markup_pct + '%' : 'N/A'}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderInventoryPane(report) {
    const inv = report.inventory || {};
    if (!inv.computed) {
        return `
            <div class="bi-notice-box warning">
                <strong>INVENTORY ANALYTICS UNAVAILABLE</strong><br>
                ${escapeHtml(inv.reason || 'Stock quantity columns are required.')}<br>
                <span style="font-size: 0.7rem; color: var(--text-muted);">Required Fields: ${escapeHtml((inv.missing_fields || []).join(', '))}</span>
            </div>
        `;
    }

    const lowStock = inv.low_stock_products || [];

    return `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
            <div class="bi-kpi-card cyan">
                <span class="bi-kpi-label">TOTAL STOCK UNITS</span>
                <span class="bi-kpi-value">${(inv.total_units_in_stock || 0).toLocaleString()}</span>
            </div>
            <div class="bi-kpi-card ${inv.low_stock_count > 0 ? 'red' : 'green'}">
                <span class="bi-kpi-label">LOW STOCK ITEMS</span>
                <span class="bi-kpi-value">${inv.low_stock_count}</span>
            </div>
            <div class="bi-kpi-card ${inv.out_of_stock_count > 0 ? 'red' : 'green'}">
                <span class="bi-kpi-label">OUT OF STOCK</span>
                <span class="bi-kpi-value">${inv.out_of_stock_count}</span>
            </div>
            <div class="bi-kpi-card gold">
                <span class="bi-kpi-label">EST. INVENTORY VALUE</span>
                <span class="bi-kpi-value">${inv.total_inventory_value !== null ? '$' + inv.total_inventory_value.toLocaleString(undefined, {minimumFractionDigits: 2}) : 'Requires Cost Column'}</span>
            </div>
        </div>

        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">LOW STOCK & CRITICAL REORDER ALERTS</span>
                <span class="bi-section-subtitle">${lowStock.length} flagged products</span>
            </div>
            ${lowStock.length === 0 ? '<div class="bi-notice-box">All inventory levels are above configured or default reorder thresholds.</div>' : `
                <div style="overflow-x: auto;">
                    <table class="data-preview-table">
                        <thead>
                            <tr>
                                <th>PRODUCT</th>
                                <th>CURRENT QUANTITY</th>
                                <th>REORDER THRESHOLD</th>
                                <th>DEFICIT STATUS</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${lowStock.map(p => `
                                <tr>
                                    <td><strong>${escapeHtml(p.product)}</strong></td>
                                    <td style="color: #ff5566; font-weight: bold;">${p.quantity}</td>
                                    <td>${p.threshold}</td>
                                    <td><span class="severity-badge critical">REORDER REQUIRED</span></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `}
        </div>
    `;
}

function renderSalesPane(report) {
    const sales = report.sales || {};
    if (!sales.computed) {
        return `
            <div class="bi-notice-box warning">
                <strong>SALES & REVENUE ANALYTICS UNAVAILABLE</strong><br>
                ${escapeHtml(sales.reason || 'Historical transaction or sales revenue columns required.')}<br>
                <span style="font-size: 0.7rem; color: var(--text-muted);">Required Fields: ${escapeHtml((sales.missing_fields || []).join(', '))}</span>
            </div>
        `;
    }

    const topSelling = sales.top_selling_products || [];
    const timeline = sales.sales_by_date || [];

    let trendSvg = renderTimelineAreaChart(timeline);

    return `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
            <div class="bi-kpi-card green">
                <span class="bi-kpi-label">TOTAL REVENUE</span>
                <span class="bi-kpi-value">$${(sales.total_revenue || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
            </div>
            <div class="bi-kpi-card cyan">
                <span class="bi-kpi-label">TRANSACTION COUNT</span>
                <span class="bi-kpi-value">${sales.transaction_count}</span>
            </div>
            <div class="bi-kpi-card gold">
                <span class="bi-kpi-label">AVERAGE TRANSACTION (ATV)</span>
                <span class="bi-kpi-value">$${(sales.average_transaction_value || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
            </div>
            <div class="bi-kpi-card">
                <span class="bi-kpi-label">UNITS SOLD</span>
                <span class="bi-kpi-value">${(sales.units_sold || 0).toLocaleString()}</span>
            </div>
        </div>

        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">REVENUE TIMELINE TREND</span>
                <span class="bi-section-subtitle">Chronological progression</span>
            </div>
            <div class="bi-chart-container">
                ${trendSvg}
            </div>
        </div>

        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">TOP REVENUE PRODUCTS</span>
                <span class="bi-section-subtitle">By aggregate sales volume</span>
            </div>
            <div style="overflow-x: auto;">
                <table class="data-preview-table">
                    <thead>
                        <tr>
                            <th>PRODUCT</th>
                            <th>REVENUE GENERATED</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${topSelling.map(p => `
                            <tr>
                                <td><strong>${escapeHtml(p.product)}</strong></td>
                                <td style="color: var(--cyan); font-weight: bold;">$${p.revenue.toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderSuppliersPane(report) {
    const supp = report.suppliers || {};
    if (!supp.computed) {
        return `
            <div class="bi-notice-box">
                <strong>SUPPLIER ANALYTICS UNAVAILABLE</strong><br>
                ${escapeHtml(supp.reason || 'Supplier and vendor columns were not detected in this file.')}<br>
                <span style="font-size: 0.7rem; color: var(--text-muted);">Required Fields: ${escapeHtml((supp.missing_fields || []).join(', '))}</span>
            </div>
        `;
    }

    const topSupp = supp.top_suppliers || [];

    return `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
            <div class="bi-kpi-card cyan">
                <span class="bi-kpi-label">SUPPLIER COUNT</span>
                <span class="bi-kpi-value">${supp.supplier_count}</span>
            </div>
            <div class="bi-kpi-card gold">
                <span class="bi-kpi-label">TOTAL SPEND</span>
                <span class="bi-kpi-value">$${(supp.total_spend || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
            </div>
            <div class="bi-kpi-card">
                <span class="bi-kpi-label">MULTI-SUPPLIER PRODUCTS</span>
                <span class="bi-kpi-value">${supp.multi_supplier_products_count}</span>
            </div>
        </div>

        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">VENDOR CONCENTRATION & SPEND</span>
                <span class="bi-section-subtitle">Ranked by volume and total spend</span>
            </div>
            <div style="overflow-x: auto;">
                <table class="data-preview-table">
                    <thead>
                        <tr>
                            <th>SUPPLIER NAME</th>
                            <th>RECORD COUNT</th>
                            <th>TOTAL SPEND</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${topSupp.map(s => `
                            <tr>
                                <td><strong>${escapeHtml(s.supplier)}</strong></td>
                                <td>${s.count}</td>
                                <td style="color: var(--cyan); font-weight: bold;">$${s.spend.toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderRawPreviewPane(report) {
    if (report.file_type === 'pdf') {
        const text = report.raw_text_preview || 'No readable text content.';
        return `
            <div class="bi-section-card">
                <div class="bi-section-header">
                    <span class="bi-section-title">PDF DOCUMENT STREAM PREVIEW</span>
                    <span class="bi-section-subtitle">${(report.dataset_summary || {}).page_count || 1} pages</span>
                </div>
                <div class="pdf-text-preview" style="max-height: 400px;">${escapeHtml(text)}</div>
            </div>
        `;
    }

    const rows = report.raw_preview_rows || [];
    const cols = report.columns || [];

    if (rows.length === 0) {
        return '<div class="bi-notice-box">No raw tabular records to display.</div>';
    }

    return `
        <div class="bi-section-card">
            <div class="bi-section-header">
                <span class="bi-section-title">EXTRACTED TABULAR MATRIX</span>
                <span class="bi-section-subtitle">Displaying first ${rows.length} rows</span>
            </div>
            <div style="overflow-x: auto; max-height: 420px;">
                <table class="data-preview-table">
                    <thead>
                        <tr>
                            ${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr>
                                ${cols.map(c => {
                                    const val = row[c];
                                    if (val === null || val === undefined) return '<td class="cell-null">null</td>';
                                    return `<td>${escapeHtml(String(val))}</td>`;
                                }).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

/* ========================================================
   LIGHTWEIGHT PROCEDURAL SVG CHART GENERATORS
   ======================================================== */

function renderHorizontalBarChart(items, valKey, labelKey, unit = '') {
    if (!items || items.length === 0) {
        return '<p style="color: var(--text-muted); text-align: center;">Insufficient data for visualization.</p>';
    }

    const maxVal = Math.max(...items.map(it => Math.abs(it[valKey] || 0)), 1);
    const height = Math.max(items.length * 28 + 20, 100);

    let bars = '';
    items.slice(0, 8).forEach((it, idx) => {
        const y = idx * 28 + 10;
        const val = it[valKey] || 0;
        const pctWidth = Math.max(Math.min((Math.abs(val) / maxVal) * 65, 65), 1);
        const barColor = val < 0 ? '#ff3344' : '#00f0ff';

        bars += `
            <text x="10" y="${y + 14}" fill="#7899b5" font-size="11" font-family="'Orbitron', monospace">${escapeHtml(it[labelKey]).substring(0, 16)}</text>
            <rect x="160" y="${y + 3}" width="${pctWidth}%" height="16" rx="3" fill="${barColor}" fill-opacity="0.85"></rect>
            <text x="${165 + pctWidth * 5}" y="${y + 15}" fill="#fff" font-size="11" font-weight="bold">${val}${unit}</text>
        `;
    });

    return `
        <svg class="bi-svg-chart" viewBox="0 0 600 ${height}">
            ${bars}
        </svg>
    `;
}

function renderTimelineAreaChart(timeline) {
    if (!timeline || timeline.length < 2) {
        return '<p style="color: var(--text-muted); text-align: center; padding: 20px;">Timeline requires multiple dated transaction points.</p>';
    }

    const maxRev = Math.max(...timeline.map(t => t.revenue || 0), 1);
    const width = 580;
    const height = 150;
    const padding = 30;

    const points = timeline.map((pt, idx) => {
        const x = padding + (idx / (timeline.length - 1)) * (width - padding * 2);
        const y = height - padding - ((pt.revenue || 0) / maxRev) * (height - padding * 2);
        return { x, y, date: pt.date, rev: pt.revenue };
    });

    const pathD = points.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`, '');
    const areaD = `${pathD} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`;

    let labels = '';
    points.forEach((p, i) => {
        if (i === 0 || i === points.length - 1 || i === Math.floor(points.length / 2)) {
            labels += `<text x="${p.x}" y="${height - 8}" fill="#7899b5" font-size="9" text-anchor="middle">${escapeHtml(p.date)}</text>`;
        }
    });

    return `
        <svg class="bi-svg-chart" viewBox="0 0 ${width} ${height}">
            <defs>
                <linearGradient id="chartGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#00f0ff" stop-opacity="0.4"></stop>
                    <stop offset="100%" stop-color="#00f0ff" stop-opacity="0.0"></stop>
                </linearGradient>
            </defs>
            <path d="${areaD}" fill="url(#chartGrad)"></path>
            <path d="${pathD}" fill="none" stroke="#00f0ff" stroke-width="2.5"></path>
            ${points.map(p => `<circle cx="${p.x}" cy="${p.y}" r="3.5" fill="#00f0ff" stroke="#fff" stroke-width="1"></circle>`).join('')}
            ${labels}
        </svg>
    `;
}

// ==============================================================================
// SAVED DATA LIBRARY CONTROLLER
// ==============================================================================

let libraryCurrentPage = 1;
let libraryPageSize = 5;
let librarySearchQuery = '';
let libraryFilterType = '';
let searchDebounceTimer = null;
let activeDatasetId = null;

async function loadSavedDatasets(page = 1) {
    libraryCurrentPage = page;
    const container = document.getElementById('libraryListContainer');
    const badge = document.getElementById('libraryCountBadge');
    const paginationRow = document.getElementById('libraryPaginationRow');
    const pageIndicator = document.getElementById('libPageIndicator');
    const prevBtn = document.getElementById('libPrevBtn');
    const nextBtn = document.getElementById('libNextBtn');

    if (!container) return;

    try {
        let url = `/api/datasets?page=${libraryCurrentPage}&page_size=${libraryPageSize}`;
        if (librarySearchQuery) url += `&search=${encodeURIComponent(librarySearchQuery)}`;
        if (libraryFilterType) url += `&file_type=${encodeURIComponent(libraryFilterType)}`;

        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch datasets');
        const data = await res.json();

        if (!data.success) throw new Error(data.error || 'Server error');

        const datasets = data.datasets || [];
        const pag = data.pagination || { total_items: 0, total_pages: 1, page: 1 };

        if (badge) badge.textContent = `${pag.total_items} DATASET${pag.total_items === 1 ? '' : 'S'}`;

        if (datasets.length === 0) {
            container.innerHTML = `
                <div class="library-empty-state">
                    <span class="empty-icon">📂</span>
                    <p class="empty-text">${librarySearchQuery || libraryFilterType ? 'No datasets match your search criteria.' : 'No saved datasets yet. Import an Excel or PDF file to begin.'}</p>
                </div>
            `;
            if (paginationRow) paginationRow.style.display = 'none';
            return;
        }

        let html = '';
        datasets.forEach(ds => {
            const isCur = ds.id === activeDatasetId;
            const ext = (ds.file_type || '').toLowerCase();
            const dateStr = ds.created_at ? new Date(ds.created_at).toLocaleString() : 'N/A';
            const countInfo = ext === 'pdf' ? `${ds.page_count || 1} Pages` : `${ds.row_count || 0} Rows`;
            const idxStatus = ds.index_status || 'unindexed';
            const chunkCount = ds.chunk_count || 0;

            let statusBadge = '';
            if (idxStatus === 'indexed') {
                statusBadge = `<span class="bi-badge" style="background: rgba(0,255,170,0.15); color: #00ffaa; border: 1px solid #00ffaa; font-size: 0.65rem;">INDEXED (${chunkCount})</span>`;
            } else if (idxStatus === 'empty_ocr_required') {
                statusBadge = `<span class="bi-badge" style="background: rgba(255,170,0,0.15); color: #ffaa00; border: 1px solid #ffaa00; font-size: 0.65rem;">OCR REQUIRED</span>`;
            } else if (idxStatus === 'failed') {
                statusBadge = `<span class="bi-badge" style="background: rgba(255,51,68,0.15); color: #ff3344; border: 1px solid #ff3344; font-size: 0.65rem;">FAILED</span>`;
            } else if (idxStatus === 'indexing') {
                statusBadge = `<span class="bi-badge" style="background: rgba(0,210,255,0.15); color: #00d2ff; border: 1px solid #00d2ff; font-size: 0.65rem;">INDEXING...</span>`;
            } else {
                statusBadge = `<span class="bi-badge" style="background: rgba(150,150,150,0.15); color: #aaa; border: 1px solid #666; font-size: 0.65rem;">UNINDEXED</span>`;
            }

            html += `
                <div class="library-card ${isCur ? 'active-dataset' : ''}" id="libCard_${ds.id}">
                    <div class="library-card-header">
                        <div class="library-card-title-group" title="${escapeHtml(ds.original_filename)}">
                            <span class="library-type-badge ${ext}">${ext.toUpperCase()}</span>
                            <span class="library-card-name" onclick="openSavedDataset('${ds.id}')">${escapeHtml(ds.original_filename)}</span>
                        </div>
                        ${statusBadge}
                    </div>
                    <div class="library-card-meta">
                        <span>📊 ${countInfo}</span>
                        <span>⏱️ ${dateStr}</span>
                    </div>
                    <div class="library-card-actions">
                        <button type="button" class="lib-action-btn" onclick="openSavedDataset('${ds.id}')" title="Set as active working dataset">OPEN</button>
                        <button type="button" class="lib-action-btn" onclick="reindexDataset('${ds.id}')" title="Index or reindex for RAG intelligence">INDEX</button>
                        <button type="button" class="lib-action-btn" onclick="viewDatasetReport('${ds.id}')" title="View Intelligence Dossier">REPORT</button>
                        <button type="button" class="lib-action-btn" onclick="reanalyzeSavedDataset('${ds.id}')" title="Rerun neural analysis engine">REANALYZE</button>
                        <button type="button" class="lib-action-btn delete-btn" onclick="deleteSavedDataset('${ds.id}')" title="Delete dataset and history">🗑️</button>
                    </div>
                </div>
            `;
        });

        container.innerHTML = html;

        // Update pagination
        if (paginationRow) {
            if (pag.total_pages > 1) {
                paginationRow.style.display = 'flex';
                pageIndicator.textContent = `PAGE ${pag.page} / ${pag.total_pages}`;
                prevBtn.disabled = !pag.has_prev;
                nextBtn.disabled = !pag.has_next;
            } else {
                paginationRow.style.display = 'none';
            }
        }

    } catch (err) {
        console.warn('Error loading library:', err);
        container.innerHTML = `
            <div class="library-empty-state">
                <span class="empty-icon" style="color: var(--red);">⚠️</span>
                <p class="empty-text" style="color: var(--red);">Failed to connect to local database library.</p>
            </div>
        `;
    }
}

function onLibrarySearch(query) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
        librarySearchQuery = query.trim();
        loadSavedDatasets(1);
    }, 250);
}

function onLibraryFilter(type) {
    libraryFilterType = type.trim();
    loadSavedDatasets(1);
}

function changeLibraryPage(delta) {
    loadSavedDatasets(libraryCurrentPage + delta);
}

async function openSavedDataset(datasetId) {
    logTerminal(`Accessing persistent dataset ${datasetId}...`, 'system');
    try {
        const res = await fetch(`/api/datasets/${datasetId}/open`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Failed to open dataset');
        }

        activeDatasetId = datasetId;
        currentBIReport = data.report;
        const ds = data.dataset;

        // Update import result card and preview viewport
        const resultViewport = document.getElementById('importResultViewport');
        if (resultViewport && ds) {
            renderImportResult({
                file_name: ds.original_filename,
                file_type: ds.file_type,
                summary: ds.extraction_summary || {
                    sheet_count: ds.sheet_count,
                    total_rows: ds.row_count,
                    total_columns: ds.column_count,
                    page_count: ds.page_count
                },
                sheets: ds.sheets || [],
                report: data.report
            });
        }

        logTerminal(`Dataset '${ds.original_filename}' activated in VANTIQ workspace.`, 'jarvis');
        jarvisSpeak(`Loaded saved dataset ${ds.original_filename}.`);
        loadSavedDatasets(libraryCurrentPage);
    } catch (err) {
        logTerminal(`[ERROR] Failed to open dataset: ${err.message}`, 'system');
    }
}

async function viewDatasetReport(datasetId) {
    try {
        logTerminal(`Retrieving intelligence dossier for ${datasetId}...`, 'system');
        const res = await fetch(`/api/datasets/${datasetId}/reports`);
        const data = await res.json();
        if (!res.ok || !data.success || !data.reports || data.reports.length === 0) {
            throw new Error('No reports found for this dataset.');
        }

        const latestReportId = data.reports[0].report_id;
        const repRes = await fetch(`/api/reports/${latestReportId}`);
        const repData = await repRes.json();
        if (!repRes.ok || !repData.success) {
            throw new Error(repData.error || 'Failed to load report.');
        }

        activeDatasetId = datasetId;
        currentBIReport = repData.report.report_content;
        openBIModal(currentBIReport);
        loadSavedDatasets(libraryCurrentPage);
    } catch (err) {
        logTerminal(`[ERROR] Could not load saved report: ${err.message}`, 'system');
        showImportError(err.message);
    }
}

async function reanalyzeSavedDataset(datasetId) {
    logTerminal(`Triggering neural re-analysis on dataset ${datasetId}...`, 'system');
    jarvisSpeak('Re-analyzing dataset with analytical engine.');
    try {
        const res = await fetch(`/api/datasets/${datasetId}/analyze`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Re-analysis failed.');
        }

        activeDatasetId = datasetId;
        currentBIReport = data.report;
        openBIModal(currentBIReport);
        logTerminal(`Re-analysis complete (Version: ${data.analysis_version}). New analysis run recorded.`, 'jarvis');
        jarvisSpeak('Neural re-analysis complete and saved to persistent database.');
        loadSavedDatasets(libraryCurrentPage);
    } catch (err) {
        logTerminal(`[ERROR] Re-analysis failed: ${err.message}`, 'system');
        showImportError(`Re-analysis failed: ${err.message}`);
    }
}

async function reindexDataset(datasetId) {
    logTerminal(`Reindexing document ${datasetId} for RAG intelligence...`, 'system');
    try {
        const res = await fetch(`/api/rag/documents/${datasetId}/reindex`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            logTerminal(`[RAG] Document ${data.document_name || datasetId} indexed successfully (${data.chunk_count} chunks).`, 'jarvis');
            jarvisSpeak('Document indexed into local intelligence store.');
        } else if (data.status === 'empty_ocr_required') {
            logTerminal(`[RAG WARNING] Scanned document: ${data.error}`, 'system');
            jarvisSpeak('Scanned document detected. OCR is required to extract text.');
        } else {
            logTerminal(`[RAG ERROR] Indexing failed: ${data.error}`, 'system');
        }
        loadSavedDatasets(libraryCurrentPage);
    } catch (err) {
        logTerminal(`[ERROR] Reindex request failed: ${err.message}`, 'system');
    }
}

async function deleteSavedDataset(datasetId) {
    const confirmDel = confirm(`CONFIRM DECOMMISSION:\nPermanently remove dataset ${datasetId} and its associated analysis history from the persistent database?`);
    if (!confirmDel) return;

    try {
        const res = await fetch(`/api/datasets/${datasetId}`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Deletion failed.');
        }

        logTerminal(`Dataset ${datasetId} deleted from database.`, 'system');
        if (activeDatasetId === datasetId) {
            activeDatasetId = null;
            currentBIReport = null;
            closeImportPreview();
        }
        loadSavedDatasets(1);
    } catch (err) {
        logTerminal(`[ERROR] Delete failed: ${err.message}`, 'system');
    }
}

function renderHistoryPane(report) {
    if (!activeDatasetId) {
        return `
            <div class="bi-section-card">
                <h3 class="bi-section-heading">ANALYSIS RUNS & VERSION AUDIT</h3>
                <p style="color: var(--text-muted); font-size: 0.78rem;">Analysis history is tracked for saved datasets in the local database.</p>
            </div>
        `;
    }

    return `
        <div class="bi-section-card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h3 class="bi-section-heading" style="margin: 0;">HISTORICAL ANALYSIS RUNS</h3>
                <button type="button" class="lib-action-btn" style="flex: 0 0 130px;" onclick="reanalyzeSavedDataset('${activeDatasetId}')">⚡ NEW ANALYSIS RUN</button>
            </div>
            <p style="color: var(--text-muted); font-size: 0.74rem;">Every analysis run is preserved with independent timestamps and engine versions.</p>
            <div id="modalHistoryContainer" style="margin-top: 10px;">
                <p style="color: var(--cyan); font-size: 0.75rem;">Loading historical runs...</p>
            </div>
        </div>
    `;
}

async function loadModalHistoryRuns(datasetId) {
    const histElem = document.getElementById('modalHistoryContainer');
    if (!histElem) return;

    try {
        const res = await fetch(`/api/datasets/${datasetId}/reports`);
        const data = await res.json();
        if (!res.ok || !data.success || !data.reports) {
            histElem.innerHTML = '<p style="color: var(--text-muted); font-size: 0.75rem;">No historical runs found.</p>';
            return;
        }

        const reports = data.reports;
        if (reports.length === 0) {
            histElem.innerHTML = '<p style="color: var(--text-muted); font-size: 0.75rem;">No historical runs found.</p>';
            return;
        }

        let html = `
            <table class="analysis-history-table">
                <thead>
                    <tr>
                        <th>RUN ID</th>
                        <th>VERSION</th>
                        <th>REPORT TYPE</th>
                        <th>STATUS</th>
                        <th>TIMESTAMP</th>
                        <th>ACTION</th>
                    </tr>
                </thead>
                <tbody>
        `;

        reports.forEach(r => {
            const dt = r.created_at ? new Date(r.created_at).toLocaleString() : 'N/A';
            html += `
                <tr>
                    <td style="color: var(--cyan); font-family: var(--font-display);">${escapeHtml(r.analysis_run_id || '')}</td>
                    <td><span class="bi-badge">${escapeHtml(r.analysis_version || 'v1.0.0')}</span></td>
                    <td>${escapeHtml(r.report_type || 'full_bi')}</td>
                    <td><span style="color: #00ff88;">${escapeHtml(r.analysis_status || 'success')}</span></td>
                    <td style="color: var(--text-muted); font-size: 0.68rem;">${dt}</td>
                    <td>
                        <button type="button" class="lib-action-btn" onclick="loadSpecificReport('${r.report_id}')" style="padding: 2px 6px;">VIEW</button>
                    </td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        histElem.innerHTML = html;
    } catch (e) {
        histElem.innerHTML = `<p style="color: var(--red); font-size: 0.75rem;">Error loading run history: ${escapeHtml(e.message)}</p>`;
    }
}

async function loadSpecificReport(reportId) {
    try {
        const res = await fetch(`/api/reports/${reportId}`);
        const data = await res.json();
        if (res.ok && data.success && data.report) {
            currentBIReport = data.report.report_content;
            renderBIModalContent(currentBIReport);
            logTerminal(`Loaded historical report ${reportId} (${data.report.analysis_version || ''}).`, 'jarvis');
        }
    } catch (e) {
        console.error('Error loading specific report:', e);
    }
}


// ==============================================================================
// J.A.R.V.I.S. STEP 4 — PRODUCT CATALOGUE & INVENTORY MANAGEMENT CONTROLLER
// ==============================================================================

let catalogueState = {
    page: 1,
    pageSize: 15,
    search: '',
    category: '',
    status: '1',
    stockFilter: '',
    sortBy: 'name',
    sortOrder: 'asc',
    totalPages: 1,
    activeTab: 'products'
};

let currentDetailProduct = null;
let currentAdjustProduct = null;
let mappingDatasetId = null;
let mappingDatasetColumns = [];

function initCatalogueModule() {
    fetchCatalogueSummary();
    setInterval(fetchCatalogueSummary, 10000);
}

// Fetch HUD Summary Telemetry
async function fetchCatalogueSummary() {
    try {
        const res = await fetch('/api/inventory');
        if (!res.ok) return;
        const data = await res.json();
        if (data.success && data.summary) {
            const s = data.summary;
            // Left HUD Card
            const activeElem = document.getElementById('hudActiveProdsVal');
            const stockElem = document.getElementById('hudTotalStockVal');
            const lowElem = document.getElementById('hudLowStockVal');
            const outElem = document.getElementById('hudOutOfStockVal');

            if (activeElem) activeElem.textContent = s.active_products || 0;
            if (stockElem) stockElem.textContent = (s.total_stock_units || 0).toLocaleString();
            if (lowElem) lowElem.textContent = s.low_stock_count || 0;
            if (outElem) outElem.textContent = s.out_of_stock_count || 0;

            // Modal Header & KPIs
            const modalActive = document.getElementById('catActiveBadge');
            const modalStock = document.getElementById('catTotalStockBadge');
            if (modalActive) modalActive.textContent = `${s.active_products || 0} ACTIVE PRODUCTS`;
            if (modalStock) modalStock.textContent = `TOTAL STOCK: ${(s.total_stock_units || 0).toLocaleString()} UNITS`;

            const kpiActive = document.getElementById('catKpiActive');
            const kpiStock = document.getElementById('catKpiStock');
            const kpiLow = document.getElementById('catKpiLow');
            const kpiOut = document.getElementById('catKpiOut');
            const kpiMiss = document.getElementById('catKpiMissingPrice');

            if (kpiActive) kpiActive.textContent = s.active_products || 0;
            if (kpiStock) kpiStock.textContent = (s.total_stock_units || 0).toLocaleString();
            if (kpiLow) kpiLow.textContent = s.low_stock_count || 0;
            if (kpiOut) kpiOut.textContent = s.out_of_stock_count || 0;
            if (kpiMiss) kpiMiss.textContent = s.missing_price_count || 0;

            // Populate Category Filter dropdown
            const catSelect = document.getElementById('catCategoryFilter');
            if (catSelect && s.categories) {
                const currentVal = catSelect.value;
                let optHtml = '<option value="">ALL CATEGORIES</option>';
                s.categories.forEach(c => {
                    const selected = (c.category === currentVal) ? 'selected' : '';
                    optHtml += `<option value="${escapeHtml(c.category)}" ${selected}>${escapeHtml(c.category)} (${c.count})</option>`;
                });
                catSelect.innerHTML = optHtml;
            }
        }
    } catch (e) {
        console.warn('Failed to fetch catalogue summary:', e);
    }
}

function openCatalogueModal() {
    const modal = document.getElementById('catalogueModal');
    if (modal) {
        modal.style.display = 'flex';
        fetchCatalogueSummary();
        loadCatalogueProducts();
        logTerminal('Product Catalogue & Inventory module engaged.', 'jarvis');
    }
}

function closeCatalogueModal() {
    const modal = document.getElementById('catalogueModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function switchCatalogueTab(tab) {
    catalogueState.activeTab = tab;
    const tabProducts = document.getElementById('catTabProducts');
    const tabInv = document.getElementById('catTabInventory');
    const tabMov = document.getElementById('catTabMovements');

    const paneProducts = document.getElementById('catPaneProducts');
    const paneInv = document.getElementById('catPaneInventory');
    const paneMov = document.getElementById('catPaneMovements');

    if (tabProducts) tabProducts.classList.toggle('active', tab === 'products');
    if (tabInv) tabInv.classList.toggle('active', tab === 'inventory');
    if (tabMov) tabMov.classList.toggle('active', tab === 'movements');

    if (paneProducts) paneProducts.style.display = (tab === 'products') ? 'flex' : 'none';
    if (paneInv) paneInv.style.display = (tab === 'inventory') ? 'flex' : 'none';
    if (paneMov) paneMov.style.display = (tab === 'movements') ? 'flex' : 'none';

    if (tab === 'products') {
        loadCatalogueProducts();
    } else if (tab === 'inventory') {
        loadCatalogueInventory();
    } else if (tab === 'movements') {
        loadCatalogueMovements();
    }
}

// Load Products Table
async function loadCatalogueProducts() {
    const tbody = document.getElementById('catProductsTbody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding: 20px; color: var(--cyan);">Querying Stark Product Catalogue...</td></tr>';

    try {
        const params = new URLSearchParams({
            page: catalogueState.page,
            page_size: catalogueState.pageSize,
            sort_by: catalogueState.sortBy,
            sort_order: catalogueState.sortOrder
        });

        if (catalogueState.search) params.append('search', catalogueState.search);
        if (catalogueState.category) params.append('category', catalogueState.category);
        if (catalogueState.status !== '') params.append('is_active', catalogueState.status);
        if (catalogueState.stockFilter === 'low') params.append('low_stock', 'true');
        if (catalogueState.stockFilter === 'out') params.append('out_of_stock', 'true');

        const res = await fetch(`/api/products?${params.toString()}`);
        const data = await res.json();

        if (!res.ok || !data.success) {
            tbody.innerHTML = `<tr><td colspan="12" style="text-align:center; color: var(--red);">Error loading products: ${escapeHtml(data.error || 'Server error')}</td></tr>`;
            return;
        }

        const items = data.items || [];
        catalogueState.totalPages = data.total_pages || 1;

        // Update pagination UI
        const pageInd = document.getElementById('catPageIndicator');
        const prevBtn = document.getElementById('catPrevBtn');
        const nextBtn = document.getElementById('catNextBtn');

        if (pageInd) pageInd.textContent = `PAGE ${data.page} / ${catalogueState.totalPages} (${data.total_count} ITEMS)`;
        if (prevBtn) prevBtn.disabled = (data.page <= 1);
        if (nextBtn) nextBtn.disabled = (data.page >= catalogueState.totalPages);

        if (items.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="12" style="text-align: center; padding: 30px; color: var(--text-muted);">
                        No products found matching criteria. Click <strong>+ ADD PRODUCT</strong> or <strong>MAP TO PRODUCT CATALOGUE</strong> to create items.
                    </td>
                </tr>
            `;
            return;
        }

        let rowsHtml = '';
        items.forEach(p => {
            let statusPill = '';
            let rowClass = '';
            if (!p.is_active) {
                statusPill = '<span class="status-pill inactive">INACTIVE</span>';
            } else if (p.is_out_of_stock) {
                statusPill = '<span class="status-pill out-of-stock">OUT OF STOCK</span>';
                rowClass = 'out-of-stock-row';
            } else if (p.is_low_stock) {
                statusPill = '<span class="status-pill low-stock">LOW STOCK</span>';
                rowClass = 'low-stock-row';
            } else {
                statusPill = '<span class="status-pill in-stock">IN STOCK</span>';
            }

            const marginStr = (p.gross_margin_pct !== null && p.gross_margin_pct !== undefined)
                ? `<span style="color: ${p.gross_margin_pct >= 0 ? '#00ff80' : 'var(--red)'}; font-weight: 700;">${p.gross_margin_pct}%</span>`
                : '<span style="color: var(--text-muted);">--</span>';

            const costStr = (p.purchase_price !== null && p.purchase_price !== undefined) ? `${p.purchase_price.toFixed(2)} ${p.currency || 'INR'}` : '--';
            const priceStr = (p.selling_price !== null && p.selling_price !== undefined) ? `${p.selling_price.toFixed(2)} ${p.currency || 'INR'}` : '--';

            rowsHtml += `
                <tr class="${rowClass}">
                    <td style="color: var(--cyan); font-family: var(--font-display); font-weight: 700;">${escapeHtml(p.sku || 'N/A')}</td>
                    <td style="font-weight: 600; color: #fff;">${escapeHtml(p.name)}</td>
                    <td>${escapeHtml(p.category || 'General')}</td>
                    <td>${escapeHtml(p.supplier_name || '--')}</td>
                    <td>${costStr}</td>
                    <td style="color: var(--cyan); font-weight: 600;">${priceStr}</td>
                    <td>${marginStr}</td>
                    <td style="font-weight: 700;">${p.quantity_on_hand}</td>
                    <td style="color: var(--text-muted);">${escapeHtml(p.unit || 'piece')}</td>
                    <td>${p.reorder_level}</td>
                    <td>${statusPill}</td>
                    <td>
                        <button type="button" class="tbl-btn" onclick="openProductDetailModal(${p.id})">VIEW</button>
                        <button type="button" class="tbl-btn adjust" onclick="openStockAdjustModal(${p.id}, 'receipt')">STOCK</button>
                        <button type="button" class="tbl-btn" onclick="openEditProductModal(${p.id})">EDIT</button>
                        ${p.is_active ? `<button type="button" class="tbl-btn deactivate" onclick="deactivateProduct(${p.id})">DEACTIVATE</button>` : ''}
                    </td>
                </tr>
            `;
        });

        tbody.innerHTML = rowsHtml;
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="12" style="text-align:center; color: var(--red);">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

// Load Inventory Balances View
async function loadCatalogueInventory() {
    const tbody = document.getElementById('catInventoryTbody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 20px; color: var(--cyan);">Loading inventory balances...</td></tr>';

    try {
        const res = await fetch('/api/products?page_size=100&is_active=true&sort_by=stock&sort_order=asc');
        const data = await res.json();
        const items = data.items || [];

        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 20px; color: var(--text-muted);">No active inventory items found.</td></tr>';
            return;
        }

        let html = '';
        items.forEach(p => {
            let statusPill = '';
            if (p.is_out_of_stock) {
                statusPill = '<span class="status-pill out-of-stock">OUT OF STOCK (0)</span>';
            } else if (p.is_low_stock) {
                statusPill = '<span class="status-pill low-stock">LOW STOCK (≤ Reorder)</span>';
            } else {
                statusPill = '<span class="status-pill in-stock">OPTIMAL</span>';
            }

            const updatedStr = p.inventory_updated_at ? new Date(p.inventory_updated_at).toLocaleString() : '--';

            html += `
                <tr>
                    <td style="color: var(--cyan); font-family: var(--font-display);">${escapeHtml(p.sku || 'N/A')}</td>
                    <td style="font-weight: 600; color: #fff;">${escapeHtml(p.name)}</td>
                    <td style="font-weight: 700; font-size: 0.9rem;">${p.quantity_on_hand}</td>
                    <td>${p.reorder_level}</td>
                    <td style="color: var(--text-muted);">${escapeHtml(p.unit || 'piece')}</td>
                    <td>${statusPill}</td>
                    <td style="color: var(--text-muted); font-size: 0.68rem;">${updatedStr}</td>
                    <td>
                        <button type="button" class="tbl-btn adjust" onclick="openStockAdjustModal(${p.id}, 'receipt')">+ RECEIVE</button>
                        <button type="button" class="tbl-btn adjust" onclick="openStockAdjustModal(${p.id}, 'adjustment')">± ADJUST</button>
                        <button type="button" class="tbl-btn" onclick="openProductDetailModal(${p.id})">HISTORY</button>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color: var(--red);">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

// Load Movements History View
async function loadCatalogueMovements() {
    const tbody = document.getElementById('catMovementsTbody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 20px; color: var(--cyan);">Loading movement ledger...</td></tr>';

    try {
        const res = await fetch('/api/inventory/movements?limit=50');
        const data = await res.json();
        const items = data.items || [];

        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 20px; color: var(--text-muted);">No stock movements recorded yet.</td></tr>';
            return;
        }

        let html = '';
        items.forEach(m => {
            const dt = m.created_at ? new Date(m.created_at).toLocaleString() : '--';
            const deltaColor = m.quantity_delta > 0 ? '#00ff80' : 'var(--red)';
            const deltaSign = m.quantity_delta > 0 ? `+${m.quantity_delta}` : `${m.quantity_delta}`;

            html += `
                <tr>
                    <td style="color: var(--text-muted); font-size: 0.68rem;">${dt}</td>
                    <td style="color: #fff; font-weight: 600;">${escapeHtml(m.product_name)} <span style="color: var(--cyan); font-size: 0.65rem;">(${escapeHtml(m.product_sku || '')})</span></td>
                    <td><span class="bi-badge">${escapeHtml(m.movement_type.toUpperCase())}</span></td>
                    <td style="color: ${deltaColor}; font-weight: 700;">${deltaSign} ${escapeHtml(m.product_unit || '')}</td>
                    <td>${m.quantity_before}</td>
                    <td style="font-weight: 700;">${m.quantity_after}</td>
                    <td style="color: var(--text-muted);">${escapeHtml(m.reason || '')}</td>
                    <td style="color: var(--cyan);">${escapeHtml(m.reference || '--')}</td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color: var(--red);">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

// Search & Filter event handlers
let catSearchTimer = null;
function onCatalogueSearch(val) {
    clearTimeout(catSearchTimer);
    catSearchTimer = setTimeout(() => {
        catalogueState.search = val.trim();
        catalogueState.page = 1;
        loadCatalogueProducts();
    }, 300);
}

function onCatalogueFilterChange() {
    const cat = document.getElementById('catCategoryFilter').value;
    const stat = document.getElementById('catStatusFilter').value;
    const stock = document.getElementById('catStockFilter').value;

    catalogueState.category = cat;
    catalogueState.status = stat;
    catalogueState.stockFilter = stock;
    catalogueState.page = 1;
    loadCatalogueProducts();
}

function onCatalogueSortChange() {
    catalogueState.sortBy = document.getElementById('catSortBy').value;
    catalogueState.sortOrder = document.getElementById('catSortOrder').value;
    catalogueState.page = 1;
    loadCatalogueProducts();
}

function changeCataloguePage(delta) {
    const newPage = catalogueState.page + delta;
    if (newPage >= 1 && newPage <= catalogueState.totalPages) {
        catalogueState.page = newPage;
        loadCatalogueProducts();
    }
}

// ==========================================
// ADD / EDIT PRODUCT MODAL
// ==========================================

async function loadSupplierDropdown(selectedId = null) {
    const sel = document.getElementById('prodFormSupplier');
    if (!sel) return;
    try {
        const res = await fetch('/api/suppliers');
        const data = await res.json();
        let html = '<option value="">No Supplier Assigned</option>';
        if (data.suppliers) {
            data.suppliers.forEach(s => {
                const isSel = (s.id == selectedId) ? 'selected' : '';
                html += `<option value="${s.id}" ${isSel}>${escapeHtml(s.name)}</option>`;
            });
        }
        sel.innerHTML = html;
    } catch (e) {
        console.warn('Failed to load suppliers:', e);
    }
}

function openAddProductModal() {
    document.getElementById('productFormTitle').textContent = 'ADD PRODUCT TO CATALOGUE';
    document.getElementById('prodFormId').value = '';
    document.getElementById('productForm').reset();
    document.getElementById('prodFormOpeningStockGroup').style.display = 'flex';
    document.getElementById('prodFormOpeningStock').disabled = false;

    loadSupplierDropdown();
    document.getElementById('productFormModal').style.display = 'flex';
}

async function openEditProductModal(productId) {
    try {
        const res = await fetch(`/api/products/${productId}`);
        const data = await res.json();
        if (!res.ok || !data.success || !data.product) {
            alert(`Error loading product: ${data.error || 'Not found'}`);
            return;
        }

        const p = data.product;
        document.getElementById('productFormTitle').textContent = `EDIT PRODUCT — ${p.name.toUpperCase()}`;
        document.getElementById('prodFormId').value = p.id;
        document.getElementById('prodFormName').value = p.name || '';
        document.getElementById('prodFormSku').value = p.sku || '';
        document.getElementById('prodFormCategory').value = p.category || '';
        document.getElementById('prodFormBrand').value = p.brand || '';
        document.getElementById('prodFormUnit').value = p.unit || 'piece';
        document.getElementById('prodFormPurchasePrice').value = p.purchase_price || 0;
        document.getElementById('prodFormSellingPrice').value = p.selling_price || 0;
        document.getElementById('prodFormReorderLevel').value = p.reorder_level || 0;
        document.getElementById('prodFormDescription').value = p.description || '';

        // Disallow direct stock editing on update as required by specs
        document.getElementById('prodFormOpeningStockGroup').style.display = 'none';
        document.getElementById('prodFormOpeningStock').disabled = true;

        await loadSupplierDropdown(p.supplier_id);
        document.getElementById('productFormModal').style.display = 'flex';
    } catch (e) {
        alert(`Error opening product: ${e.message}`);
    }
}

function closeProductFormModal() {
    document.getElementById('productFormModal').style.display = 'none';
}

async function handleProductFormSubmit(e) {
    e.preventDefault();
    const id = document.getElementById('prodFormId').value;
    const submitBtn = document.getElementById('prodFormSubmitBtn');
    submitBtn.disabled = true;

    const payload = {
        name: document.getElementById('prodFormName').value.trim(),
        sku: document.getElementById('prodFormSku').value.trim() || null,
        category: document.getElementById('prodFormCategory').value.trim() || null,
        brand: document.getElementById('prodFormBrand').value.trim() || null,
        unit: document.getElementById('prodFormUnit').value.trim() || 'piece',
        supplier_id: document.getElementById('prodFormSupplier').value || null,
        purchase_price: parseFloat(document.getElementById('prodFormPurchasePrice').value) || 0,
        selling_price: parseFloat(document.getElementById('prodFormSellingPrice').value) || 0,
        reorder_level: parseFloat(document.getElementById('prodFormReorderLevel').value) || 0,
        description: document.getElementById('prodFormDescription').value.trim() || null
    };

    if (!id) {
        // Only include opening_stock on creation
        payload.opening_stock = parseFloat(document.getElementById('prodFormOpeningStock').value) || 0;
    }

    try {
        const url = id ? `/api/products/${id}` : '/api/products';
        const method = id ? 'PATCH' : 'POST';

        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            alert(`Validation Error: ${data.error || 'Failed to save product'}`);
            submitBtn.disabled = false;
            return;
        }

        closeProductFormModal();
        loadCatalogueProducts();
        fetchCatalogueSummary();
        logTerminal(`Product ${payload.name} successfully ${id ? 'updated' : 'registered in catalogue'}.`, 'jarvis');
        jarvisSpeak(`Product ${payload.name} saved successfully.`);
    } catch (err) {
        alert(`Error: ${err.message}`);
    } finally {
        submitBtn.disabled = false;
    }
}

// ==========================================
// STOCK ADJUSTMENT MODAL
// ==========================================

async function openStockAdjustModal(productId, defaultType = 'receipt') {
    try {
        const res = await fetch(`/api/products/${productId}`);
        const data = await res.json();
        if (!res.ok || !data.success || !data.product) {
            alert(`Product not found: ${data.error || ''}`);
            return;
        }

        currentAdjustProduct = data.product;
        document.getElementById('adjustProdId').value = currentAdjustProduct.id;
        document.getElementById('adjustProdName').textContent = currentAdjustProduct.name;
        document.getElementById('adjustCurrentStock').textContent = currentAdjustProduct.quantity_on_hand;
        document.getElementById('adjustProdUnit').textContent = currentAdjustProduct.unit || 'piece';

        document.getElementById('adjustMovementType').value = defaultType;
        document.getElementById('adjustDelta').value = '';
        document.getElementById('adjustReason').value = '';
        document.getElementById('adjustReference').value = '';
        document.getElementById('adjustErrorAlert').style.display = 'none';

        onMovementTypeChange();
        calculateAdjustPreview();
        document.getElementById('stockAdjustModal').style.display = 'flex';
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

function onMovementTypeChange() {
    const mType = document.getElementById('adjustMovementType').value;
    const label = document.getElementById('adjustDeltaLabel');
    const reasonInput = document.getElementById('adjustReason');

    if (mType === 'receipt') {
        label.textContent = 'RECEIPT QUANTITY (+) *';
        reasonInput.placeholder = 'e.g. Received shipment from supplier';
    } else if (mType === 'sale') {
        label.textContent = 'SOLD QUANTITY (-) *';
        reasonInput.placeholder = 'e.g. Customer direct sale';
    } else if (mType === 'return') {
        label.textContent = 'RETURNED QUANTITY (+) *';
        reasonInput.placeholder = 'e.g. Customer returned undamaged product';
    } else {
        label.textContent = 'ADJUSTMENT DELTA (+ / -) *';
        reasonInput.placeholder = 'e.g. Cycle count variance, Damaged in warehouse';
    }
    calculateAdjustPreview();
}

function calculateAdjustPreview() {
    if (!currentAdjustProduct) return;
    const mType = document.getElementById('adjustMovementType').value;
    const rawVal = parseFloat(document.getElementById('adjustDelta').value) || 0;
    const current = parseFloat(currentAdjustProduct.quantity_on_hand) || 0;

    let delta = rawVal;
    if (mType === 'sale' && delta > 0) {
        delta = -delta;
    }

    const nextBal = current + delta;

    document.getElementById('previewBeforeQty').textContent = current;
    document.getElementById('previewDeltaQty').textContent = (delta >= 0 ? `+${delta}` : `${delta}`);
    document.getElementById('previewAfterQty').textContent = nextBal;

    const errorAlert = document.getElementById('adjustErrorAlert');
    const submitBtn = document.getElementById('adjustSubmitBtn');

    if (nextBal < 0) {
        errorAlert.style.display = 'block';
        errorAlert.textContent = `Adjustment rejected: resulting balance would be negative (${nextBal}). Current stock is ${current}.`;
        submitBtn.disabled = true;
    } else {
        errorAlert.style.display = 'none';
        submitBtn.disabled = false;
    }
}

function closeStockAdjustModal() {
    document.getElementById('stockAdjustModal').style.display = 'none';
    currentAdjustProduct = null;
}

async function handleStockAdjustSubmit(e) {
    e.preventDefault();
    if (!currentAdjustProduct) return;

    const productId = currentAdjustProduct.id;
    const mType = document.getElementById('adjustMovementType').value;
    let rawVal = parseFloat(document.getElementById('adjustDelta').value);
    const reason = document.getElementById('adjustReason').value.trim();
    const reference = document.getElementById('adjustReference').value.trim() || null;

    if (isNaN(rawVal) || rawVal === 0) {
        alert('Quantity change must be a non-zero number.');
        return;
    }

    if (!reason) {
        alert('Reason is required for all stock adjustments.');
        return;
    }

    let delta = rawVal;
    if (mType === 'sale' && delta > 0) {
        delta = -delta;
    }

    const submitBtn = document.getElementById('adjustSubmitBtn');
    submitBtn.disabled = true;

    try {
        const res = await fetch(`/api/products/${productId}/inventory-movements`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                movement_type: mType,
                quantity_delta: delta,
                reason: reason,
                reference: reference
            })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            alert(`Validation Error: ${data.error || 'Failed to adjust stock'}`);
            submitBtn.disabled = false;
            return;
        }

        closeStockAdjustModal();
        loadCatalogueProducts();
        fetchCatalogueSummary();
        if (catalogueState.activeTab === 'inventory') loadCatalogueInventory();
        if (catalogueState.activeTab === 'movements') loadCatalogueMovements();

        logTerminal(`Stock adjustment for ${currentAdjustProduct.name}: ${delta >= 0 ? '+' : ''}${delta} ${currentAdjustProduct.unit}. New balance: ${data.quantity_after}.`, 'jarvis');
        jarvisSpeak(`Stock updated. Current balance is ${data.quantity_after} ${currentAdjustProduct.unit}.`);
    } catch (err) {
        alert(`Error: ${err.message}`);
    } finally {
        submitBtn.disabled = false;
    }
}

// ==========================================
// PRODUCT DETAIL & MOVEMENT HISTORY DRAWER
// ==========================================

async function openProductDetailModal(productId) {
    try {
        const res = await fetch(`/api/products/${productId}`);
        const data = await res.json();
        if (!res.ok || !data.success || !data.product) {
            alert(`Product not found: ${data.error || ''}`);
            return;
        }

        const p = data.product;
        currentDetailProduct = p;

        document.getElementById('detailProdName').textContent = p.name;
        document.getElementById('detailProdSku').textContent = `SKU: ${p.sku || 'N/A'}`;

        const costStr = (p.purchase_price !== null && p.purchase_price !== undefined) ? `${p.purchase_price.toFixed(2)} ${p.currency || 'INR'}` : '--';
        const priceStr = (p.selling_price !== null && p.selling_price !== undefined) ? `${p.selling_price.toFixed(2)} ${p.currency || 'INR'}` : '--';
        const profitStr = (p.gross_profit !== null && p.gross_profit !== undefined) ? `${p.gross_profit.toFixed(2)} ${p.currency || 'INR'}` : '--';
        const marginStr = (p.gross_margin_pct !== null && p.gross_margin_pct !== undefined) ? `${p.gross_margin_pct}%` : '--';
        const markupStr = (p.markup_pct !== null && p.markup_pct !== undefined) ? `${p.markup_pct}%` : '--';

        document.getElementById('detailCost').textContent = costStr;
        document.getElementById('detailPrice').textContent = priceStr;
        document.getElementById('detailProfit').textContent = profitStr;
        document.getElementById('detailMargin').textContent = marginStr;
        document.getElementById('detailMarkup').textContent = markupStr;
        document.getElementById('detailStock').textContent = `${p.quantity_on_hand} ${p.unit || 'piece'}`;

        document.getElementById('detailCategory').textContent = p.category || '--';
        document.getElementById('detailBrand').textContent = p.brand || '--';
        document.getElementById('detailSupplier').textContent = p.supplier_name || 'None Assigned';
        document.getElementById('detailReorder').textContent = `${p.reorder_level} ${p.unit || 'piece'}`;
        document.getElementById('detailStatus').innerHTML = p.is_active ? '<span style="color: #00ff80;">ACTIVE</span>' : '<span style="color: var(--red);">INACTIVE</span>';
        document.getElementById('detailCreated').textContent = p.created_at ? new Date(p.created_at).toLocaleString() : '--';
        document.getElementById('detailUpdated').textContent = p.updated_at ? new Date(p.updated_at).toLocaleString() : '--';
        document.getElementById('detailDescription').textContent = p.description || 'No description provided.';

        // Render Recent Movements
        const movTbody = document.getElementById('detailMovementsTbody');
        const movs = p.recent_movements || [];
        if (movs.length === 0) {
            movTbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No movement history logged yet.</td></tr>';
        } else {
            let mHtml = '';
            movs.forEach(m => {
                const dt = m.created_at ? new Date(m.created_at).toLocaleString() : '--';
                const deltaColor = m.quantity_delta > 0 ? '#00ff80' : 'var(--red)';
                const deltaSign = m.quantity_delta > 0 ? `+${m.quantity_delta}` : `${m.quantity_delta}`;
                mHtml += `
                    <tr>
                        <td style="color: var(--text-muted);">${dt}</td>
                        <td><span class="bi-badge">${escapeHtml(m.movement_type)}</span></td>
                        <td style="color: ${deltaColor}; font-weight: 700;">${deltaSign}</td>
                        <td style="font-weight: 600;">${m.quantity_after}</td>
                        <td style="color: var(--text-muted);">${escapeHtml(m.reason || '')}</td>
                        <td>${escapeHtml(m.reference || '--')}</td>
                    </tr>
                `;
            });
            movTbody.innerHTML = mHtml;
        }

        // Configure action buttons in detail drawer
        document.getElementById('detailAdjustBtn').onclick = () => {
            closeProductDetailModal();
            openStockAdjustModal(p.id, 'receipt');
        };

        document.getElementById('detailEditBtn').onclick = () => {
            closeProductDetailModal();
            openEditProductModal(p.id);
        };

        const deactBtn = document.getElementById('detailDeactivateBtn');
        if (p.is_active) {
            deactBtn.style.display = 'inline-block';
            deactBtn.onclick = () => deactivateProduct(p.id);
        } else {
            deactBtn.style.display = 'none';
        }

        document.getElementById('productDetailModal').style.display = 'flex';
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

function closeProductDetailModal() {
    document.getElementById('productDetailModal').style.display = 'none';
    currentDetailProduct = null;
}

// Deactivate Product
async function deactivateProduct(productId) {
    if (!confirm('Are you sure you want to mark this product inactive? Historical movement records and inventory balances will be preserved.')) {
        return;
    }

    try {
        const res = await fetch(`/api/products/${productId}/deactivate`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) {
            alert(`Error: ${data.error || 'Failed to deactivate'}`);
            return;
        }

        closeProductDetailModal();
        loadCatalogueProducts();
        fetchCatalogueSummary();
        logTerminal(`Product ${productId} marked inactive.`, 'jarvis');
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

// ==========================================
// SPREADSHEET IMPORT & LEDGER SYNC CONTROLLER
// ==========================================

let currentSyncPurpose = 'catalogue';

const SYNC_PURPOSE_FIELDS = {
    catalogue: [
        { id: 'name', label: 'PRODUCT NAME *', required: true },
        { id: 'sku', label: 'SKU / PRODUCT CODE' },
        { id: 'category', label: 'CATEGORY' },
        { id: 'brand', label: 'BRAND' },
        { id: 'supplier', label: 'SUPPLIER' },
        { id: 'purchase_price', label: 'PURCHASE PRICE / COST' },
        { id: 'selling_price', label: 'SELLING PRICE' },
        { id: 'unit', label: 'UNIT (piece, kg, etc.)' },
        { id: 'opening_stock', label: 'OPENING STOCK' },
        { id: 'reorder_level', label: 'REORDER THRESHOLD' }
    ],
    purchases: [
        { id: 'product', label: 'PRODUCT IDENTIFIER (NAME OR SKU) *', required: true },
        { id: 'sku', label: 'SKU / ITEM CODE' },
        { id: 'quantity', label: 'PURCHASE QUANTITY *', required: true },
        { id: 'unit_price', label: 'PURCHASE UNIT RATE *', required: true },
        { id: 'purchase_date', label: 'PURCHASE DATE (YYYY-MM-DD)' },
        { id: 'purchase_number', label: 'PO / BILL NUMBER' },
        { id: 'supplier', label: 'SUPPLIER / VENDOR' },
        { id: 'notes', label: 'NOTES / REMARKS' }
    ],
    sales: [
        { id: 'product', label: 'PRODUCT IDENTIFIER (NAME OR SKU) *', required: true },
        { id: 'sku', label: 'SKU / ITEM CODE' },
        { id: 'quantity', label: 'SOLD QUANTITY *', required: true },
        { id: 'unit_price', label: 'SELLING PRICE / RATE *', required: true },
        { id: 'sale_date', label: 'SALE / INVOICE DATE (YYYY-MM-DD)' },
        { id: 'invoice_number', label: 'INVOICE / BILL NUMBER' },
        { id: 'customer_name', label: 'CUSTOMER / CLIENT NAME' },
        { id: 'notes', label: 'NOTES / REMARKS' }
    ],
    inventory_adjustments: [
        { id: 'product', label: 'PRODUCT IDENTIFIER (NAME OR SKU) *', required: true },
        { id: 'sku', label: 'SKU / ITEM CODE' },
        { id: 'quantity_delta', label: 'QUANTITY DELTA (+ / -) *', required: true },
        { id: 'reason', label: 'REASON FOR ADJUSTMENT *', required: true },
        { id: 'reference', label: 'AUDIT / REFERENCE NUMBER' }
    ]
};

async function openSpreadsheetMappingModal(datasetId = null) {
    const targetId = datasetId || activeDatasetId;
    if (!targetId) {
        alert('No spreadsheet dataset selected. Please import an Excel/CSV file or open a dataset from the Saved Data Library first.');
        return;
    }

    mappingDatasetId = targetId;
    currentSyncPurpose = 'catalogue';
    const purpSel = document.getElementById('syncPurposeSelect');
    if (purpSel) purpSel.value = 'catalogue';

    await loadMappingForPurpose('catalogue');
    document.getElementById('spreadsheetMappingModal').style.display = 'flex';
}

async function onSyncPurposeChange() {
    const purpSel = document.getElementById('syncPurposeSelect');
    currentSyncPurpose = purpSel ? purpSel.value : 'catalogue';
    
    // Toggle dupStrategy row (only relevant for catalogue)
    const dupRow = document.getElementById('dupStrategyRow');
    if (dupRow) {
        dupRow.style.display = (currentSyncPurpose === 'catalogue') ? 'flex' : 'none';
    }

    // Update Commit button label
    const commitBtn = document.getElementById('commitImportBtn');
    if (commitBtn) {
        if (currentSyncPurpose === 'purchases') commitBtn.textContent = '⚡ CONFIRM & COMMIT PURCHASES LEDGER';
        else if (currentSyncPurpose === 'sales') commitBtn.textContent = '⚡ CONFIRM & COMMIT SALES LEDGER';
        else if (currentSyncPurpose === 'inventory_adjustments') commitBtn.textContent = '⚡ CONFIRM & COMMIT STOCK ADJUSTMENTS';
        else commitBtn.textContent = '⚡ CONFIRM & COMMIT TO CATALOGUE';
    }

    await loadMappingForPurpose(currentSyncPurpose);
}

async function loadMappingForPurpose(purpose) {
    try {
        const res = await fetch(`/api/datasets/${mappingDatasetId}/suggest-mapping?purpose=${purpose}`);
        const data = await res.json();
        if (!res.ok || !data.success) {
            alert(`Error loading column mapping: ${data.error || 'Dataset not found'}`);
            return;
        }

        mappingDatasetColumns = data.columns || [];
        const suggested = data.suggested_mapping || {};
        const fields = SYNC_PURPOSE_FIELDS[purpose] || SYNC_PURPOSE_FIELDS.catalogue;

        const grid = document.getElementById('mappingFieldsGrid');
        let html = '';

        fields.forEach(f => {
            const suggestedCol = suggested[f.id] || '';
            let optHtml = `<option value="">-- Do Not Map --</option>`;
            mappingDatasetColumns.forEach(col => {
                const isSel = (col === suggestedCol) ? 'selected' : '';
                optHtml += `<option value="${escapeHtml(col)}" ${isSel}>${escapeHtml(col)}</option>`;
            });

            html += `
                <div class="mapping-field-item">
                    <label>${f.label}</label>
                    <select id="mapCol_${f.id}" class="cat-select" onchange="resetMappingCommitBtn()">
                        ${optHtml}
                    </select>
                </div>
            `;
        });

        grid.innerHTML = html;
        document.getElementById('mappingResultBox').style.display = 'none';
        document.getElementById('commitImportBtn').disabled = true;
    } catch (e) {
        alert(`Error configuring mapping for ${purpose}: ${e.message}`);
    }
}

function closeSpreadsheetMappingModal() {
    document.getElementById('spreadsheetMappingModal').style.display = 'none';
    mappingDatasetId = null;
}

function resetMappingCommitBtn() {
    document.getElementById('commitImportBtn').disabled = true;
}

function gatherColumnMapping() {
    const fields = SYNC_PURPOSE_FIELDS[currentSyncPurpose] || SYNC_PURPOSE_FIELDS.catalogue;
    const mapping = {};
    fields.forEach(f => {
        const sel = document.getElementById(`mapCol_${f.id}`);
        if (sel && sel.value) {
            mapping[f.id] = sel.value;
        }
    });
    return mapping;
}

async function runMappingPreview() {
    const mapping = gatherColumnMapping();
    if (currentSyncPurpose === 'catalogue') {
        if (!mapping.name) {
            alert("You must map at least the 'PRODUCT NAME' column.");
            return;
        }
    } else {
        if (!mapping.product && !mapping.sku && !mapping.name) {
            alert("You must map at least the 'PRODUCT IDENTIFIER' or 'SKU' column.");
            return;
        }
    }

    try {
        const res = await fetch(`/api/datasets/${mappingDatasetId}/product-import/preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                column_mapping: mapping,
                sync_purpose: currentSyncPurpose
            })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            alert(`Preview Error: ${data.error || 'Failed to parse records'}`);
            return;
        }

        document.getElementById('mapValidCount').textContent = data.valid_count || 0;
        document.getElementById('mapDuplicateCount').textContent = data.duplicate_count || 0;
        document.getElementById('mapInvalidCount').textContent = data.invalid_count || 0;
        document.getElementById('mapTotalCount').textContent = data.total_rows || 0;

        // Transaction telemetry banner
        const txnRow = document.getElementById('mappingTxnSummaryRow');
        const txnText = document.getElementById('mapTxnSummaryText');
        if (currentSyncPurpose !== 'catalogue') {
            txnRow.style.display = 'block';
            let summaryParts = [];
            if (data.matched_count !== undefined) summaryParts.push(`Matched Products: ${data.matched_count}`);
            if (data.unmatched_count !== undefined && data.unmatched_count > 0) summaryParts.push(`Unmatched Products: ${data.unmatched_count}`);
            if (data.proposed_stock_additions !== undefined && data.proposed_stock_additions > 0) summaryParts.push(`Proposed Stock Inflow: +${data.proposed_stock_additions}`);
            if (data.proposed_stock_deductions !== undefined && data.proposed_stock_deductions > 0) summaryParts.push(`Proposed Stock Outflow: -${data.proposed_stock_deductions}`);
            txnText.textContent = summaryParts.join(' | ');
        } else {
            txnRow.style.display = 'none';
        }

        // Errors list
        const errorsContainer = document.getElementById('mappingErrorsContainer');
        const errorsList = document.getElementById('mappingErrorsList');
        window.lastMappingErrors = data.errors || [];
        if (data.errors && data.errors.length > 0) {
            errorsContainer.style.display = 'block';
            let errHtml = '';
            data.errors.forEach(err => {
                errHtml += `<li>Row ${err.row}: ${escapeHtml(err.message)}</li>`;
            });
            errorsList.innerHTML = errHtml;
        } else {
            errorsContainer.style.display = 'none';
        }

        // Sample Table
        const sampleTbody = document.getElementById('mappingSampleTbody');
        const samples = data.sample_preview || [];
        let sHtml = '';
        samples.forEach(s => {
            let badge = '';
            if (s.status === 'valid') badge = '<span class="status-pill in-stock">VALID</span>';
            else if (s.status === 'duplicate') badge = '<span class="status-pill low-stock">DUPLICATE</span>';
            else badge = '<span class="status-pill out-of-stock">INVALID</span>';

            sHtml += `
                <tr>
                    <td style="color: var(--text-muted);">${s.row_index}</td>
                    <td style="font-weight: 600; color: #fff;">${escapeHtml(s.name || s.product || '--')}</td>
                    <td style="color: var(--cyan);">${escapeHtml(s.sku || '--')}</td>
                    <td>${s.purchase_price || s.unit_price || '--'}</td>
                    <td>${s.selling_price || '--'}</td>
                    <td>${s.opening_stock || s.quantity || s.quantity_delta || '--'}</td>
                    <td>${s.reorder_level || s.purchase_number || s.invoice_number || '--'}</td>
                    <td>${badge}</td>
                </tr>
            `;
        });
        sampleTbody.innerHTML = sHtml;

        document.getElementById('mappingResultBox').style.display = 'flex';

        // Enable commit if there are valid or duplicate items
        const commitBtn = document.getElementById('commitImportBtn');
        if (data.valid_count > 0 || (currentSyncPurpose === 'catalogue' && data.duplicate_count > 0)) {
            commitBtn.disabled = false;
        } else {
            commitBtn.disabled = true;
        }
    } catch (e) {
        alert(`Error previewing mapping: ${e.message}`);
    }
}

async function commitSpreadsheetImport() {
    const mapping = gatherColumnMapping();
    if (currentSyncPurpose === 'catalogue') {
        if (!mapping.name) {
            alert("You must map at least the 'PRODUCT NAME' column.");
            return;
        }
    } else {
        if (!mapping.product && !mapping.sku && !mapping.name) {
            alert("You must map at least the 'PRODUCT IDENTIFIER' or 'SKU' column.");
            return;
        }
    }

    const dupStrategyEl = document.querySelector('input[name="dupStrategy"]:checked');
    const dupStrategy = dupStrategyEl ? dupStrategyEl.value : 'skip_existing';
    const purposeName = currentSyncPurpose.replace('_', ' ').toUpperCase();
    const confirmMsg = `Are you sure you want to commit these records into the ${purposeName} database?`;

    if (!confirm(confirmMsg)) {
        return;
    }

    const commitBtn = document.getElementById('commitImportBtn');
    commitBtn.disabled = true;

    try {
        const res = await fetch(`/api/datasets/${mappingDatasetId}/product-import/commit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                column_mapping: mapping,
                duplicate_strategy: dupStrategy,
                sync_purpose: currentSyncPurpose
            })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            alert(`Commit Error: ${data.error || 'Failed to commit synchronization'}`);
            commitBtn.disabled = false;
            return;
        }

        if (currentSyncPurpose === 'catalogue') {
            alert(`Catalogue Import Complete!\n- Newly Created Products: ${data.created_count}\n- Updated Existing Products: ${data.updated_count}\n- Skipped Records: ${data.skipped_count}\n- Row Errors: ${data.error_count}`);
        } else {
            alert(`Ledger Synchronization Complete!\n- Recorded Transactions: ${data.recorded_transactions || data.created_count || 0}\n- Stock Movements: ${data.recorded_movements || 0}\n- Previously Synchronized / Skipped: ${data.previously_imported_count || data.skipped_count || 0}\n- Row Errors: ${data.error_count}`);
        }

        closeSpreadsheetMappingModal();
        fetchCatalogueSummary();
        openCatalogueModal();
        logTerminal(`Synchronization complete for ${purposeName}: ${data.recorded_transactions || data.created_count} recorded, ${data.error_count} errors.`, 'jarvis');
        jarvisSpeak(`Synchronization complete for ${purposeName}.`);
    } catch (e) {
        alert(`Error committing import: ${e.message}`);
        commitBtn.disabled = false;
    }
}

function downloadMappingErrors() {
    const errs = window.lastMappingErrors || [];
    if (!errs || errs.length === 0) {
        alert("No validation errors to export.");
        return;
    }
    const blob = new Blob([JSON.stringify(errs, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `catalogue_import_errors_${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}



