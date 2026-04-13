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
  const _STAGE_LOSS = { 0: 0, 1: 2, 2: 8, 3: 18, 4: 32 };

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
        height_cm:         cc.height_cm || 175,
        face_desc:         cc.face_desc || '',
        personality:       cc.personality || 'stoic',
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
      hair_color:    'black',
      eye_color:     'brown',
      build:         'average',
      background:    'warrior',
      sin:           'pride',
      attraction:    'female-leaning',
      secret:        '',
      tone:          'conflict',
      height_cm:     175,
      face_desc:     '',
      personality:   'stoic',
    };

    // -----------------------------------------------------------------------
    // Live preview updater
    // -----------------------------------------------------------------------
    function _updatePreview() {
      const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      const nameVal = (document.getElementById('cc-name') || {}).value || cc.name || '—';
      setTxt('cc-prev-name',        nameVal || '—');
      setTxt('cc-prev-height',      cc.height_cm + 'cm');
      setTxt('cc-prev-build',       _capitalize(cc.build));
      setTxt('cc-prev-hair',        _capitalize(cc.hair_color));
      setTxt('cc-prev-eyes',        _capitalize(cc.eye_color));
      setTxt('cc-prev-bg',          _capitalize(cc.background));
      setTxt('cc-prev-sin',         _capitalize(cc.sin));
      setTxt('cc-prev-personality', _capitalize(cc.personality));
      setTxt('cc-prev-tone',        _capitalize(cc.tone));
      const stage4h = Math.round(cc.height_cm - (_STAGE_LOSS[4] || 32));
      setTxt('cc-prev-stage4-h', stage4h);
      // Face desc row
      const faceRow = document.getElementById('cc-prev-face-row');
      const faceVal = document.getElementById('cc-prev-face');
      const faceInput = (document.getElementById('cc-face-desc') || {}).value || cc.face_desc || '';
      if (faceRow && faceVal) {
        faceRow.hidden = !faceInput;
        faceVal.textContent = faceInput;
      }
    }

    function _capitalize(s) {
      if (!s) return '';
      return s.charAt(0).toUpperCase() + s.slice(1).replace(/-/g, ' ');
    }

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

    function _wireGroupWithPreview(containerId, stateKey) {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.querySelectorAll('[data-val],[data-bg],[data-attr]').forEach(btn => {
        btn.addEventListener('click', () => {
          container.querySelectorAll('.active').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          const val = btn.dataset.val || btn.dataset.bg || btn.dataset.attr;
          cc[stateKey] = val;
          _updatePreview();
        });
      });
    }

    _wireGroupWithPreview('cc-gender-choices',        'gender');
    _wireGroupWithPreview('cc-hair-choices',          'hair_color');
    _wireGroupWithPreview('cc-eye-choices',           'eye_color');
    _wireGroupWithPreview('cc-build-choices',         'build');
    _wireGroupWithPreview('background-choices',       'background');
    _wireGroupWithPreview('cc-sin-choices',           'sin');
    _wireGroupWithPreview('attraction-choices',       'attraction');
    _wireGroupWithPreview('cc-tone-choices',          'tone');
    _wireGroupWithPreview('cc-personality-choices',   'personality');

    // Height slider
    const heightSlider = document.getElementById('cc-height');
    const heightDisplay = document.getElementById('cc-height-display');
    const heightStage4 = document.getElementById('cc-height-stage4-display');
    if (heightSlider) {
      heightSlider.addEventListener('input', () => {
        const h = parseInt(heightSlider.value);
        cc.height_cm = h;
        if (heightDisplay) heightDisplay.textContent = h;
        if (heightStage4) heightStage4.textContent = h - (_STAGE_LOSS[4] || 32);
        _updatePreview();
      });
    }

    // Face description input
    const faceDescInput = document.getElementById('cc-face-desc');
    const faceCountEl   = document.getElementById('cc-face-count');
    if (faceDescInput) {
      faceDescInput.addEventListener('input', () => {
        cc.face_desc = faceDescInput.value.slice(0, 60);
        if (faceCountEl) faceCountEl.textContent = faceDescInput.value.length;
        _updatePreview();
      });
    }

    // Name input → preview
    const nameInput = document.getElementById('cc-name');
    if (nameInput) {
      nameInput.addEventListener('input', () => _updatePreview());
    }

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
      _updatePreview();
    }

    function _renderSummary() {
      const el = document.getElementById('cc-summary');
      if (!el) return;
      const SIN_SYMBOLS = {pride:'♦',lust:'♥',sloth:'♠',wrath:'♣',envy:'★',greed:'$',gluttony:'●'};
      const name = (document.getElementById('cc-name') || {}).value || '(unnamed)';
      cc.name = name;
      cc.secret   = (document.getElementById('cc-secret')   || {}).value || '';
      cc.face_desc = (document.getElementById('cc-face-desc') || {}).value || '';
      const stage4h = Math.round(cc.height_cm - (_STAGE_LOSS[4] || 32));
      el.innerHTML = `
        <div class="cc-summary-row"><span class="cc-sum-label">Name</span><span>${_escHtml(name)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Gender</span><span>${_escHtml(cc.gender)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Height</span><span>${cc.height_cm}cm <span class="cc-sum-dim">(→ ${stage4h}cm at Stage 4)</span></span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Appearance</span><span>${_escHtml(cc.hair_color)} hair, ${_escHtml(cc.eye_color)} eyes, ${_escHtml(cc.build)} build</span></div>
        ${cc.face_desc ? `<div class="cc-summary-row"><span class="cc-sum-label">Face</span><span>${_escHtml(cc.face_desc)}</span></div>` : ''}
        <div class="cc-summary-row"><span class="cc-sum-label">Background</span><span>${_escHtml(cc.background)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Sin</span><span>${SIN_SYMBOLS[cc.sin] || ''} ${_escHtml(cc.sin)}</span></div>
        <div class="cc-summary-row"><span class="cc-sum-label">Personality</span><span>${_escHtml(cc.personality)}</span></div>
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
          cc.secret    = (document.getElementById('cc-secret')   || {}).value || '';
          cc.face_desc = (document.getElementById('cc-face-desc') || {}).value || '';
          cc.height_cm = parseInt((document.getElementById('cc-height') || {}).value || 175);
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
