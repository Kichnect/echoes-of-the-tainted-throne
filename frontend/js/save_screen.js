/**
 * save_screen.js — Save slot selection and character creation
 *
 * Shows before the game loads. Fetches save list from API,
 * renders up to 3 slot cards, handles New Game / Continue / Delete.
 * Calls game.js init(saveId) when a slot is selected.
 */

(function () {
  'use strict';

  const API_BASE = 'http://localhost:8000';

  let _selectedBg   = 'warrior';
  let _selectedAttr = 'female-leaning';

  // -------------------------------------------------------------------------
  // Public interface (called from DOMContentLoaded in game.js)
  // -------------------------------------------------------------------------

  window.SaveScreen = {
    init,
  };

  async function init(onSaveSelected) {
    const screen = document.getElementById('save-screen');
    if (!screen) return;

    try {
      const saves = await _fetchSaveList();
      _renderSlots(saves, onSaveSelected);
    } catch (err) {
      const container = document.getElementById('save-slots');
      if (container) {
        container.innerHTML = `
          <div class="save-slot-error">
            Server not reachable. Start the backend:<br>
            <code>uvicorn main:app --reload</code>
          </div>`;
      }
    }

    _initCharCreate(onSaveSelected);
  }

  // -------------------------------------------------------------------------
  // API
  // -------------------------------------------------------------------------

  async function _fetchSaveList() {
    const res = await fetch(`${API_BASE}/api/saves/list`);
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  }

  async function _deleteSave(saveId) {
    await fetch(`${API_BASE}/api/saves/${saveId}`, { method: 'DELETE' });
  }

  async function _createSave(cc, onSaveSelected) {
    const API_BASE = 'http://localhost:8000';
    const res = await fetch(`${API_BASE}/api/saves/new`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        slot_name:         cc.name,
        champion_name:     cc.name,
        background:        cc.background,
        gender_attraction: cc.attraction,
        gender:            cc.gender,
        hair_color:        cc.hair_color,
        eye_color:         cc.eye_color,
        build:             cc.build,
        sin:               cc.sin,
        tone_preference:   cc.tone,
        champion_secret:   cc.secret || null,
      }),
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`${res.status}: ${detail}`);
    }
    const data = await res.json();
    const modal = document.getElementById('char-create-modal');
    if (modal) modal.hidden = true;
    _hideSaveScreen();
    onSaveSelected(data.save_id);
  }

  // -------------------------------------------------------------------------
  // Slot rendering
  // -------------------------------------------------------------------------

  function _renderSlots(saves, onSaveSelected) {
    const container = document.getElementById('save-slots');
    if (!container) return;

    container.innerHTML = saves.map((s, i) => {
      if (!s.exists) {
        return `
          <div class="save-slot empty" data-slot="${i}">
            <div class="save-slot-label">${_esc(s.slot_name)}</div>
            <div class="save-slot-empty-text">Empty</div>
            <button class="save-slot-btn new-game-btn" data-slot="${i}">New Game</button>
          </div>`;
      }
      const stageBar = _stageBarHtml(s.stage, s.corruption);
      return `
        <div class="save-slot occupied" data-save-id="${s.save_id}">
          <div class="save-slot-name">${_esc(s.champion_name)}</div>
          <div class="save-slot-meta">
            ${_esc(s.stage_name)} · Day ${s.days} · ${_esc(s.region)}
          </div>
          ${stageBar}
          <div class="save-slot-actions">
            <button class="save-slot-btn continue-btn" data-save-id="${s.save_id}">Continue</button>
            <button class="save-slot-btn delete-btn" data-save-id="${s.save_id}">Delete</button>
          </div>
        </div>`;
    }).join('');

    // Wire buttons
    container.querySelectorAll('.new-game-btn').forEach(btn => {
      btn.addEventListener('click', () => _showCharCreate());
    });

    container.querySelectorAll('.continue-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const saveId = parseInt(btn.dataset.saveId);
        _hideSaveScreen();
        onSaveSelected(saveId);
      });
    });

    container.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const saveId = parseInt(btn.dataset.saveId);
        if (!confirm('Delete this save? This cannot be undone.')) return;
        await _deleteSave(saveId);
        const saves = await _fetchSaveList();
        _renderSlots(saves, onSaveSelected);
      });
    });
  }

  function _stageBarHtml(stage, corruption) {
    const pct = Math.min(100, corruption);
    const stageColors = ['#5a5a5a', '#7a5a3a', '#8a5a4a', '#6a3a5a', '#8a4a6a'];
    const color = stageColors[stage] || stageColors[0];
    return `
      <div class="save-slot-bar-track">
        <div class="save-slot-bar-fill" style="width:${pct}%;background:${color}"></div>
      </div>
      <div class="save-slot-corruption">${pct.toFixed(1)}% corruption</div>`;
  }

  // -------------------------------------------------------------------------
  // Character creation
  // -------------------------------------------------------------------------

  function _showCharCreate() {
    const modal = document.getElementById('char-create-modal');
    if (modal) modal.hidden = false;
  }

  function _hideCharCreate() {
    const modal = document.getElementById('char-create-modal');
    if (modal) modal.hidden = true;
    const err = document.getElementById('cc-error');
    if (err) { err.hidden = true; err.textContent = ''; }
  }

  function _initCharCreate(onSaveSelected) {
    const modal    = document.getElementById('char-create-modal');
    const confirm  = document.getElementById('cc-confirm');
    const back     = document.getElementById('cc-back');
    const cancel   = document.getElementById('cc-cancel');
    const errorEl  = document.getElementById('cc-error');
    const TOTAL_STEPS = 6;
    let currentStep = 1;

    // State object that accumulates across steps
    const cc = {
      name:          '',
      gender:        'male',
      hair_color:    'brown',
      eye_color:     'brown',
      build:         'average',
      background:    'warrior',
      sin:           'pride',
      attraction:    'female-leaning',
      secret:        '',
      tone:          'conflict',
    };

    // Wire pill/card single-select groups
    function _wireGroup(containerId, stateKey) {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.querySelectorAll('[data-val],[data-bg],[data-attr]').forEach(btn => {
        btn.addEventListener('click', () => {
          container.querySelectorAll('.active').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          const val = btn.dataset.val || btn.dataset.bg || btn.dataset.attr;
          cc[stateKey] = val;
        });
      });
    }

    _wireGroup('cc-gender-choices',  'gender');
    _wireGroup('cc-hair-choices',    'hair_color');
    _wireGroup('cc-eye-choices',     'eye_color');
    _wireGroup('cc-build-choices',   'build');
    _wireGroup('background-choices', 'background');
    _wireGroup('cc-sin-choices',     'sin');
    _wireGroup('attraction-choices', 'attraction');
    _wireGroup('cc-tone-choices',    'tone');

    function _showStep(n) {
      for (let i = 1; i <= TOTAL_STEPS; i++) {
        const el = document.getElementById(`cc-step-${i}`);
        if (el) el.hidden = (i !== n);
      }
      document.querySelectorAll('.cc-dot').forEach(dot => {
        dot.classList.toggle('active', parseInt(dot.dataset.step) <= n);
      });
      if (back) back.hidden = (n <= 1);
      if (confirm) confirm.textContent = n < TOTAL_STEPS ? 'Next →' : 'Begin';
      if (n === TOTAL_STEPS) _renderSummary();
      currentStep = n;
    }

    function _renderSummary() {
      const el = document.getElementById('cc-summary');
      if (!el) return;
      const SIN_SYMBOLS = {pride:'♦',lust:'♥',sloth:'♠',wrath:'♣',envy:'★',greed:'$',gluttony:'●'};
      const name = (document.getElementById('cc-name') || {}).value || '(unnamed)';
      cc.name = name;
      cc.secret = (document.getElementById('cc-secret') || {}).value || '';
      el.innerHTML = `
        <div class="cc-summary-row"><span class="cc-sum-label">Name</span><span>${_escHtml(name)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Gender</span><span>${_escHtml(cc.gender)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Appearance</span><span>${_escHtml(cc.hair_color)} hair, ${_escHtml(cc.eye_color)} eyes, ${_escHtml(cc.build)} build</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Background</span><span>${_escHtml(cc.background)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Sin</span><span>${SIN_SYMBOLS[cc.sin] || ''} ${_escHtml(cc.sin)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Attraction</span><span>${_escHtml(cc.attraction)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Tone</span><span>${_escHtml(cc.tone)}</span></div>
        ${cc.secret ? `<div class="cc-summary-row"><span class="cc-sum-label">Secret</span><span><em>set</em></span></div>` : ''}
      `;
    }

    function _validateStep(n) {
      if (n === 1) {
        const name = (document.getElementById('cc-name') || {}).value || '';
        cc.name = name.trim();
        if (!cc.name) {
          if (errorEl) { errorEl.textContent = 'Enter a name.'; errorEl.hidden = false; }
          return false;
        }
      }
      if (errorEl) errorEl.hidden = true;
      return true;
    }

    function _escHtml(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    if (confirm) {
      confirm.addEventListener('click', async () => {
        if (!_validateStep(currentStep)) return;
        if (currentStep < TOTAL_STEPS) {
          _showStep(currentStep + 1);
        } else {
          // Final confirm — collect final fields and create save
          cc.secret = (document.getElementById('cc-secret') || {}).value || '';
          confirm.disabled = true;
          confirm.textContent = 'Creating…';
          try {
            await _createSave(cc, onSaveSelected);
          } catch (err) {
            if (errorEl) { errorEl.textContent = err.message; errorEl.hidden = false; }
            confirm.disabled = false;
            confirm.textContent = 'Begin';
          }
        }
      });
    }

    if (back) {
      back.addEventListener('click', () => {
        if (currentStep > 1) _showStep(currentStep - 1);
      });
    }

    if (cancel) {
      cancel.addEventListener('click', () => {
        if (modal) modal.hidden = true;
      });
    }

    document.addEventListener('keydown', function _ccKeys(e) {
      if (!modal || modal.hidden) return;
      if (e.key === 'Escape') { modal.hidden = true; document.removeEventListener('keydown', _ccKeys); }
    });

    _showStep(1);
  }

  function _showCharCreateError(msg) {
    const err = document.getElementById('cc-error');
    if (err) {
      err.textContent = msg;
      err.hidden = false;
    }
  }

  // -------------------------------------------------------------------------
  // Show/hide save screen
  // -------------------------------------------------------------------------

  function _hideSaveScreen() {
    const screen = document.getElementById('save-screen');
    if (screen) screen.setAttribute('aria-hidden', 'true');
  }

  // -------------------------------------------------------------------------
  // Utilities
  // -------------------------------------------------------------------------

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

}());
